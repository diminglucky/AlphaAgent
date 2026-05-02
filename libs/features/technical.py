"""Technical indicators and features."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class TechnicalFeatures:
    """Technical features for a symbol."""
    symbol: str
    as_of_date: date
    
    # Price features
    close: float
    returns_1d: float
    returns_5d: float
    returns_20d: float
    
    # Volatility features
    volatility_20d: float
    
    # Volume features
    volume: int
    volume_ratio_5d: float  # Current volume / 5-day average
    turnover_rate: float
    
    # Momentum features
    rsi_14d: Optional[float] = None
    # MACD triple: DIF (fast-slow EMA diff), DEA (signal), histogram
    macd_dif: Optional[float] = None
    macd_dea: Optional[float] = None
    macd_hist: Optional[float] = None

    # Trend features
    ma_5d: Optional[float] = None
    ma_20d: Optional[float] = None
    ma_60d: Optional[float] = None

    # Bollinger Bands (20-day, 2σ)
    bb_upper: Optional[float] = None
    bb_lower: Optional[float] = None
    bb_pct_b: Optional[float] = None  # where price sits within the band (0-1)

    # KDJ stochastic (requires OHLCV; None when only close prices are available)
    kdj_k: Optional[float] = None
    kdj_d: Optional[float] = None
    kdj_j: Optional[float] = None


def calculate_returns(prices: list[float], period: int) -> Optional[float]:
    """Calculate returns over a period."""
    if len(prices) < period + 1:
        return None
    
    current = prices[-1]
    past = prices[-(period + 1)]
    
    if past == 0:
        return None
    
    return (current - past) / past


def calculate_volatility(returns: list[float], period: int) -> Optional[float]:
    """Calculate volatility (standard deviation of returns)."""
    if len(returns) < period:
        return None
    
    recent_returns = returns[-period:]
    mean_return = sum(recent_returns) / len(recent_returns)
    variance = sum((r - mean_return) ** 2 for r in recent_returns) / len(recent_returns)
    
    return variance ** 0.5


def calculate_moving_average(prices: list[float], period: int) -> Optional[float]:
    """Calculate simple moving average."""
    if len(prices) < period:
        return None
    
    recent_prices = prices[-period:]
    return sum(recent_prices) / len(recent_prices)


def calculate_ema(prices: list[float], period: int) -> list[float]:
    """Exponential Moving Average; returns a list of the same length as *prices*."""
    if not prices:
        return []
    k = 2.0 / (period + 1)
    emas = [prices[0]]
    for price in prices[1:]:
        emas.append(price * k + emas[-1] * (1.0 - k))
    return emas


def calculate_macd(
    prices: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Optional[tuple[float, float, float]]:
    """Standard MACD.  Returns (DIF, DEA, histogram) or None if data too short.

    - DIF  = EMA(fast) - EMA(slow)   (MACD line)
    - DEA  = EMA(DIF, signal)         (signal line)
    - hist = DIF - DEA                (MACD bar)
    """
    if len(prices) < slow:
        return None
    ema_fast = calculate_ema(prices, fast)
    ema_slow = calculate_ema(prices, slow)
    dif_series = [f - s for f, s in zip(ema_fast, ema_slow)]
    dea_series = calculate_ema(dif_series, signal)
    dif = dif_series[-1]
    dea = dea_series[-1]
    return (dif, dea, dif - dea)


def calculate_bollinger_bands(
    prices: list[float],
    period: int = 20,
    num_std: float = 2.0,
) -> Optional[tuple[float, float, float, float]]:
    """Bollinger Bands.  Returns (upper, middle, lower, %B) or None.

    %B = (close - lower) / (upper - lower); >1 = above band, <0 = below band.
    """
    if len(prices) < period:
        return None
    recent = prices[-period:]
    middle = sum(recent) / period
    variance = sum((p - middle) ** 2 for p in recent) / period
    std = variance ** 0.5
    upper = middle + num_std * std
    lower = middle - num_std * std
    current = prices[-1]
    pct_b = (current - lower) / (upper - lower) if upper != lower else 0.5
    return (upper, middle, lower, pct_b)


def calculate_kdj(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 9,
    k_smooth: int = 3,
    d_smooth: int = 3,
) -> Optional[tuple[float, float, float]]:
    """KDJ stochastic oscillator (Chinese-market convention).

    Returns ``(K, D, J)`` or ``None`` if data is too short.

    - RSV  = (Close - LowestLow_n) / (HighestHigh_n - LowestLow_n) * 100
    - K_t  = (k_smooth - 1)/k_smooth * K_{t-1} + 1/k_smooth * RSV_t   (seed=50)
    - D_t  = (d_smooth - 1)/d_smooth * D_{t-1} + 1/d_smooth * K_t     (seed=50)
    - J    = 3K - 2D

    Interpretation:
      - K & D > 80: overbought
      - K & D < 20: oversold
      - K crosses above D (golden cross): bullish; below (death cross): bearish
    """
    n = len(closes)
    if n < period or n != len(highs) or n != len(lows):
        return None

    # Seed K and D at 50 (Chinese-market convention)
    k_prev = 50.0
    d_prev = 50.0
    k = d = 50.0

    for i in range(period - 1, n):
        window_high = max(highs[i - period + 1 : i + 1])
        window_low = min(lows[i - period + 1 : i + 1])
        denom = window_high - window_low
        if denom <= 0:
            rsv = 50.0  # flat window: neutral
        else:
            rsv = (closes[i] - window_low) / denom * 100.0
        k = ((k_smooth - 1) / k_smooth) * k_prev + (1.0 / k_smooth) * rsv
        d = ((d_smooth - 1) / d_smooth) * d_prev + (1.0 / d_smooth) * k
        k_prev, d_prev = k, d

    j = 3.0 * k - 2.0 * d
    return (k, d, j)


def calculate_rsi(prices: list[float], period: int = 14) -> Optional[float]:
    """Calculate Relative Strength Index."""
    if len(prices) < period + 1:
        return None
    
    gains = []
    losses = []
    
    for i in range(1, len(prices)):
        change = prices[i] - prices[i - 1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
    
    if len(gains) < period:
        return None
    
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi


def build_technical_features(
    symbol: str,
    bars: list[tuple[date, float, int, float]],  # (date, close, volume, turnover_rate)
    *,
    highs: Optional[list[float]] = None,
    lows: Optional[list[float]] = None,
) -> Optional[TechnicalFeatures]:
    """Build technical features from bar data.

    Parameters
    ----------
    symbol:
        Stock ticker, e.g. ``"600519.SH"``.
    bars:
        Sequence of ``(date, close, volume, turnover_rate)`` tuples, oldest first.
    highs:
        Optional list of daily high prices (same length as *bars*).  Required for
        KDJ; ignored otherwise.
    lows:
        Optional list of daily low prices (same length as *bars*).  Required for KDJ.
    """
    if not bars:
        return None

    as_of_date, current_close, current_volume, current_turnover = bars[-1]
    
    prices = [bar[1] for bar in bars]
    volumes = [bar[2] for bar in bars]
    
    # Calculate returns
    returns_1d = calculate_returns(prices, 1) or 0.0
    returns_5d = calculate_returns(prices, 5) or 0.0
    returns_20d = calculate_returns(prices, 20) or 0.0
    
    # Calculate daily returns for volatility
    daily_returns = []
    for i in range(1, len(prices)):
        if prices[i - 1] != 0:
            daily_returns.append((prices[i] - prices[i - 1]) / prices[i - 1])
    
    volatility_20d = calculate_volatility(daily_returns, 20) or 0.0
    
    # Calculate volume ratio
    volume_ratio_5d = 1.0
    if len(volumes) >= 6:
        avg_volume_5d = sum(volumes[-6:-1]) / 5
        if avg_volume_5d > 0:
            volume_ratio_5d = current_volume / avg_volume_5d
    
    # Calculate indicators
    rsi_14d = calculate_rsi(prices, 14)
    ma_5d = calculate_moving_average(prices, 5)
    ma_20d = calculate_moving_average(prices, 20)
    ma_60d = calculate_moving_average(prices, 60)

    # MACD (requires ≥ 26 bars)
    macd_dif = macd_dea = macd_hist = None
    macd_result = calculate_macd(prices)
    if macd_result is not None:
        macd_dif, macd_dea, macd_hist = macd_result

    # Bollinger Bands (requires ≥ 20 bars)
    bb_upper = bb_lower = bb_pct_b = None
    bb_result = calculate_bollinger_bands(prices, period=20)
    if bb_result is not None:
        bb_upper, _bb_mid, bb_lower, bb_pct_b = bb_result

    # KDJ (requires OHLCV with highs and lows)
    kdj_k = kdj_d = kdj_j = None
    if highs is not None and lows is not None and len(highs) == len(bars):
        kdj_result = calculate_kdj(highs, lows, prices)
        if kdj_result is not None:
            kdj_k, kdj_d, kdj_j = kdj_result

    return TechnicalFeatures(
        symbol=symbol,
        as_of_date=as_of_date,
        close=current_close,
        returns_1d=returns_1d,
        returns_5d=returns_5d,
        returns_20d=returns_20d,
        volatility_20d=volatility_20d,
        volume=current_volume,
        volume_ratio_5d=volume_ratio_5d,
        turnover_rate=current_turnover,
        rsi_14d=rsi_14d,
        macd_dif=macd_dif,
        macd_dea=macd_dea,
        macd_hist=macd_hist,
        ma_5d=ma_5d,
        ma_20d=ma_20d,
        ma_60d=ma_60d,
        bb_upper=bb_upper,
        bb_lower=bb_lower,
        bb_pct_b=bb_pct_b,
        kdj_k=kdj_k,
        kdj_d=kdj_d,
        kdj_j=kdj_j,
    )
