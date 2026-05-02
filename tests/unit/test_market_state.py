"""Tests for market-state detection."""

import pytest

from libs.features.market_state import (
    MarketRegime,
    MarketState,
    classify_volatility,
    detect_market_state,
)


def _uptrend(n: int = 60, start: float = 3000.0, step: float = 10.0):
    return [start + i * step for i in range(n)]


def _downtrend(n: int = 60, start: float = 4500.0, step: float = -10.0):
    return [start + i * step for i in range(n)]


def _flat(n: int = 60, price: float = 3500.0):
    return [price] * n


def test_bull_regime_uptrend():
    state = detect_market_state(_uptrend(60), universe_ma20_above_fraction=0.75)
    assert state.regime == MarketRegime.BULL
    assert state.trend_score > 0


def test_bear_regime_downtrend():
    state = detect_market_state(_downtrend(60), universe_ma20_above_fraction=0.20)
    assert state.regime == MarketRegime.BEAR
    assert state.trend_score < 0


def test_sideways_flat():
    state = detect_market_state(_flat(60))
    # Flat prices = zero trend score, no MACD signal → SIDEWAYS
    assert state.regime == MarketRegime.SIDEWAYS
    assert state.trend_score == 0.0


def test_insufficient_data_sideways():
    state = detect_market_state([3000.0, 3010.0])
    assert state.regime == MarketRegime.SIDEWAYS


def test_macd_positive_in_uptrend():
    state = detect_market_state(_uptrend(60))
    assert state.macd_positive is True


def test_macd_negative_in_downtrend():
    state = detect_market_state(_downtrend(60))
    assert state.macd_positive is False


def test_bb_position_populated():
    state = detect_market_state(_uptrend(60))
    assert state.bb_position is not None


def test_classify_volatility():
    assert classify_volatility(0.005) == "LOW"
    assert classify_volatility(0.012) == "NORMAL"
    assert classify_volatility(0.022) == "HIGH"
    assert classify_volatility(0.040) == "EXTREME"
    assert classify_volatility(None) == "NORMAL"


def test_breadth_influences_regime():
    prices = _uptrend(30)
    high_breadth = detect_market_state(prices, universe_ma20_above_fraction=0.80)
    low_breadth = detect_market_state(prices, universe_ma20_above_fraction=0.20)
    assert high_breadth.trend_score >= low_breadth.trend_score


def test_distribution_regime():
    """Index at highs but weak breadth → score driven down → not full BULL."""
    # 40-bar rise followed by 20-bar flat top = distribution-like pattern.
    # Close equals MA20 on the flat portion → moderate trend score.
    rising = [3000.0 + i * 15.0 for i in range(40)]
    flat_top = [rising[-1]] * 20
    prices = rising + flat_top
    state = detect_market_state(prices, universe_ma20_above_fraction=0.38)
    # Poor breadth must reduce the score versus a full bull
    bull_state = detect_market_state(prices, universe_ma20_above_fraction=0.80)
    assert state.trend_score <= bull_state.trend_score
