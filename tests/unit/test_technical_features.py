"""Tests for technical features calculation."""

from datetime import date

import pytest

from libs.features.technical import (
    build_technical_features,
    calculate_bollinger_bands,
    calculate_ema,
    calculate_kdj,
    calculate_macd,
    calculate_moving_average,
    calculate_returns,
    calculate_rsi,
    calculate_volatility,
)


def test_calculate_kdj_uptrend_overbought():
    """In a strong uptrend, K and D should drift toward overbought (>80)."""
    n = 30
    closes = [float(100 + i) for i in range(n)]
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    result = calculate_kdj(highs, lows, closes)
    assert result is not None
    k, d, j = result
    assert k > 80
    assert d > 70
    # J = 3K - 2D may exceed 100 in strong uptrends (expected behaviour)


def test_calculate_kdj_downtrend_oversold():
    """In a strong downtrend, K and D should drift toward oversold (<20).""" 
    n = 30
    closes = [float(130 - i) for i in range(n)]
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    result = calculate_kdj(highs, lows, closes)
    assert result is not None
    k, d, _j = result
    assert k < 20
    assert d < 30


def test_calculate_kdj_insufficient_data():
    """Returns None when fewer bars than period."""
    closes = [100.0, 101.0, 102.0]
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    assert calculate_kdj(highs, lows, closes, period=9) is None


def test_calculate_kdj_length_mismatch():
    """Returns None when arrays differ in length."""
    closes = [100.0] * 10
    highs = [101.0] * 9
    lows = [99.0] * 10
    assert calculate_kdj(highs, lows, closes) is None


def test_calculate_kdj_flat_market_neutral():
    """Flat market: RSV=50 → K, D converge to 50, J = 50.""" 
    closes = [100.0] * 30
    highs = [100.0] * 30
    lows = [100.0] * 30
    result = calculate_kdj(highs, lows, closes)
    assert result is not None
    k, d, j = result
    assert abs(k - 50.0) < 1e-6
    assert abs(d - 50.0) < 1e-6
    assert abs(j - 50.0) < 1e-6


def test_build_technical_features_with_kdj():
    """When highs and lows are supplied, KDJ fields should be populated."""
    from datetime import date as _date
    n = 30
    closes = [float(100 + i) for i in range(n)]
    highs = [c + 1.0 for c in closes]
    lows = [c - 1.0 for c in closes]
    bars = [(_date(2024, 1, i + 1), closes[i], 1000, 0.5) for i in range(n)]
    features = build_technical_features("600519.SH", bars, highs=highs, lows=lows)
    assert features is not None
    assert features.kdj_k is not None
    assert features.kdj_d is not None
    assert features.kdj_j is not None
    assert features.kdj_k > 80  # uptrend → overbought


def test_build_technical_features_without_kdj():
    """Without highs/lows, KDJ fields remain None."""
    from datetime import date as _date
    n = 30
    closes = [float(100 + i) for i in range(n)]
    bars = [(_date(2024, 1, i + 1), closes[i], 1000, 0.5) for i in range(n)]
    features = build_technical_features("600519.SH", bars)
    assert features is not None
    assert features.kdj_k is None
    assert features.kdj_d is None
    assert features.kdj_j is None


def test_build_technical_features_kdj_length_mismatch_skipped():
    """Mismatched highs length → KDJ skipped gracefully (no error)."""
    from datetime import date as _date
    n = 30
    closes = [float(100 + i) for i in range(n)]
    bars = [(_date(2024, 1, i + 1), closes[i], 1000, 0.5) for i in range(n)]
    highs = [c + 1 for c in closes[:20]]   # wrong length
    lows = [c - 1 for c in closes[:20]]
    features = build_technical_features("600519.SH", bars, highs=highs, lows=lows)
    assert features is not None
    assert features.kdj_k is None   # silently skipped


