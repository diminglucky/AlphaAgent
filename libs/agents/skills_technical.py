"""Technical-analysis skills — 使用新版 market_service"""
from __future__ import annotations

import math
from libs.agents.skills import Skill, SkillRegistry


def _calc_indicators(bars: list[dict]) -> dict:
    """从 K 线数据计算完整技术指标"""
    if not bars:
        return {}

    closes = [float(b.get("close", 0)) for b in bars]
    highs  = [float(b.get("high", 0)) for b in bars]
    lows   = [float(b.get("low", 0)) for b in bars]
    vols   = [float(b.get("amount", b.get("volume", 0))) for b in bars]
    n = len(closes)

    def ma(period):
        if n < period:
            return None
        return round(sum(closes[-period:]) / period, 3)

    def ema(period):
        if n < period:
            return None
        k = 2 / (period + 1)
        e = closes[0]
        for p in closes[1:]:
            e = p * k + e * (1 - k)
        return round(e, 3)

    def rsi(period=14):
        if n < period + 1:
            return None
        gains, losses = [], []
        for i in range(1, n):
            d = closes[i] - closes[i-1]
            gains.append(max(d, 0))
            losses.append(max(-d, 0))
        ag = sum(gains[-period:]) / period
        al = sum(losses[-period:]) / period
        if al == 0:
            return 100.0
        return round(100 - 100 / (1 + ag / al), 2)

    def macd():
        if n < 26:
            return None, None, None
        e12 = ema(12)
        e26 = ema(26)
        if e12 is None or e26 is None:
            return None, None, None
        dif = round(e12 - e26, 4)
        dea = round(dif * 0.9, 4)
        hist = round((dif - dea) * 2, 4)
        return dif, dea, hist

    def bollinger(period=20):
        if n < period:
            return None, None, None
        mid = sum(closes[-period:]) / period
        std = math.sqrt(sum((p - mid) ** 2 for p in closes[-period:]) / period)
        return round(mid - 2*std, 3), round(mid, 3), round(mid + 2*std, 3)

    def kdj(period=9):
        if n < period:
            return None, None, None
        h9 = max(highs[-period:])
        l9 = min(lows[-period:])
        if h9 == l9:
            return 50.0, 50.0, 50.0
        rsv = (closes[-1] - l9) / (h9 - l9) * 100
        k = round(rsv / 3 + 50 * 2 / 3, 2)
        d = round(k / 3 + 50 * 2 / 3, 2)
        j = round(3*k - 2*d, 2)
        return k, d, j

    ret = lambda p: round((closes[-1] - closes[-p]) / closes[-p] * 100, 2) if n >= p and closes[-p] else 0

    vol_ma20 = sum(vols[-20:]) / 20 if n >= 20 else None
    vol_ratio = round(vols[-1] / vol_ma20, 2) if vol_ma20 and vol_ma20 > 0 else None

    if n >= 20:
        daily_rets = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(max(1, n-20), n)]
        avg_r = sum(daily_rets) / len(daily_rets)
        vol_20d = round(math.sqrt(sum((r - avg_r)**2 for r in daily_rets) / len(daily_rets)) * 100, 3)
    else:
        vol_20d = None

    high_20 = max(highs[-20:]) if n >= 20 else max(highs)
    low_20  = min(lows[-20:]) if n >= 20 else min(lows)
    high_60 = max(highs[-60:]) if n >= 60 else max(highs)
    low_60  = min(lows[-60:]) if n >= 60 else min(lows)

    dif, dea, hist = macd()
    bb_lower, bb_mid, bb_upper = bollinger()
    k_val, d_val, j_val = kdj()

    return {
        "ma5": ma(5), "ma10": ma(10), "ma20": ma(20), "ma60": ma(60),
        "ema12": ema(12), "ema26": ema(26),
        "rsi14": rsi(14),
        "macd_dif": dif, "macd_dea": dea, "macd_hist": hist,
        "bb_lower": bb_lower, "bb_mid": bb_mid, "bb_upper": bb_upper,
        "kdj_k": k_val, "kdj_d": d_val, "kdj_j": j_val,
        "ret_1d": ret(2), "ret_5d": ret(5), "ret_10d": ret(10),
        "ret_20d": ret(20), "ret_60d": ret(60),
        "vol_20d": vol_20d, "vol_ratio": vol_ratio,
        "high_20": round(high_20, 3), "low_20": round(low_20, 3),
        "high_60": round(high_60, 3), "low_60": round(low_60, 3),
        "current": round(closes[-1], 3),
        "pos_in_20d": round((closes[-1] - low_20) / (high_20 - low_20) * 100, 1) if high_20 != low_20 else 50,
        "pos_in_60d": round((closes[-1] - low_60) / (high_60 - low_60) * 100, 1) if high_60 != low_60 else 50,
    }


