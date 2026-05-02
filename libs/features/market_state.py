"""Market-state detection: bull / bear / sideways and sector-rotation signals.

Heuristics are based on:
  - Index price relative to moving averages (trend direction)
  - Short-term momentum vs volatility (trend strength)
  - Breadth: fraction of universe above their MA20 (market internals)

All computations use only close-price series so they work without external
data sources in unit tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from libs.features.technical import (
    calculate_bollinger_bands,
    calculate_ema,
    calculate_macd,
    calculate_moving_average,
    calculate_volatility,
)


class MarketRegime(str, Enum):
    BULL = "BULL"        # Sustained uptrend, low fear
    BEAR = "BEAR"        # Sustained downtrend, high fear
    SIDEWAYS = "SIDEWAYS"  # Choppy, no clear directional conviction
    RECOVERY = "RECOVERY"  # Bouncing from bear lows, breadth improving
    DISTRIBUTION = "DISTRIBUTION"  # Late-stage bull, breadth deteriorating


@dataclass(frozen=True)
class MarketState:
    """Snapshot of the market regime on a given close date."""

    regime: MarketRegime
    trend_score: float       # [-1, 1]: -1 = strongest bear, +1 = strongest bull
    volatility_level: str    # "LOW" | "NORMAL" | "HIGH" | "EXTREME"
    breadth_pct: Optional[float]  # fraction of universe above MA20, or None
    macd_positive: Optional[bool]  # index DIF > DEA
    bb_position: Optional[float]   # %B of index close; >1 = above upper band
    description: str


def classify_volatility(volatility_20d: Optional[float]) -> str:
    """Bucket daily volatility into qualitative levels."""
    if volatility_20d is None:
        return "NORMAL"
    if volatility_20d < 0.008:
        return "LOW"
    if volatility_20d < 0.018:
        return "NORMAL"
    if volatility_20d < 0.030:
        return "HIGH"
    return "EXTREME"


def detect_market_state(
    index_prices: list[float],
    universe_ma20_above_fraction: Optional[float] = None,
) -> MarketState:
    """Detect the current market regime from index close prices.

    Parameters
    ----------
    index_prices:
        Daily close prices for a broad index (e.g. CSI 300).  At least 20
        prices are required for a meaningful reading; fewer will produce a
        SIDEWAYS result with a warning.
    universe_ma20_above_fraction:
        Optional market-breadth measure: fraction of stocks in the universe
        that are trading above their own 20-day MA.  Pass ``None`` if
        unavailable.
    """
    if len(index_prices) < 5:
        return MarketState(
            regime=MarketRegime.SIDEWAYS,
            trend_score=0.0,
            volatility_level="NORMAL",
            breadth_pct=universe_ma20_above_fraction,
            macd_positive=None,
            bb_position=None,
            description="Insufficient data (<5 bars) to determine regime.",
        )

    prices = index_prices
    score = 0.0

    # --- Trend: MAs ---
    ma5 = calculate_moving_average(prices, 5)
    ma20 = calculate_moving_average(prices, 20)
    ma60 = calculate_moving_average(prices, 60)
    close = prices[-1]

    if ma5 is not None and ma5 != 0:
        if close > ma5:
            score += 0.2
        elif close < ma5:
            score -= 0.2
    if ma20 is not None and ma20 != 0:
        if close > ma20:
            score += 0.3
        elif close < ma20:
            score -= 0.3
    if ma60 is not None and ma60 != 0:
        if close > ma60:
            score += 0.2
        elif close < ma60:
            score -= 0.2
    # MA alignment bonus
    if ma5 is not None and ma20 is not None and ma60 is not None:
        if ma5 > ma20 > ma60:
            score += 0.2
        elif ma5 < ma20 < ma60:
            score -= 0.2

    # --- Momentum: MACD ---
    macd_positive: Optional[bool] = None
    macd_result = calculate_macd(prices)
    if macd_result is not None:
        dif, dea, hist = macd_result
        if abs(dif - dea) < 1e-10:  # flat / perfectly neutral — no MACD signal
            macd_positive = None
        else:
            macd_positive = dif > dea
            score += 0.15 if macd_positive else -0.15

    # --- Bollinger Bands position ---
    bb_position: Optional[float] = None
    bb_result = calculate_bollinger_bands(prices, period=20)
    if bb_result is not None:
        _upper, _mid, _lower, bb_position = bb_result
        if bb_position > 1.0:   # above upper band
            score -= 0.1        # overextended
        elif bb_position < 0.0:  # below lower band
            score += 0.1        # oversold bounce potential

    # --- Volatility ---
    daily_returns = [
        (prices[i] - prices[i - 1]) / prices[i - 1]
        for i in range(1, len(prices))
        if prices[i - 1] != 0
    ]
    vol_20d = calculate_volatility(daily_returns, 20)
    vol_level = classify_volatility(vol_20d)

    # --- Breadth ---
    breadth_score = 0.0
    if universe_ma20_above_fraction is not None:
        if universe_ma20_above_fraction > 0.65:
            breadth_score = 0.15
        elif universe_ma20_above_fraction < 0.35:
            breadth_score = -0.15
        score += breadth_score

    score = max(-1.0, min(1.0, score))

    # --- Classify regime ---
    if score >= 0.4:
        regime = MarketRegime.BULL
        desc = "Broad uptrend: price above key MAs, positive MACD, strong breadth."
    elif score >= 0.15:
        if universe_ma20_above_fraction is not None and universe_ma20_above_fraction < 0.50:
            regime = MarketRegime.DISTRIBUTION
            desc = "Late-stage rally: price elevated but breadth deteriorating."
        else:
            regime = MarketRegime.RECOVERY
            desc = "Recovery phase: trend improving but not yet confirmed bull."
    elif score <= -0.4:
        regime = MarketRegime.BEAR
        desc = "Broad downtrend: price below MAs, negative MACD, weak breadth."
    elif score <= -0.15:
        if universe_ma20_above_fraction is not None and universe_ma20_above_fraction > 0.50:
            regime = MarketRegime.RECOVERY
            desc = "Potential recovery: price weak but breadth holding."
        else:
            regime = MarketRegime.BEAR
            desc = "Developing downtrend: trend weakening, caution advised."
    else:
        regime = MarketRegime.SIDEWAYS
        desc = "No clear directional conviction; wait for breakout or breakdown."

    if vol_level in ("HIGH", "EXTREME"):
        desc += f"  [Volatility: {vol_level} — size positions accordingly]"

    return MarketState(
        regime=regime,
        trend_score=round(score, 4),
        volatility_level=vol_level,
        breadth_pct=universe_ma20_above_fraction,
        macd_positive=macd_positive,
        bb_position=round(bb_position, 4) if bb_position is not None else None,
        description=desc,
    )