def test_calculate_returns():
    """Test returns calculation."""
    prices = [100.0, 102.0, 105.0, 103.0, 108.0]
    
    # 1-day return
    returns_1d = calculate_returns(prices, 1)
    assert returns_1d is not None
    assert abs(returns_1d - 0.0485) < 0.001  # (108-103)/103 ≈ 4.85%
    
    # 3-day return
    returns_3d = calculate_returns(prices, 3)
    assert returns_3d is not None
    assert abs(returns_3d - 0.0588) < 0.001  # (108-102)/102 ≈ 5.88%


def test_calculate_returns_insufficient_data():
    """Test returns calculation with insufficient data."""
    prices = [100.0, 102.0]
    
    returns_5d = calculate_returns(prices, 5)
    assert returns_5d is None


def test_calculate_moving_average():
    """Test moving average calculation."""
    prices = [100.0, 102.0, 105.0, 103.0, 108.0, 110.0]
    
    ma_3 = calculate_moving_average(prices, 3)
    assert ma_3 is not None
    assert abs(ma_3 - 107.0) < 0.1  # (103+108+110)/3 ≈ 107
    
    ma_5 = calculate_moving_average(prices, 5)
    assert ma_5 is not None
    assert abs(ma_5 - 105.6) < 0.1  # (102+105+103+108+110)/5 ≈ 105.6


def test_calculate_rsi():
    """Test RSI calculation."""
    # Uptrend prices
    prices_up = [100.0, 102.0, 105.0, 107.0, 110.0, 112.0, 115.0, 118.0, 
                 120.0, 122.0, 125.0, 127.0, 130.0, 132.0, 135.0]
    
    rsi = calculate_rsi(prices_up, 14)
    assert rsi is not None
    assert rsi > 50  # Uptrend should have RSI > 50
    
    # Downtrend prices
    prices_down = [135.0, 132.0, 130.0, 127.0, 125.0, 122.0, 120.0, 118.0,
                   115.0, 112.0, 110.0, 107.0, 105.0, 102.0, 100.0]
    
    rsi = calculate_rsi(prices_down, 14)
    assert rsi is not None
    assert rsi < 50  # Downtrend should have RSI < 50


def test_calculate_volatility():
    """Test volatility calculation."""
    # Low volatility returns
    returns_low = [0.01, 0.01, 0.01, 0.01, 0.01] * 4
    vol_low = calculate_volatility(returns_low, 20)
    assert vol_low is not None
    assert vol_low < 0.01
    
    # High volatility returns
    returns_high = [0.05, -0.04, 0.06, -0.05, 0.04] * 4
    vol_high = calculate_volatility(returns_high, 20)
    assert vol_high is not None
    assert vol_high > vol_low


def test_build_technical_features():
    """Test building complete technical features."""
    bars = [
        (date(2026, 4, 1), 100.0, 10000, 1.0),
        (date(2026, 4, 2), 102.0, 12000, 1.2),
        (date(2026, 4, 3), 105.0, 15000, 1.5),
        (date(2026, 4, 4), 103.0, 11000, 1.1),
        (date(2026, 4, 5), 108.0, 18000, 1.8),
        (date(2026, 4, 8), 110.0, 16000, 1.6),
        (date(2026, 4, 9), 112.0, 14000, 1.4),
        (date(2026, 4, 10), 115.0, 20000, 2.0),
    ]
    
    features = build_technical_features("600519.SH", bars)
    
    assert features is not None
    assert features.symbol == "600519.SH"
    assert features.as_of_date == date(2026, 4, 10)
    assert features.close == 115.0
    assert features.volume == 20000
    assert features.returns_1d > 0  # Price increased
    assert features.ma_5d is not None
    assert features.ma_5d > 0


def test_build_technical_features_empty():
    """Test building features with empty data."""
    bars = []
    
    features = build_technical_features("600519.SH", bars)
    assert features is None