def _detect_patterns(bars: list[dict]) -> list[dict]:
    """识别 K 线形态"""
    if len(bars) < 20:
        return []

    closes = [float(b.get("close", 0)) for b in bars]
    highs  = [float(b.get("high", 0)) for b in bars]
    lows   = [float(b.get("low", 0)) for b in bars]
    vols   = [float(b.get("amount", b.get("volume", 0))) for b in bars]
    n = len(closes)

    patterns = []

    # 均线
    ma5  = sum(closes[-5:]) / 5 if n >= 5 else None
    ma20 = sum(closes[-20:]) / 20 if n >= 20 else None
    ma5_prev  = sum(closes[-6:-1]) / 5 if n >= 6 else None
    ma20_prev = sum(closes[-21:-1]) / 20 if n >= 21 else None

    if ma5 and ma20 and ma5_prev and ma20_prev:
        if ma5_prev <= ma20_prev and ma5 > ma20:
            patterns.append({"name": "golden_cross", "desc": "MA5 上穿 MA20，多头信号", "type": "bull"})
        elif ma5_prev >= ma20_prev and ma5 < ma20:
            patterns.append({"name": "death_cross", "desc": "MA5 下穿 MA20，空头信号", "type": "bear"})

    # 突破/跌破
    if n >= 21:
        recent_high = max(highs[-21:-1])
        recent_low  = min(lows[-21:-1])
        if closes[-1] > recent_high:
            patterns.append({"name": "breakout_high", "desc": f"突破 20 日高点 {recent_high:.2f}", "type": "bull"})
        if closes[-1] < recent_low:
            patterns.append({"name": "breakdown_low", "desc": f"跌破 20 日低点 {recent_low:.2f}", "type": "bear"})

    # 量能
    if n >= 25:
        avg_vol = sum(vols[-25:-1]) / 24
        if avg_vol > 0:
            ratio = vols[-1] / avg_vol
            if ratio >= 2.0:
                patterns.append({"name": "volume_surge", "desc": f"成交量放大 {ratio:.1f}×", "type": "neutral"})
            elif ratio <= 0.4:
                patterns.append({"name": "volume_dry_up", "desc": "成交量大幅萎缩", "type": "warn"})

    # 量价背离
    if n >= 10:
        close_5d_max = max(closes[-5:])
        close_prev_5d_max = max(closes[-10:-5])
        vol_5d_avg = sum(vols[-5:]) / 5
        vol_prev_5d_avg = sum(vols[-10:-5]) / 5 if sum(vols[-10:-5]) > 0 else 1
        if close_5d_max > close_prev_5d_max * 1.02 and vol_5d_avg < vol_prev_5d_avg * 0.85:
            patterns.append({"name": "volume_price_divergence", "desc": "价涨量缩，上涨乏力", "type": "warn"})

    # 高位震荡（派发特征）
    if n >= 20:
        up_20d = (closes[-1] - closes[-20]) / closes[-20] if closes[-20] else 0
        range_5d = (max(closes[-5:]) - min(closes[-5:])) / closes[-1] if closes[-1] else 0
        if up_20d > 0.12 and range_5d < 0.02:
            patterns.append({"name": "distribution_zone", "desc": f"20日累涨{up_20d*100:.1f}%后高位窄幅震荡，派发特征", "type": "bear"})

    return patterns


