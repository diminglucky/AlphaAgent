"""Tests for signal engine."""

from datetime import date

import pytest

from libs.features.technical import TechnicalFeatures
from libs.quant_core.enums import RecommendationAction
from libs.recommendations.signal_engine import SignalEngine


def test_signal_engine_initialization():
    """Test signal engine initializes correctly."""
    engine = SignalEngine()
    
    assert engine.momentum_weight > 0
    assert engine.trend_weight > 0
    assert engine.volume_weight > 0
    assert engine.volatility_weight > 0


def test_momentum_score_bullish():
    """Test momentum score calculation for bullish case."""
    engine = SignalEngine()
    
    features = TechnicalFeatures(
        symbol="600519.SH",
        as_of_date=date(2026, 4, 25),
        close=1720.0,
        returns_1d=0.03,  # 3% gain
        returns_5d=0.08,  # 8% gain
        returns_20d=0.15,
        volatility_20d=0.02,
        volume=30000,
        volume_ratio_5d=1.2,
        turnover_rate=0.5,
        rsi_14d=55.0,  # Neutral
    )
    
    score = engine.calculate_momentum_score(features)
    assert score > 0  # Should be bullish


def test_momentum_score_bearish():
    """Test momentum score calculation for bearish case."""
    engine = SignalEngine()
    
    features = TechnicalFeatures(
        symbol="600519.SH",
        as_of_date=date(2026, 4, 25),
        close=1720.0,
        returns_1d=-0.03,  # 3% loss
        returns_5d=-0.08,  # 8% loss
        returns_20d=-0.15,
        volatility_20d=0.02,
        volume=30000,
        volume_ratio_5d=1.2,
        turnover_rate=0.5,
        rsi_14d=75.0,  # Overbought
    )
    
    score = engine.calculate_momentum_score(features)
    assert score < 0  # Should be bearish


def test_trend_score_bullish():
    """Test trend score for bullish alignment."""
    engine = SignalEngine()
    
    features = TechnicalFeatures(
        symbol="600519.SH",
        as_of_date=date(2026, 4, 25),
        close=1720.0,
        returns_1d=0.01,
        returns_5d=0.03,
        returns_20d=0.10,
        volatility_20d=0.02,
        volume=30000,
        volume_ratio_5d=1.2,
        turnover_rate=0.5,
        ma_5d=1710.0,  # Price above MA5
        ma_20d=1680.0,  # MA5 > MA20
        ma_60d=1650.0,  # MA20 > MA60 (bullish alignment)
    )
    
    score = engine.calculate_trend_score(features)
    assert score > 0


def test_volume_score_with_surge():
    """Test volume score with volume surge."""
    engine = SignalEngine()
    
    features = TechnicalFeatures(
        symbol="600519.SH",
        as_of_date=date(2026, 4, 25),
        close=1720.0,
        returns_1d=0.02,  # Positive return
        returns_5d=0.05,
        returns_20d=0.10,
        volatility_20d=0.02,
        volume=50000,
        volume_ratio_5d=2.0,  # 100% above average (surge)
        turnover_rate=3.0,
    )
    
    score = engine.calculate_volume_score(features)
    assert score > 0  # Volume surge with positive returns is bullish


def test_generate_signal_bullish():
    """Test signal generation for bullish case."""
    engine = SignalEngine()
    
    features = TechnicalFeatures(
        symbol="600519.SH",
        as_of_date=date(2026, 4, 25),
        close=1720.0,
        returns_1d=0.025,
        returns_5d=0.06,
        returns_20d=0.12,
        volatility_20d=0.018,
        volume=35000,
        volume_ratio_5d=1.5,
        turnover_rate=2.5,
        rsi_14d=58.0,
        ma_5d=1710.0,
        ma_20d=1680.0,
        ma_60d=1650.0,
    )
    
    signal = engine.generate_signal(features)
    
    assert signal.symbol == "600519.SH"
    assert signal.raw_score > 0  # Bullish
    assert 0 <= signal.confidence <= 1.0
    assert "momentum" in signal.components
    assert "trend" in signal.components


