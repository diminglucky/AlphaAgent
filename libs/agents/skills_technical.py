"""Technical-analysis skills."""

from __future__ import annotations

from libs.agents.skills import Skill, SkillRegistry


def register_technical_skills(reg: SkillRegistry) -> None:
    from apps.api.app.services.market_service import MarketService
    from libs.features.technical import build_technical_features

    market = MarketService()

    def _get_features(symbol: str) -> dict:
        bars = market.get_bars(symbol=symbol, freq="1d")
        if not bars:
            return {"error": "no bars"}
        feat = build_technical_features(
            symbol, [(b.trade_date, b.close, b.volume, b.turnover_rate) for b in bars]
        )
        if feat is None:
            return {"error": "insufficient data"}
        return {
            "symbol": symbol,
            "as_of_date": str(feat.as_of_date),
            "current_close": feat.close,
            "returns_1d": feat.returns_1d,
            "return_5d": feat.returns_5d,
            "return_20d": feat.returns_20d,
            "ma_5d": feat.ma_5d,
            "ma_20d": feat.ma_20d,
            "ma_60d": feat.ma_60d,
            "volatility_20d": feat.volatility_20d,
            "rsi_14d": feat.rsi_14d,
            "macd_hist": feat.macd_hist,
            "volume_ratio_5d": feat.volume_ratio_5d,
            "current_volume": feat.volume,
            "current_turnover": feat.turnover_rate,
        }

    def _detect_pattern(symbol: str) -> dict:
        """Detect simple patterns: trend break, breakout, divergence, etc."""
        bars = market.get_bars(symbol=symbol, freq="1d")
        if len(bars) < 20:
            return {"error": "need at least 20 bars"}
        closes = [b.close for b in bars]
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        volumes = [b.volume for b in bars]

        ma20 = sum(closes[-20:]) / 20
        prev_ma20 = sum(closes[-21:-1]) / 20 if len(closes) >= 21 else ma20

        patterns = []

        # Golden cross / death cross (5 vs 20)
        if len(closes) >= 21:
            ma5 = sum(closes[-5:]) / 5
            ma5_prev = sum(closes[-6:-1]) / 5
            if ma5_prev <= prev_ma20 and ma5 > ma20:
                patterns.append({"name": "golden_cross", "desc": "MA5 上穿 MA20，多头信号"})
            elif ma5_prev >= prev_ma20 and ma5 < ma20:
                patterns.append({"name": "death_cross", "desc": "MA5 下穿 MA20，空头信号"})

        # Breakout: close > 20-day high
        recent_high = max(highs[-21:-1]) if len(highs) >= 21 else max(highs[:-1])
        if closes[-1] > recent_high:
            patterns.append({"name": "breakout_high", "desc": f"突破 20 日高点 {recent_high:.2f}"})

        # Breakdown: close < 20-day low
        recent_low = min(lows[-21:-1]) if len(lows) >= 21 else min(lows[:-1])
        if closes[-1] < recent_low:
            patterns.append({"name": "breakdown_low", "desc": f"跌破 20 日低点 {recent_low:.2f}"})

        # Volume surge
        if len(volumes) >= 25:
            avg_vol = sum(volumes[-25:-1]) / 24
            if avg_vol > 0 and volumes[-1] / avg_vol >= 2.0:
                patterns.append({"name": "volume_surge", "desc": f"成交量是 24日均量 {volumes[-1]/avg_vol:.1f}×"})
            elif avg_vol > 0 and volumes[-1] / avg_vol <= 0.4:
                patterns.append({"name": "volume_dry_up", "desc": "成交量大幅萎缩"})

        # Trend
        slope_20 = (closes[-1] - closes[-20]) / closes[-20] if len(closes) >= 20 and closes[-20] else 0
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

        # ==============================================================
        # FORWARD-LOOKING / PREDICTIVE PATTERNS — fire BEFORE the damage.
        # These let Guardian recommend WATCH/REDUCE *before* a loss occurs.
        # ==============================================================
        feat = build_technical_features(
            symbol, [(b.trade_date, b.close, b.volume, b.turnover_rate) for b in bars]
        )

        # 1. RSI Bearish Divergence — price made a new high, but RSI didn't.
        #    Strongly signals exhaustion BEFORE the top is confirmed.
        if feat is not None and feat.rsi_14d is not None and len(closes) >= 30:
            recent_close = closes[-1]
            highest_20 = max(closes[-20:])
            highest_idx = len(closes) - 20 + closes[-20:].index(highest_20)
            if recent_close >= highest_20 * 0.98 and feat.rsi_14d > 60:
                # Compute RSI snapshot 5-15 bars ago, see if it was higher then
                from libs.features.technical import build_technical_features as _bt
                older = _bt(
                    symbol,
                    [(b.trade_date, b.close, b.volume, b.turnover_rate)
                     for b in bars[: highest_idx + 1]],
                )
                if older is not None and older.rsi_14d is not None:
                    if older.rsi_14d > feat.rsi_14d + 3:
                        patterns.append({
                            "name": "rsi_bearish_divergence",
                            "desc": (
                                f"价格逼近近 20 日高点，但 RSI({feat.rsi_14d:.1f}) "
                                f"较前次高点 RSI({older.rsi_14d:.1f}) 已走弱 → "
                                "动能衰竭，顶部预警"
                            ),
                            "severity": "warning",
                        })

        # 2. MACD Weakening — histogram shrinking 3 days in a row while
        #    DIF still above DEA. Death cross typically forms 3-5 bars later.
        if feat is not None and feat.macd_hist is not None and len(bars) >= 30:
            hist_seq = []
            for i in range(max(0, len(bars) - 4), len(bars)):
                f = build_technical_features(
                    symbol,
                    [(b.trade_date, b.close, b.volume, b.turnover_rate) for b in bars[: i + 1]],
                )
                if f is not None and f.macd_hist is not None:
                    hist_seq.append(f.macd_hist)
            if (
                len(hist_seq) >= 4
                and hist_seq[-1] > 0
                and hist_seq[-1] < hist_seq[-2] < hist_seq[-3] < hist_seq[-4]
            ):
                patterns.append({
                    "name": "macd_weakening",
                    "desc": (
                        f"MACD 柱连续 3 日萎缩 ({hist_seq[-4]:.2f}→{hist_seq[-1]:.2f})，"
                        "死叉概率上升，提前减仓预警"
                    ),
                    "severity": "warning",
                })

        # 3. Volume-Price Divergence — price 5-day high but volume drying.
        #    Classic upthrust without supply, often precedes top.
        if len(closes) >= 10:
            close_5d_max = max(closes[-5:])
            close_prev_5d_max = max(closes[-10:-5])
            vol_5d_avg = sum(volumes[-5:]) / 5
            vol_prev_5d_avg = sum(volumes[-10:-5]) / 5 if sum(volumes[-10:-5]) > 0 else 1
            if (
                close_5d_max > close_prev_5d_max * 1.02
                and vol_5d_avg < vol_prev_5d_avg * 0.85
            ):
                patterns.append({
                    "name": "volume_price_divergence",
                    "desc": (
                        f"5 日新高但量能较前 5 日萎缩 "
                        f"{(1 - vol_5d_avg/vol_prev_5d_avg)*100:.0f}% → 上涨乏力"
                    ),
                    "severity": "warning",
                })

        # 4. Approaching Resistance — price within 2% of nearest 30-day swing
        #    high while RSI > 65. High probability of rejection.
        if len(highs) >= 30 and feat is not None and feat.rsi_14d is not None:
            recent_swing_highs = sorted(set(highs[-30:-1]), reverse=True)[:3]
            nearest_above = next((h for h in recent_swing_highs if h > closes[-1]), None)
            if nearest_above is not None:
                gap_pct = (nearest_above - closes[-1]) / closes[-1]
                if gap_pct < 0.02 and feat.rsi_14d > 65:
                    patterns.append({
                        "name": "approaching_resistance",
                        "desc": (
                            f"距阻力位 {nearest_above:.2f} 仅 {gap_pct*100:.1f}%，"
                            f"RSI {feat.rsi_14d:.0f} 偏高 → 受阻回调风险"
                        ),
                        "severity": "warning",
                    })

        # 5. Distribution Pattern — price up >12% in 20 days but recent 5-day
        #    range tight (<2%) — sideways at top is classic distribution.
        if len(closes) >= 20:
            up_20d = (closes[-1] - closes[-20]) / closes[-20] if closes[-20] else 0
            range_5d = (max(closes[-5:]) - min(closes[-5:])) / closes[-1] if closes[-1] else 0
            if up_20d > 0.12 and range_5d < 0.02:
                patterns.append({
                    "name": "distribution_zone",
                    "desc": (
                        f"20 日累涨 {up_20d*100:.1f}%，但近 5 日窄幅震荡 ({range_5d*100:.1f}%) "
                        "→ 高位筹码派发特征"
                    ),
                    "severity": "warning",
                })

        return {
            "symbol": symbol,
            "trend_20d": trend,
            "trend_pct": round(slope_20, 4),
            "patterns": patterns,
            "ma20": round(ma20, 2),
            "above_ma20": closes[-1] > ma20,
            "current_close": closes[-1],
            "recent_20d_high": recent_high,
            "recent_20d_low": recent_low,
            "rsi_14d": feat.rsi_14d if feat else None,
        }

    def _support_resistance(symbol: str) -> dict:
        """Compute simple swing-based support/resistance levels."""
        bars = market.get_bars(symbol=symbol, freq="1d")
        if len(bars) < 30:
            return {"error": "need at least 30 bars"}
        highs = [b.high for b in bars[-30:]]
        lows = [b.low for b in bars[-30:]]
        closes = [b.close for b in bars[-30:]]
        # Simple proxy: top 3 resistances = top 3 swing highs;
        # top 3 supports = bottom 3 swing lows
        sorted_h = sorted(highs, reverse=True)[:3]
        sorted_l = sorted(lows)[:3]
        return {
            "symbol": symbol,
            "current_close": closes[-1],
            "resistance_levels": [round(x, 2) for x in sorted_h],
            "support_levels": [round(x, 2) for x in sorted_l],
            "distance_to_nearest_resistance_pct": round(
                (min(r for r in sorted_h if r > closes[-1]) - closes[-1]) / closes[-1] * 100
                if any(r > closes[-1] for r in sorted_h) else 0, 2
            ),
            "distance_to_nearest_support_pct": round(
                (closes[-1] - max(s for s in sorted_l if s < closes[-1])) / closes[-1] * 100
                if any(s < closes[-1] for s in sorted_l) else 0, 2
            ),
        }

    reg.register_many([
        Skill(
            name="get_technical_features",
            description="计算技术指标快照：5/20/60 日均线、5/20 日收益率、波动率、RSI14、量比。Agent 用于趋势与超买超卖判断。",
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
            description="识别 K 线形态：金叉/死叉、突破/跌破 20 日高低点、量能异常、趋势状态。Agent 用于判断买卖时机。",
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
            description="基于近 30 日 swing 计算支撑位与阻力位。Agent 用于设定止损止盈或判断安全边际。",
            parameters={
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
            },
            handler=_support_resistance,
            category="technical",
        ),
    ])