def register_technical_skills(reg: SkillRegistry) -> None:
    from apps.api.app.services import market_service

    def _get_features(symbol: str) -> dict:
        bars = market_service.get_kline(symbol, period="daily", count=120)
        if not bars:
            return {"error": "no bars"}
        ind = _calc_indicators(bars)
        ind["symbol"] = symbol
        return ind

    def _detect_pattern(symbol: str) -> dict:
        bars = market_service.get_kline(symbol, period="daily", count=120)
        if len(bars) < 20:
            return {"error": "need at least 20 bars", "patterns": []}

        closes = [float(b.get("close", 0)) for b in bars]
        highs  = [float(b.get("high", 0)) for b in bars]
        lows   = [float(b.get("low", 0)) for b in bars]
        n = len(closes)

        ma20 = sum(closes[-20:]) / 20
        above_ma20 = closes[-1] > ma20
        slope_20 = (closes[-1] - closes[-20]) / closes[-20] if closes[-20] else 0

        if slope_20 > 0.10:
            trend = "strong_up"
        elif slope_20 > 0.03:
            trend = "up"
        elif slope_20 < -0.10:
            trend = "strong_down"
        elif slope_20 < -0.03:
            trend = "down"
        else:
            trend = "sideways"

        patterns = _detect_patterns(bars)

        high_20 = max(highs[-20:]) if n >= 20 else max(highs)
        low_20  = min(lows[-20:]) if n >= 20 else min(lows)

        return {
            "symbol": symbol,
            "trend_20d": trend,
            "trend_pct": round(slope_20, 4),
            "patterns": patterns,
            "ma20": round(ma20, 2),
            "above_ma20": above_ma20,
            "current_close": closes[-1],
            "recent_20d_high": round(high_20, 2),
            "recent_20d_low": round(low_20, 2),
        }

    def _support_resistance(symbol: str) -> dict:
        bars = market_service.get_kline(symbol, period="daily", count=60)
        if len(bars) < 20:
            return {"error": "need at least 20 bars"}
        highs  = [float(b.get("high", 0)) for b in bars[-30:]]
        lows   = [float(b.get("low", 0)) for b in bars[-30:]]
        closes = [float(b.get("close", 0)) for b in bars[-30:]]
        current = closes[-1]

        sorted_h = sorted(set(highs), reverse=True)[:5]
        sorted_l = sorted(set(lows))[:5]

        resistances = [round(h, 2) for h in sorted_h if h > current][:3]
        supports    = [round(l, 2) for l in sorted_l if l < current][:3]

        return {
            "symbol": symbol,
            "current_close": current,
            "resistance_levels": resistances,
            "support_levels": supports,
            "nearest_resistance": resistances[0] if resistances else None,
            "nearest_support": supports[0] if supports else None,
            "distance_to_resistance_pct": round((resistances[0] - current) / current * 100, 2) if resistances else None,
            "distance_to_support_pct": round((current - supports[0]) / current * 100, 2) if supports else None,
        }

    reg.register_many([
        Skill(
            name="get_technical_features",
            description="计算完整技术指标：MA5/10/20/60、EMA12/26、RSI14、MACD(DIF/DEA/柱)、KDJ、布林带、各周期涨跌幅、波动率、量比、价格区间位置。",
            parameters={
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
            },
            handler=_get_features,
            category="technical",
        ),
        Skill(
            name="detect_chart_pattern",
            description="识别K线形态：金叉/死叉、突破/跌破20日高低点、量能异常、量价背离、高位派发等。返回趋势方向和形态列表。",
            parameters={
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
            },
            handler=_detect_pattern,
            category="technical",
        ),
        Skill(
            name="get_support_resistance",
            description="基于近60日K线计算支撑位与阻力位，返回最近3个支撑/阻力价格及距离百分比。",
            parameters={
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
            },
            handler=_support_resistance,
            category="technical",
        ),
    ])