def test_signal_to_action():
    """Test converting signal to action."""
    engine = SignalEngine()
    
    features = TechnicalFeatures(
        symbol="600519.SH",
        as_of_date=date(2026, 4, 25),
        close=1720.0,
        returns_1d=0.03,
        returns_5d=0.08,
        returns_20d=0.15,
        volatility_20d=0.02,
        volume=35000,
        volume_ratio_5d=1.5,
        turnover_rate=2.5,
        rsi_14d=55.0,
        ma_5d=1710.0,
        ma_20d=1680.0,
        ma_60d=1650.0,
    )
    
    signal = engine.generate_signal(features)
    action = engine.signal_to_action(signal)
    
    assert action in (RecommendationAction.BUY, RecommendationAction.HOLD, RecommendationAction.SELL)
    
    # Strong bullish signal should be BUY
    if signal.raw_score > 0.3:
        assert action == RecommendationAction.BUY


# ---------------------------------------------------------------------------
# KDJ scoring
# ---------------------------------------------------------------------------

def test_kdj_score_oversold():
    """K < 20 with K > D → strong bullish KDJ score."""
    engine = SignalEngine()
    features = TechnicalFeatures(
        symbol="000001.SZ",
        as_of_date=date(2026, 4, 25),
        close=10.0,
        returns_1d=0.0,
        returns_5d=0.0,
        returns_20d=0.0,
        volatility_20d=0.015,
        volume=10000,
        volume_ratio_5d=1.0,
        turnover_rate=1.0,
        kdj_k=15.0,   # oversold
        kdj_d=12.0,   # K > D → bullish crossover
        kdj_j=21.0,
    )
    score = engine.calculate_kdj_score(features)
    assert score > 0.4   # oversold + K>D → max bullish


def test_kdj_score_overbought():
    """K > 80 with K < D → strong bearish KDJ score."""
    engine = SignalEngine()
    features = TechnicalFeatures(
        symbol="000001.SZ",
        as_of_date=date(2026, 4, 25),
        close=10.0,
        returns_1d=0.0,
        returns_5d=0.0,
        returns_20d=0.0,
        volatility_20d=0.015,
        volume=10000,
        volume_ratio_5d=1.0,
        turnover_rate=1.0,
        kdj_k=85.0,   # overbought
        kdj_d=90.0,   # K < D → bearish crossover
        kdj_j=80.0,
    )
    score = engine.calculate_kdj_score(features)
    assert score < -0.4


def test_kdj_score_none_returns_zero():
    """KDJ unavailable (close-only bars) → score is exactly 0."""
    engine = SignalEngine()
    features = TechnicalFeatures(
        symbol="000001.SZ",
        as_of_date=date(2026, 4, 25),
        close=10.0,
        returns_1d=0.0,
        returns_5d=0.0,
        returns_20d=0.0,
        volatility_20d=0.015,
        volume=10000,
        volume_ratio_5d=1.0,
        turnover_rate=1.0,
        # kdj_k / d / j left as None (default)
    )
    assert engine.calculate_kdj_score(features) == 0.0


# ---------------------------------------------------------------------------
# Fundamental scoring
# ---------------------------------------------------------------------------

def _make_features(symbol: str = "TEST.SH") -> TechnicalFeatures:
    return TechnicalFeatures(
        symbol=symbol,
        as_of_date=date(2026, 4, 25),
        close=100.0,
        returns_1d=0.01,
        returns_5d=0.03,
        returns_20d=0.06,
        volatility_20d=0.015,
        volume=10000,
        volume_ratio_5d=1.0,
        turnover_rate=1.5,
    )


def test_fundamental_score_none_returns_zero():
    """No fundamentals → fundamental component is 0."""
    assert SignalEngine().calculate_fundamental_score(None) == 0.0


def test_fundamental_score_cheap_growing():
    """Low PE + high ROE + strong growth → positive fundamental score."""
    from datetime import date as _date
    from libs.features.fundamental import FundamentalFeatures
    fund = FundamentalFeatures(
        symbol="TEST.SH",
        as_of_date=_date(2026, 4, 25),
        pe_ttm=12.0,    # cheap
        pb=1.2,
        roe=0.25,       # high ROE
        revenue_yoy=0.35,   # strong growth
        profit_yoy=0.40,
    )
    score = SignalEngine().calculate_fundamental_score(fund)
    assert score > 0.2


def test_fundamental_score_expensive_shrinking():
    """High PE + negative ROE + declining revenue → negative score."""
    from datetime import date as _date
    from libs.features.fundamental import FundamentalFeatures
    fund = FundamentalFeatures(
        symbol="TEST.SH",
        as_of_date=_date(2026, 4, 25),
        pe_ttm=80.0,
        pb=12.0,
        roe=-0.05,
        revenue_yoy=-0.20,
        profit_yoy=-0.30,
    )
    score = SignalEngine().calculate_fundamental_score(fund)
    assert score < -0.1