def test_calculate_ema_basic():
    """EMA series must be same length and react faster than SMA."""
    prices = [100.0, 102.0, 101.0, 103.0, 105.0]
    emas = calculate_ema(prices, 3)
    assert len(emas) == len(prices)
    assert emas[0] == prices[0]
    # EMA should be between min and max of prices
    assert min(prices) <= emas[-1] <= max(prices)


def test_calculate_ema_empty():
    assert calculate_ema([], 5) == []


def test_calculate_macd_basic():
    """With an uptrending series long enough, DIF should be positive."""
    prices = [float(i) for i in range(80, 110)]  # 30 bars, strictly rising
    result = calculate_macd(prices)
    assert result is not None
    dif, dea, hist = result
    assert dif > 0   # EMA12 > EMA26 in uptrend
    assert isinstance(dea, float)
    assert abs(hist - (dif - dea)) < 1e-9


def test_calculate_macd_insufficient_data():
    """Returns None when fewer than 26 bars."""
    prices = [float(i) for i in range(20)]
    assert calculate_macd(prices) is None


def test_calculate_macd_downtrend_negative_dif():
    """In a downtrend, DIF should be negative."""
    prices = [float(i) for i in range(110, 80, -1)]  # 30 bars, strictly falling
    result = calculate_macd(prices)
    assert result is not None
    dif, _dea, _hist = result
    assert dif < 0


def test_calculate_bollinger_bands_basic():
    """BB middle should equal SMA20; upper > middle > lower."""
    prices = [100.0 + i * 0.5 for i in range(25)]
    result = calculate_bollinger_bands(prices)
    assert result is not None
    upper, middle, lower, pct_b = result
    assert upper > middle > lower
    # Middle should match SMA20 of last 20 bars
    sma20 = sum(prices[-20:]) / 20
    assert abs(middle - sma20) < 1e-9
    # pct_b should be between 0 and 1 for a flat trend
    assert 0.0 <= pct_b <= 1.5


def test_calculate_bollinger_bands_insufficient():
    """Returns None when fewer than 20 bars."""
    prices = [100.0 + i for i in range(10)]
    assert calculate_bollinger_bands(prices) is None


def test_calculate_bollinger_bands_flat_prices():
    """Flat prices produce zero-width bands; pct_b defaults to 0.5."""
    prices = [100.0] * 25
    result = calculate_bollinger_bands(prices)
    assert result is not None
    upper, middle, lower, pct_b = result
    assert upper == middle == lower == 100.0
    assert pct_b == 0.5


def test_build_technical_features_with_macd_and_bb():
    """With 30+ bars, MACD and BB fields should be populated."""
    bars = [
        (date(2026, 1, i + 1), 100.0 + i * 0.4, 10000 + i * 100, 1.0)
        for i in range(30)
    ]
    features = build_technical_features("000001.SZ", bars)
    assert features is not None
    assert features.macd_dif is not None
    assert features.macd_dea is not None
    assert features.macd_hist is not None
    assert features.bb_upper is not None
    assert features.bb_lower is not None
    assert features.bb_pct_b is not None
    assert features.bb_upper > features.bb_lower


def test_build_technical_features_short_no_macd_bb():
    """Fewer than 20 bars: MACD and BB fields remain None."""
    bars = [
        (date(2026, 4, 1 + i), 100.0 + i, 10000, 1.0)
        for i in range(10)
    ]
    features = build_technical_features("000001.SZ", bars)
    assert features is not None
    assert features.macd_dif is None
    assert features.bb_upper is None


def test_build_technical_features_minimal():
    """Test building features with minimal data."""
    bars = [
        (date(2026, 4, 25), 1720.0, 30000, 0.5),
    ]
    
    features = build_technical_features("600519.SH", bars)
    
    assert features is not None
    assert features.symbol == "600519.SH"
    assert features.close == 1720.0
    # With only 1 bar, most indicators will be None or 0
    assert features.returns_1d == 0.0
    assert features.ma_5d is None
