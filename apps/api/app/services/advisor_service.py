"""
Portfolio-aware Advisor service.

For each holding the user already owns: produce a SELL/HOLD recommendation
(taking into account cost basis, P&L and current technical/news/risk signals).

For each watchlist symbol that is NOT held: produce a BUY/PASS recommendation.

The output is a ranked list of actionable advice with reasons and urgency,
suitable for direct display on the Dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from apps.api.app.core.config import get_settings
from apps.api.app.services.analyze_service import AnalyzeService
from apps.api.app.services.portfolio_service import PortfolioService
from apps.api.app.services.watchlist_service import DEFAULT_SYMBOLS, WatchlistService
from libs.llm_analyst.decision import AnalysisReport
from libs.quant_core.enums import RecommendationAction


# Default watchlist used when no DB entries exist (kept for backwards compat).
DEFAULT_WATCHLIST: list[str] = list(DEFAULT_SYMBOLS)


@dataclass
class AdvisorItem:
    symbol: str
    action: str                 # BUY / SELL / HOLD / TAKE_PROFIT / STOP_LOSS / PASS
    priority: int               # 1 (most urgent) … 5
    reason: str                 # one-line headline
    detail: str                 # full multi-line explanation
    confidence: float
    held: bool                  # True if currently in portfolio
    current_pnl_ratio: Optional[float] = None
    risk_flags: list[str] = field(default_factory=list)
    components: dict = field(default_factory=dict)


@dataclass
class AdvisorReport:
    generated_at: datetime
    items: list[AdvisorItem]
    summary: dict


class AdvisorService:
    """Combine portfolio state and per-symbol AnalysisReport into actionable advice."""

    # Risk-management thresholds
    STOP_LOSS_RATIO = -0.08      # -8 %  → urgent stop-loss
    TAKE_PROFIT_RATIO = 0.20     # +20 % → consider taking profit
    HEAVY_LOSS_RATIO = -0.05     # -5 %  → loss warning

    def __init__(self, db: Session) -> None:
        self._db = db
        self._analyzer = AnalyzeService(db)
        self._portfolio = PortfolioService()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def build(self, watchlist: Optional[list[str]] = None) -> AdvisorReport:
        if not watchlist:
            account_id = get_settings().default_account_id
            watchlist = WatchlistService(self._db).list_symbols(account_id)
        positions = self._portfolio.get_positions()
        held_symbols = {p.symbol for p in positions}

        items: list[AdvisorItem] = []

        # 1) For each holding → analyze and decide SELL/HOLD/TAKE_PROFIT/STOP_LOSS
        for pos in positions:
            try:
                report = self._analyzer.analyze(
                    pos.symbol,
                    portfolio_context=self._position_context(pos),
                )
            except ValueError:
                continue
            items.append(self._holding_to_item(pos, report))

        # 2) For each watchlist symbol NOT held → analyze and decide BUY/PASS
        for sym in watchlist:
            if sym in held_symbols:
                continue
            try:
                report = self._analyzer.analyze(sym, portfolio_context="尚未持仓")
            except ValueError:
                continue
            items.append(self._watch_to_item(sym, report))

        # Sort by priority asc, then by confidence desc
        items.sort(key=lambda x: (x.priority, -x.confidence))

        # Summary
        summary = {
            "total": len(items),
            "buy": sum(1 for i in items if i.action == "BUY"),
            "sell": sum(1 for i in items if i.action in ("SELL", "STOP_LOSS")),
            "take_profit": sum(1 for i in items if i.action == "TAKE_PROFIT"),
            "hold": sum(1 for i in items if i.action == "HOLD"),
            "pass": sum(1 for i in items if i.action == "PASS"),
            "held_count": len(positions),
            "watchlist_count": len(watchlist),
        }

        return AdvisorReport(generated_at=datetime.now(), items=items, summary=summary)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _current_price(pos) -> float:
        if pos.quantity:
            return pos.market_value / pos.quantity
        return pos.avg_cost

    @classmethod
    def _pnl_ratio(cls, pos) -> float:
        if pos.avg_cost <= 0:
            return 0.0
        return (cls._current_price(pos) - pos.avg_cost) / pos.avg_cost

    def _position_context(self, pos) -> str:
        pnl_ratio = self._pnl_ratio(pos)
        return (
            f"已持仓 {pos.quantity} 股，成本 ¥{pos.avg_cost:.2f}，"
            f"现价 ¥{self._current_price(pos):.2f}，浮动盈亏 {pnl_ratio*100:+.2f}%"
        )

    def _holding_to_item(self, pos, report: AnalysisReport) -> AdvisorItem:
        """Apply position-aware overrides on top of the multi-agent action."""

        pnl_ratio = self._pnl_ratio(pos)
        cur_price = self._current_price(pos)

        # 1) Hard stop-loss override (highest priority)
        if pnl_ratio <= self.STOP_LOSS_RATIO:
            return AdvisorItem(
                symbol=pos.symbol,
                action="STOP_LOSS",
                priority=1,
                reason=f"⚠ 浮亏 {pnl_ratio*100:.2f}%，触发止损线（-8%），建议立即减仓",
                detail=(
                    f"持仓 {pos.quantity} 股 @ ¥{pos.avg_cost:.2f}，现价 ¥{cur_price:.2f}\n"
                    f"已触及止损阈值 {self.STOP_LOSS_RATIO*100:.0f}%。\n\n{report.reasoning}"
                ),
                confidence=max(report.confidence, 0.85),
                held=True,
                current_pnl_ratio=pnl_ratio,
                risk_flags=["STOP_LOSS"] + report.risk_flags,
                components=report.components,
            )

        # 2) Risk-officer veto on holdings → SELL
        if not report.approved or "ST_STOCK" in report.risk_flags:
            return AdvisorItem(
                symbol=pos.symbol,
                action="SELL",
                priority=1,
                reason=f"风控告警，建议卖出 — {report.summary}",
                detail=report.reasoning,
                confidence=report.confidence,
                held=True,
                current_pnl_ratio=pnl_ratio,
                risk_flags=report.risk_flags,
                components=report.components,
            )

        # 3) Take-profit when up sharply and signal turns neutral/bearish
        if pnl_ratio >= self.TAKE_PROFIT_RATIO and report.action != RecommendationAction.BUY:
            return AdvisorItem(
                symbol=pos.symbol,
                action="TAKE_PROFIT",
                priority=2,
                reason=f"✓ 浮盈 {pnl_ratio*100:.2f}%，技术面动能减弱，可考虑止盈",
                detail=(
                    f"持仓 {pos.quantity} 股 @ ¥{pos.avg_cost:.2f}，现价 ¥{cur_price:.2f}\n\n"
                    f"{report.reasoning}"
                ),
                confidence=report.confidence,
                held=True,
                current_pnl_ratio=pnl_ratio,
                risk_flags=report.risk_flags,
                components=report.components,
            )

        # 4) Multi-agent says SELL → SELL
        if report.action == RecommendationAction.SELL:
            return AdvisorItem(
                symbol=pos.symbol,
                action="SELL",
                priority=2,
                reason=f"多 Agent 综合看空，建议卖出（盈亏 {pnl_ratio*100:+.2f}%）",
                detail=report.reasoning,
                confidence=report.confidence,
                held=True,
                current_pnl_ratio=pnl_ratio,
                risk_flags=report.risk_flags,
                components=report.components,
            )

        # 5) Loss warning (still HOLD but flag it)
        if pnl_ratio <= self.HEAVY_LOSS_RATIO:
            return AdvisorItem(
                symbol=pos.symbol,
                action="HOLD",
                priority=3,
                reason=f"持有观察（浮亏 {pnl_ratio*100:.2f}%，需关注）",
                detail=report.reasoning,
                confidence=report.confidence,
                held=True,
                current_pnl_ratio=pnl_ratio,
                risk_flags=report.risk_flags + ["LOSS_WARNING"],
                components=report.components,
            )

        # 6) Default HOLD
        return AdvisorItem(
            symbol=pos.symbol,
            action="HOLD",
            priority=4,
            reason=f"继续持有（盈亏 {pnl_ratio*100:+.2f}%）",
            detail=report.reasoning,
            confidence=report.confidence,
            held=True,
            current_pnl_ratio=pnl_ratio,
            risk_flags=report.risk_flags,
            components=report.components,
        )

    def _watch_to_item(self, symbol: str, report: AnalysisReport) -> AdvisorItem:
        if not report.approved:
            return AdvisorItem(
                symbol=symbol,
                action="PASS",
                priority=5,
                reason="风控未通过，跳过",
                detail=report.reasoning,
                confidence=report.confidence,
                held=False,
                risk_flags=report.risk_flags,
                components=report.components,
            )

        if report.action == RecommendationAction.BUY:
            return AdvisorItem(
                symbol=symbol,
                action="BUY",
                priority=2,
                reason=report.summary,
                detail=report.reasoning,
                confidence=report.confidence,
                held=False,
                risk_flags=report.risk_flags,
                components=report.components,
            )

        return AdvisorItem(
            symbol=symbol,
            action="PASS",
            priority=5,
            reason=f"信号不足（{report.action.value}）",
            detail=report.reasoning,
            confidence=report.confidence,
            held=False,
            risk_flags=report.risk_flags,
            components=report.components,
        )
