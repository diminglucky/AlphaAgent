"""Position Monitor — actively watches every held position for sell triggers.

Runs continuously (every 30s) and emits a SellAlert whenever any of the
priority rules fires. Alerts have urgency levels:
- CRITICAL : immediate action recommended (stop-loss breach, halt, ST)
- HIGH     : strong sell signal (broken trend + volume divergence)
- MEDIUM   : warning (RSI extreme, news shock)

Each held position is checked against:
1. Stop-loss line (default -8% from cost)
2. Trailing high drawdown (-15% from since-buy peak)
3. Trend break (close < MA20 & volume up)
4. RSI extreme reversal (>78 with bearish day)
5. Negative news with high relevance + urgency
6. Take-profit threshold (+25% gain → suggest reduce)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from apps.api.app.db.repositories import (
    NewsRepository,
    PortfolioRepository,
    TradeFillRepository,
)
from apps.api.app.services.market_service import MarketService
from libs.features.technical import build_technical_features

log = logging.getLogger("quant.monitor")


@dataclass
class SellAlert:
    symbol: str
    name: str
    urgency: str           # CRITICAL | HIGH | MEDIUM
    rule: str              # stop_loss | trailing_drawdown | trend_break | rsi_reversal | bad_news | take_profit
    message: str
    last_price: float
    avg_cost: float
    pct_pnl: float
    quantity: int
    available_quantity: int
    triggered_at: datetime
    details: dict = field(default_factory=dict)


@dataclass
class MonitorReport:
    generated_at: datetime
    positions_checked: int
    alerts: list[SellAlert]


# --- Tunable thresholds (could come from RiskRule table later) ---
STOP_LOSS_PCT = -0.08           # -8% from cost basis
TRAILING_DRAWDOWN_PCT = -0.15   # -15% from peak
TAKE_PROFIT_PCT = 0.25          # +25% from cost
TREND_BREAK_VOL_RATIO = 1.3     # break + 1.3× volume
RSI_BEARISH_THRESHOLD = 78
NEWS_LOOKBACK_HOURS = 24
NEWS_NEGATIVE_THRESHOLD = -0.4
NEWS_RELEVANCE_THRESHOLD = 0.6


class PositionMonitor:
    def __init__(self, session: Session, market: Optional[MarketService] = None) -> None:
        self._db = session
        self._portfolio = PortfolioRepository(session)
        self._fills = TradeFillRepository(session)
        self._news = NewsRepository(session)
        self._market = market or MarketService()

    def run(self) -> MonitorReport:
        positions = self._portfolio.list_positions()
        alerts: list[SellAlert] = []
        for pos in positions:
            try:
                pos_alerts = self._check_position(pos)
                alerts.extend(pos_alerts)
            except Exception as exc:  # noqa: BLE001
                log.warning("monitor[%s] failed: %s", pos.symbol, exc, exc_info=True)
        return MonitorReport(
            generated_at=datetime.now(),
            positions_checked=len(positions),
            alerts=alerts,
        )

    # ------------------------------------------------------------------

    def _check_position(self, pos) -> list[SellAlert]:
        alerts: list[SellAlert] = []
        instrument = self._lookup_instrument(pos.symbol)
        if instrument is None:
            return alerts

        bars = self._market.get_bars(pos.symbol, freq="1d")
        if not bars:
            return alerts
        last = bars[-1]
        last_price = last.close
        pct_pnl = (last_price - pos.avg_cost) / pos.avg_cost if pos.avg_cost > 0 else 0.0

        ctx = {
            "symbol": pos.symbol,
            "name": instrument.name,
            "last_price": last_price,
            "avg_cost": pos.avg_cost,
            "pct_pnl": pct_pnl,
            "quantity": pos.quantity,
            "available_quantity": pos.available_quantity,
        }

        # --- Rule 1: Stop loss ---
        if pct_pnl <= STOP_LOSS_PCT:
            alerts.append(self._make_alert(
                ctx, urgency="CRITICAL", rule="stop_loss",
                message=f"已跌 {pct_pnl*100:.1f}%，触发 {STOP_LOSS_PCT*100:.0f}% 止损线，建议立即卖出",
                details={"threshold": STOP_LOSS_PCT, "pct_pnl": pct_pnl},
            ))

        # --- Rule 2: Trailing drawdown from since-entry peak ---
        peak = self._peak_since_entry(pos.symbol, pos.avg_cost, bars)
        if peak > 0 and last_price > 0:
            dd = (last_price - peak) / peak
            if dd <= TRAILING_DRAWDOWN_PCT:
                alerts.append(self._make_alert(
                    ctx, urgency="HIGH", rule="trailing_drawdown",
                    message=f"自买入后高点回撤 {dd*100:.1f}%（峰值 ¥{peak:.2f} → 现价 ¥{last_price:.2f}），存在趋势反转风险",
                    details={"peak": peak, "drawdown": dd},
                ))

        # --- Rule 3: Trend break (close < MA20 with volume confirmation) ---
        closes = [b.close for b in bars]
        volumes = [b.volume for b in bars]
        if len(closes) >= 21:
            ma20 = sum(closes[-20:]) / 20
            prev_ma20 = sum(closes[-21:-1]) / 20
            broke = closes[-2] >= prev_ma20 and closes[-1] < ma20
            if broke and len(volumes) >= 25:
                vol_ratio = volumes[-1] / (sum(volumes[-25:-1]) / 24 + 1e-9)
                if vol_ratio >= TREND_BREAK_VOL_RATIO:
                    alerts.append(self._make_alert(
                        ctx, urgency="HIGH", rule="trend_break",
                        message=f"破位 MA20 + 放量 {vol_ratio:.1f}× → 短线趋势走弱",
                        details={"ma20": ma20, "vol_ratio": vol_ratio},
                    ))

        # --- Rule 4: RSI bearish reversal ---
        bar_tuples = [(b.trade_date, b.close, b.volume, b.turnover_rate) for b in bars]
        features = build_technical_features(pos.symbol, bar_tuples)
        if features and features.rsi_14d is not None:
            rsi = features.rsi_14d
            today_red = last.close < last.open
            if rsi >= RSI_BEARISH_THRESHOLD and today_red:
                alerts.append(self._make_alert(
                    ctx, urgency="MEDIUM", rule="rsi_reversal",
                    message=f"RSI {rsi:.0f}（超买）+ 当日收阴，存在回调风险",
                    details={"rsi": rsi},
                ))

        # --- Rule 5: Negative news ---
        try:
            cutoff = datetime.now() - timedelta(hours=NEWS_LOOKBACK_HOURS)
            events = self._news.list_events_for_symbol(pos.symbol, limit=20)
            recent_neg = [
                e for e in events
                if e.created_at >= cutoff
                and e.sentiment_score <= NEWS_NEGATIVE_THRESHOLD
                and e.relevance_score >= NEWS_RELEVANCE_THRESHOLD
            ]
            if recent_neg:
                worst = min(recent_neg, key=lambda e: e.sentiment_score)
                alerts.append(self._make_alert(
                    ctx, urgency="HIGH", rule="bad_news",
                    message=f"近 {NEWS_LOOKBACK_HOURS}h 出现负面事件：{worst.summary[:60]}",
                    details={
                        "sentiment_score": worst.sentiment_score,
                        "event_type": worst.event_type,
                    },
                ))
        except Exception as exc:  # noqa: BLE001
            log.debug("news lookup failed for %s: %s", pos.symbol, exc)

        # --- Rule 6: Take profit ---
        if pct_pnl >= TAKE_PROFIT_PCT:
            alerts.append(self._make_alert(
                ctx, urgency="MEDIUM", rule="take_profit",
                message=f"已盈利 {pct_pnl*100:.1f}%，达 {TAKE_PROFIT_PCT*100:.0f}% 止盈线，建议减仓锁定利润",
                details={"threshold": TAKE_PROFIT_PCT, "pct_pnl": pct_pnl},
            ))

        return alerts

    # ------------------------------------------------------------------

    def _make_alert(self, ctx: dict, urgency: str, rule: str, message: str, details: dict) -> SellAlert:
        return SellAlert(
            symbol=ctx["symbol"],
            name=ctx["name"],
            urgency=urgency,
            rule=rule,
            message=message,
            last_price=round(ctx["last_price"], 2),
            avg_cost=round(ctx["avg_cost"], 2),
            pct_pnl=round(ctx["pct_pnl"], 4),
            quantity=ctx["quantity"],
            available_quantity=ctx["available_quantity"],
            triggered_at=datetime.now(),
            details=details,
        )

    def _peak_since_entry(self, symbol: str, avg_cost: float, bars) -> float:
        """Approximate peak price observed since the position was opened.

        Without dated cost-basis history, use the first bar where close >=
        avg_cost as a rough entry proxy; if none found, use full bar range.
        """
        entry_idx = 0
        for i, b in enumerate(bars):
            if b.close >= avg_cost:
                entry_idx = i
                break
        if entry_idx >= len(bars):
            return 0.0
        return max(b.high for b in bars[entry_idx:])

    def _lookup_instrument(self, symbol: str):
        instruments = self._market.list_instruments()
        return next((i for i in instruments if i.symbol == symbol), None)
