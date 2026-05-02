"""Market data service with provider abstraction."""

from __future__ import annotations

from datetime import date
from typing import Optional

from apps.api.app.core.config import get_settings
from apps.api.app.services.sample_data import DAILY_BARS, INSTRUMENTS, REALTIME_QUOTES
from libs.market_data.cache import _TTLCache
from libs.market_data.providers import (
    AkshareMarketDataProvider,
    ProviderStatus,
    is_akshare_installed,
)
from libs.quant_core.models import Instrument, MarketBar, RealtimeQuote


class MockMarketDataProvider:
    """Mock provider — extended with 30+ stock universe + synthetic bars.

    For demo & scanner use without AKShare: uses `libs/market_data/universe.py`
    when a symbol isn't in the original sample DAILY_BARS, generating
    deterministic 60-day OHLC sequences with varied trend/volatility profiles.
    """
    provider_name = "mock"

    def list_instruments(self) -> list[Instrument]:
        # Combine legacy seed + extended universe (deduped)
        from libs.market_data.universe import UNIVERSE
        seen = {i.symbol for i in INSTRUMENTS}
        extra = [
            Instrument(
                symbol=u.symbol, exchange=u.symbol.split(".")[1],
                name=u.name, industry=u.industry,
                list_date=date(2010, 1, 1), delist_date=None,
                status="listed", is_st=u.is_st,
            )
            for u in UNIVERSE if u.symbol not in seen
        ]
        return INSTRUMENTS + extra

    # ≥300 trading days unlocks 1y in-sample + 1q OOS walk-forward folds.
    _SYNTH_DAYS = 320

    def get_bars(
        self,
        symbol: str,
        freq: str = "1d",
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> list[MarketBar]:
        if freq not in {"1d", "1m"}:
            raise ValueError(f"Unsupported frequency: {freq}")

        from libs.market_data.universe import UNIVERSE, generate_bars
        stock = next((u for u in UNIVERSE if u.symbol == symbol), None)

        # Strategy: synthesize ≥320 days for any symbol in UNIVERSE, then
        # OVERLAY the hand-crafted DAILY_BARS values for matching dates so
        # demos still see "real-looking" recent prices while backtests/
        # walk-forward get sufficient history.
        bars: list[MarketBar] = []
        if stock is not None:
            raw = generate_bars(stock, days=self._SYNTH_DAYS)
            bars = [
                MarketBar(
                    symbol=symbol, trade_date=d, open=o, high=h, low=l, close=c,
                    volume=v, amount=a, turnover_rate=t,
                    adj_type="qfq", data_source="mock",
                )
                for (d, o, h, l, c, v, a, t) in raw
            ]
        legacy = DAILY_BARS.get(symbol, [])
        if legacy:
            by_date = {b.trade_date: b for b in bars}
            for b in legacy:
                by_date[b.trade_date] = b   # legacy wins where overlapping
            bars = sorted(by_date.values(), key=lambda x: x.trade_date)
        if not bars:
            raise ValueError(f"Unknown symbol: {symbol}")

        if start is not None:
            bars = [item for item in bars if item.trade_date >= start]
        if end is not None:
            bars = [item for item in bars if item.trade_date <= end]

        return bars

    def get_realtime_quotes(self, symbols: list[str]) -> list[RealtimeQuote]:
        from libs.market_data.universe import UNIVERSE
        from datetime import datetime as _dt
        quotes: list[RealtimeQuote] = []
        universe_map = {u.symbol: u for u in UNIVERSE}

        for symbol in symbols:
            quote = REALTIME_QUOTES.get(symbol)
            if quote is not None:
                quotes.append(quote)
                continue
            # Synthesize quote from latest bar
            try:
                bars = self.get_bars(symbol, freq="1d")
            except ValueError:
                continue
            if not bars:
                continue
            last = bars[-1]
            stock = universe_map.get(symbol)
            limit_factor = 0.05 if (stock and stock.is_st) else 0.10
            quotes.append(RealtimeQuote(
                symbol=symbol, quote_time=_dt.now(),
                last_price=last.close,
                bid1=round(last.close * 0.999, 2),
                ask1=round(last.close * 1.001, 2),
                volume=last.volume, turnover=last.amount,
                pct_change=round(((last.close - last.open) / last.open) * 100, 2) if last.open else 0,
                limit_up=round(last.close * (1 + limit_factor), 2),
                limit_down=round(last.close * (1 - limit_factor), 2),
            ))

        return quotes


class MarketService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.mock_provider = MockMarketDataProvider()
        self.provider = self._build_provider()
        self.allow_runtime_fallback = self.settings.market_data_provider.lower() == "auto"
        # TTL caches: bars are slow (akshare hits the network), quotes refresh fast
        self._bars_cache = _TTLCache(max_size=128, ttl=300.0)     # 5 min
        self._quotes_cache = _TTLCache(max_size=64, ttl=3.0)      # 3 sec

    def _build_provider(self) -> MockMarketDataProvider | AkshareMarketDataProvider:
        provider_name = self.settings.market_data_provider.lower()

        if provider_name == "auto":
            if is_akshare_installed():
                return AkshareMarketDataProvider()
            return self.mock_provider

        if provider_name == "akshare":
            if not is_akshare_installed():
                raise RuntimeError(
                    "QUANT_MARKET_DATA_PROVIDER is set to akshare but akshare is not installed."
                )
            return AkshareMarketDataProvider()

        return self.mock_provider

    def _execute_with_fallback(self, action: str, *args: object, **kwargs: object) -> object:
        method = getattr(self.provider, action)
        try:
            return method(*args, **kwargs)
        except Exception:
            if not self.allow_runtime_fallback or self.provider.provider_name == "mock":
                raise
            fallback_method = getattr(self.mock_provider, action)
            return fallback_method(*args, **kwargs)

    def get_provider_status(self) -> ProviderStatus:
        return ProviderStatus(
            selected_provider=self.settings.market_data_provider,
            active_provider=self.provider.provider_name,
            akshare_installed=is_akshare_installed(),
        )

    def list_instruments(self) -> list[Instrument]:
        return self._execute_with_fallback("list_instruments")

    def get_bars(
        self,
        symbol: str,
        freq: str = "1d",
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> list[MarketBar]:
        key = (symbol, freq, start, end)
        hit, value = self._bars_cache.get(key)
        if hit:
            return value
        value = self._execute_with_fallback(
            "get_bars", symbol=symbol, freq=freq, start=start, end=end,
        )
        self._bars_cache.set(key, value)
        return value

    def get_realtime_quotes(self, symbols: list[str]) -> list[RealtimeQuote]:
        key = tuple(sorted(symbols))
        hit, value = self._quotes_cache.get(key)
        if hit:
            return value
        value = self._execute_with_fallback("get_realtime_quotes", symbols)
        self._quotes_cache.set(key, value)
        return value

    def cache_stats(self) -> dict:
        return {
            "bars": self._bars_cache.stats(),
            "quotes": self._quotes_cache.stats(),
        }