# ---------------------------------------------------------------------------
# Market-regime adjustment
# ---------------------------------------------------------------------------

def test_regime_bull_raises_score():
    """BULL regime bias pushes the raw score up."""
    from libs.features.market_state import MarketRegime, MarketState
    features = _make_features()
    engine = SignalEngine()
    sig_no_regime = engine.generate_signal(features)
    bull_state = MarketState(
        regime=MarketRegime.BULL,
        trend_score=0.8,
        volatility_level="LOW",
        breadth_pct=0.7,
        macd_positive=True,
        bb_position=0.9,
        description="bull",
    )
    sig_bull = engine.generate_signal(features, market_state=bull_state)
    assert sig_bull.raw_score > sig_no_regime.raw_score
    assert "regime_bias" in sig_bull.components


def test_regime_bear_lowers_score():
    """BEAR regime bias pushes the raw score down."""
    from libs.features.market_state import MarketRegime, MarketState
    features = _make_features()
    engine = SignalEngine()
    sig_no_regime = engine.generate_signal(features)
    bear_state = MarketState(
        regime=MarketRegime.BEAR,
        trend_score=-0.8,
        volatility_level="HIGH",
        breadth_pct=0.2,
        macd_positive=False,
        bb_position=0.1,
        description="bear",
    )
    sig_bear = engine.generate_signal(features, market_state=bear_state)
    assert sig_bear.raw_score < sig_no_regime.raw_score
    assert sig_bear.components["regime_bias"] < 0


def test_bear_regime_lowers_confidence():
    """BEAR regime confidence factor < 1 → reduced confidence."""
    from libs.features.market_state import MarketRegime, MarketState
    features = _make_features()
    engine = SignalEngine()
    bear_state = MarketState(
        regime=MarketRegime.BEAR,
        trend_score=-0.8,
        volatility_level="HIGH",
        breadth_pct=0.2,
        macd_positive=False,
        bb_position=0.1,
        description="bear",
    )
    sig_no_regime = engine.generate_signal(features)
    sig_bear = engine.generate_signal(features, market_state=bear_state)
    assert sig_bear.confidence <= sig_no_regime.confidence


# ---------------------------------------------------------------------------
# Full multi-source fusion
# ---------------------------------------------------------------------------

def test_full_fusion_components_present():
    """Signal with all three sources includes all component keys."""
    from datetime import date as _date
    from libs.features.fundamental import FundamentalFeatures
    from libs.features.market_state import MarketRegime, MarketState
    features = _make_features()
    fund = FundamentalFeatures(
        symbol="TEST.SH",
        as_of_date=_date(2026, 4, 25),
        pe_ttm=18.0,
        roe=0.15,
        revenue_yoy=0.12,
    )
    state = MarketState(
        regime=MarketRegime.RECOVERY,
        trend_score=0.3,
        volatility_level="NORMAL",
        breadth_pct=0.55,
        macd_positive=True,
        bb_position=0.6,
        description="recovery",
    )
    sig = SignalEngine().generate_signal(features, fundamentals=fund, market_state=state)
    for key in ("momentum", "kdj", "trend", "volume", "volatility",
                "fundamental", "regime_bias"):
        assert key in sig.components, f"Missing component: {key}"
    assert -1.0 <= sig.raw_score <= 1.0
    assert 0.0 <= sig.confidence <= 1.0


def test_fundamentals_improve_bullish_signal():
    """Adding strong fundamentals to an already-bullish signal increases score."""
    from datetime import date as _date
    from libs.features.fundamental import FundamentalFeatures
    features = TechnicalFeatures(
        symbol="TEST.SH",
        as_of_date=_date(2026, 4, 25),
        close=100.0,
        returns_1d=0.025,
        returns_5d=0.06,
        returns_20d=0.12,
        volatility_20d=0.012,
        volume=20000,
        volume_ratio_5d=1.6,
        turnover_rate=2.0,
        rsi_14d=58.0,
        ma_5d=98.0,
        ma_20d=93.0,
        ma_60d=88.0,
    )
    engine = SignalEngine()
    sig_tech_only = engine.generate_signal(features)
    fund = FundamentalFeatures(
        symbol="TEST.SH",
        as_of_date=_date(2026, 4, 25),
        pe_ttm=10.0,
        pb=1.0,
        roe=0.28,
        revenue_yoy=0.35,
        profit_yoy=0.40,
    )
    sig_fused = engine.generate_signal(features, fundamentals=fund)
    assert sig_fused.raw_score > sig_tech_only.raw_score
    assert "fundamental" in sig_fused.components
