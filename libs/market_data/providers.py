from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional, Protocol

from libs.market_data.symbols import (
    infer_exchange,
    normalize_provider_code,
    to_internal_symbol,
    to_provider_symbol,
)
from libs.quant_core.models import Instrument, MarketBar, RealtimeQuote


class MarketDataProvider(Protocol):
    provider_name: str

    def list_instruments(self) -> list[Instrument]:
        ...

    def get_bars(
        self,
        symbol: str,
        freq: str = "1d",
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> list[MarketBar]:
        ...

    def get_realtime_quotes(self, symbols: list[str]) -> list[RealtimeQuote]:
        ...


@dataclass(frozen=True)
class ProviderStatus:
    selected_provider: str
    active_provider: str
    akshare_installed: bool


def is_akshare_installed() -> bool:
    try:
        import akshare  # noqa: F401
    except Exception:
        return False
    return True


class AkshareMarketDataProvider:
    provider_name = "akshare"

    def __init__(self) -> None:
        try:
            import akshare as ak
        except Exception as exc:
            raise RuntimeError("akshare is not installed") from exc
        self.ak = ak

    def list_instruments(self) -> list[Instrument]:
        code_name_df = self.ak.stock_info_a_code_name()
        instruments: list[Instrument] = []

        for _, row in code_name_df.iterrows():
            code = str(row["code"]).strip()
            exchange = infer_exchange(code)
            instruments.append(
                Instrument(
                    symbol=to_internal_symbol(code, exchange),
                    exchange=exchange,
                    name=str(row["name"]).strip(),
                    industry="unknown",
                    list_date=None,
                    delist_date=None,
                    status="listed",
                    is_st="ST" in str(row["name"]).upper(),
                )
            )

        return instruments

    def _map_em_quotes(self, dataframe, symbols: list[str]) -> list[RealtimeQuote]:
        target_codes = {to_provider_symbol(symbol): symbol for symbol in symbols}
        filtered = dataframe[dataframe["代码"].astype(str).isin(target_codes.keys())]
        quotes: list[RealtimeQuote] = []
        quote_time = datetime.now()

        for _, row in filtered.iterrows():
            code = str(row["代码"]).strip()
            symbol = target_codes[code]
            last_price = float(row["最新价"])
            pct_change = float(row.get("涨跌幅", 0.0) or 0.0)
            quotes.append(
                RealtimeQuote(
                    symbol=symbol,
                    quote_time=quote_time,
                    last_price=last_price,
                    bid1=last_price,
                    ask1=last_price,
                    volume=int(float(row.get("成交量", 0.0) or 0.0)),
                    turnover=float(row.get("成交额", 0.0) or 0.0),
                    pct_change=pct_change,
                    limit_up=float(row.get("涨停价", 0.0) or 0.0) or last_price,
                    limit_down=float(row.get("跌停价", 0.0) or 0.0) or last_price,
                )
            )

        return quotes

    def _map_sina_quotes(self, dataframe, symbols: list[str]) -> list[RealtimeQuote]:
        target_codes = {to_provider_symbol(symbol): symbol for symbol in symbols}
        normalized_codes = dataframe["代码"].astype(str).map(normalize_provider_code)
        filtered = dataframe[normalized_codes.isin(target_codes.keys())]
        quotes: list[RealtimeQuote] = []
        quote_time = datetime.now()

        for _, row in filtered.iterrows():
            code = normalize_provider_code(str(row["代码"]))
            symbol = target_codes[code]
            last_price = float(row["最新价"])
            quotes.append(
                RealtimeQuote(
                    symbol=symbol,
                    quote_time=quote_time,
                    last_price=last_price,
                    bid1=float(row.get("买入", last_price) or last_price),
                    ask1=float(row.get("卖出", last_price) or last_price),
                    volume=int(float(row.get("成交量", 0.0) or 0.0)),
                    turnover=float(row.get("成交额", 0.0) or 0.0),
                    pct_change=float(row.get("涨跌幅", 0.0) or 0.0),
                    limit_up=last_price,
                    limit_down=last_price,
                )
            )

        return quotes

    def get_bars(
        self,
        symbol: str,
        freq: str = "1d",
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> list[MarketBar]:
        if freq != "1d":
            raise ValueError("AkShare provider currently supports daily bars only.")

        provider_symbol = to_provider_symbol(symbol)
        start_date = (start or date(2000, 1, 1)).strftime("%Y%m%d")
        end_date = (end or date.today()).strftime("%Y%m%d")
        dataframe = self.ak.stock_zh_a_hist(
            symbol=provider_symbol,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
        )

        if dataframe.empty:
            raise ValueError(f"No market bars found for {symbol}")

        bars: list[MarketBar] = []
        for _, row in dataframe.iterrows():
            bars.append(
                MarketBar(
                    symbol=to_internal_symbol(provider_symbol, symbol.split(".")[-1] if "." in symbol else None),
                    trade_date=datetime.strptime(str(row["日期"]), "%Y-%m-%d").date(),
                    open=float(row["开盘"]),
                    high=float(row["最高"]),
                    low=float(row["最低"]),
                    close=float(row["收盘"]),
                    volume=int(float(row["成交量"])),
                    amount=float(row["成交额"]),
                    turnover_rate=float(row.get("换手率", 0.0) or 0.0),
                    adj_type="qfq",
                    data_source=self.provider_name,
                )
            )

        return bars

    def get_realtime_quotes(self, symbols: list[str]) -> list[RealtimeQuote]:
        try:
            dataframe = self.ak.stock_zh_a_spot_em()
            if not dataframe.empty:
                return self._map_em_quotes(dataframe, symbols)
        except Exception:
            pass

        dataframe = self.ak.stock_zh_a_spot()
        if dataframe.empty:
            return []
        return self._map_sina_quotes(dataframe, symbols)
