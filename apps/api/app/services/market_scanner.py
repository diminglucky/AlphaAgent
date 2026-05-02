"""Market Scanner — actively ranks the entire stock universe.

Output: Top-N BUY candidates + Top-N SELL warnings + held-position health.

Composite score per symbol:
    score = 0.35*momentum + 0.25*trend + 0.20*volume - 0.15*volatility - 0.05*overheat

- momentum  = pct returns over 5d / 10d / 20d (weighted)
- trend     = sign(close - MA20) * (close-MA20)/MA20
- volume    = volume_5d / volume_20d ratio (capped)
- volatility = std of daily returns (annualized)
- overheat  = max(0, RSI14 - 70) / 30   # penalize already over-extended
ST stocks and stocks with non-listed status are excluded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from apps.api.app.services.market_service import MarketService
from libs.features.technical import build_technical_features
from libs.quant_core.models import Instrument

log = logging.getLogger("quant.scanner")


@dataclass
class ScanCandidate:
    symbol: str
    name: str
    industry: str
    score: float
    momentum_5d: float
    momentum_20d: float
    trend: float
    volume_ratio: float
    volatility: float
    rsi_14: Optional[float]
    last_close: float
    pct_change_today: float
    reason: str
    risk_flags: list[str] = field(default_factory=list)
    is_st: bool = False


@dataclass
class ScanReport:
    generated_at: datetime
    universe_size: int
    successful: int
    errors: int
    top_buy: list[ScanCandidate]
    top_sell: list[ScanCandidate]
    all_ranked: list[ScanCandidate]


class MarketScanner:
    """Rank every instrument in the active universe by composite score."""

    def __init__(self, market: Optional[MarketService] = None) -> None:
        self._market = market or MarketService()

    def run(
        self,
        top_n: int = 10,
        max_symbols: int = 500,
        skip_st: bool = True,
    ) -> ScanReport:
        instruments = self._market.list_instruments()
        # In real-akshare mode this can be 5000+; cap to keep latency reasonable.
        if max_symbols and len(instruments) > max_symbols:
            instruments = instruments[:max_symbols]

        candidates: list[ScanCandidate] = []
        errors = 0
        for instr in instruments:
            if skip_st and instr.is_st:
                continue
            if instr.status not in ("listed", "active", "正常", "ACTIVE", "LISTED"):
                continue
            try:
                cand = self._score_one(instr)
                if cand is not None:
                    candidates.append(cand)
            except Exception as exc:  # noqa: BLE001
                errors += 1
                log.debug("scan[%s] failed: %s", instr.symbol, exc)

        candidates.sort(key=lambda c: c.score, reverse=True)
        return ScanReport(
            generated_at=datetime.now(),
            universe_size=len(instruments),
            successful=len(candidates),
            errors=errors,
            top_buy=candidates[:top_n],
            top_sell=list(reversed(candidates[-top_n:])) if len(candidates) >= top_n else [],
            all_ranked=candidates,
        )

    # ------------------------------------------------------------------

    def _score_one(self, instr: Instrument) -> Optional[ScanCandidate]:
        bars = self._market.get_bars(symbol=instr.symbol, freq="1d")
        if len(bars) < 5:
            return None

        bar_tuples = [(b.trade_date, b.close, b.volume, b.turnover_rate) for b in bars]
        features = build_technical_features(instr.symbol, bar_tuples)
        if features is None:
            return None

        closes = [b.close for b in bars]
        volumes = [b.volume for b in bars]
        last_close = closes[-1]

        # ---- Component scores ----
        # Momentum: weighted recent returns (clipped to ±0.5 each)
        def _ret(n: int) -> float:
            if len(closes) <= n or closes[-n - 1] <= 0:
                return 0.0
            return max(-0.5, min(0.5, (closes[-1] - closes[-n - 1]) / closes[-n - 1]))

        m5 = _ret(5)
        m10 = _ret(10)
        m20 = _ret(20)
        momentum = (m5 * 0.5 + m10 * 0.3 + m20 * 0.2)  # ∈ [-0.5, 0.5]

        # Trend: distance to MA20
        ma20 = sum(closes[-20:]) / min(20, len(closes))
        trend = (last_close - ma20) / ma20 if ma20 > 0 else 0.0
        trend = max(-0.3, min(0.3, trend))

        # Volume ratio (recent 5d / prior 20d)
        if len(volumes) >= 25:
            recent = sum(volumes[-5:]) / 5
            base = sum(volumes[-25:-5]) / 20
            vol_ratio = (recent / base) if base > 0 else 1.0
        else:
            vol_ratio = 1.0
        # Map to score: 1.0 → 0, 2.0 → +0.3, 0.5 → -0.15
        volume_score = max(-0.2, min(0.3, (vol_ratio - 1.0) * 0.3))

        volatility = features.volatility_20d or 0.02
        vol_penalty = max(0.0, volatility - 0.025) * 5  # >2.5% daily noise → penalty

        rsi = features.rsi_14d
        overheat = 0.0
        if rsi is not None and rsi > 70:
            overheat = (rsi - 70) / 30  # 70→0, 100→1

        score = (
            0.35 * momentum
            + 0.25 * trend
            + 0.20 * volume_score
            - 0.15 * vol_penalty
            - 0.05 * overheat
        )

        # Build human reason
        bits = []
        if m5 > 0.03:
            bits.append(f"5日 +{m5*100:.1f}%")
        elif m5 < -0.03:
            bits.append(f"5日 {m5*100:.1f}%")
        if trend > 0.02:
            bits.append(f"站上 MA20 {trend*100:.1f}%")
        elif trend < -0.02:
            bits.append(f"跌破 MA20 {trend*100:.1f}%")
        if vol_ratio > 1.5:
            bits.append(f"放量 {vol_ratio:.1f}×")
        elif vol_ratio < 0.7:
            bits.append(f"缩量 {vol_ratio:.1f}×")
        if rsi is not None:
            if rsi > 75:
                bits.append(f"RSI {rsi:.0f}（超买）")
            elif rsi < 25:
                bits.append(f"RSI {rsi:.0f}（超卖）")
        reason = " · ".join(bits) if bits else "盘面平稳"

        risk_flags: list[str] = []
        if volatility > 0.04:
            risk_flags.append("HIGH_VOLATILITY")
        if rsi is not None and rsi > 80:
            risk_flags.append("OVERBOUGHT")
        elif rsi is not None and rsi < 20:
            risk_flags.append("OVERSOLD")
        if instr.is_st:
            risk_flags.append("ST_STOCK")

        # Today pct change (using open vs close of last bar)
        today_pct = ((last_close - bars[-1].open) / bars[-1].open * 100) if bars[-1].open else 0.0

        return ScanCandidate(
            symbol=instr.symbol,
            name=instr.name,
            industry=instr.industry or "",
            score=round(score, 4),
            momentum_5d=round(m5, 4),
            momentum_20d=round(m20, 4),
            trend=round(trend, 4),
            volume_ratio=round(vol_ratio, 2),
            volatility=round(volatility, 4),
            rsi_14=round(rsi, 1) if rsi is not None else None,
            last_close=round(last_close, 2),
            pct_change_today=round(today_pct, 2),
            reason=reason,
            risk_flags=risk_flags,
            is_st=instr.is_st,
        )
