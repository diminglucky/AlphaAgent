"""Signal generation engine for stock recommendations.

Fusion hierarchy (§4.3.5):
  1. Technical score  — momentum / trend / volume / volatility + KDJ
  2. Fundamental score — valuation / growth (optional)
  3. Market-regime multiplier — BULL/BEAR/SIDEWAYS … (optional)
  4. Final: weighted sum → clipped to [-1, 1]
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from libs.features.fundamental import FundamentalFeatures, score_growth, score_valuation
from libs.features.market_state import MarketRegime, MarketState
from libs.features.technical import TechnicalFeatures
from libs.quant_core.enums import RecommendationAction


@dataclass(frozen=True)
class SignalScore:
    """Signal score for a symbol."""
    symbol: str
    raw_score: float  # -1.0 to 1.0, negative = bearish, positive = bullish
    confidence: float  # 0.0 to 1.0
    components: dict[str, float]  # Individual signal components
    timestamp: datetime


class SignalEngine:
    """Generate trading signals from technical features."""
    
    # -----------------------------------------------------------------
    # Regime-level bias and confidence scaling (additive adjustments)
    # -----------------------------------------------------------------
    _REGIME_BIAS: dict[str, float] = {
        MarketRegime.BULL:         +0.06,
        MarketRegime.RECOVERY:     +0.02,
        MarketRegime.SIDEWAYS:      0.00,
        MarketRegime.DISTRIBUTION: -0.04,
        MarketRegime.BEAR:         -0.10,
    }
    _REGIME_CONFIDENCE: dict[str, float] = {
        MarketRegime.BULL:          1.00,
        MarketRegime.RECOVERY:      0.90,
        MarketRegime.SIDEWAYS:      0.70,
        MarketRegime.DISTRIBUTION:  0.80,
        MarketRegime.BEAR:          0.85,
    }

    def __init__(self) -> None:
        # Technical component weights (sum = 1.0)
        self.momentum_weight = 0.28
        self.kdj_weight      = 0.10   # KDJ stochastic
        self.trend_weight    = 0.25
        self.volume_weight   = 0.17
        self.volatility_weight = 0.10
        # Fundamental weight (only applied when fundamentals are passed)
        self.fundamental_weight = 0.10
        # Legacy aliases (kept for backward compat)
        self.macd_weight = 0.15
        self.bb_weight   = 0.10
    
    def calculate_momentum_score(self, features: TechnicalFeatures) -> float:
        """Calculate momentum score from returns, RSI, and MACD cross."""
        score = 0.0

        # Short-term momentum (1-day and 5-day returns)
        if features.returns_1d > 0.02:  # > 2% gain
            score += 0.3
        elif features.returns_1d < -0.02:  # > 2% loss
            score -= 0.3

        if features.returns_5d > 0.05:  # > 5% gain in 5 days
            score += 0.4
        elif features.returns_5d < -0.05:
            score -= 0.4

        # RSI indicator
        if features.rsi_14d is not None:
            if features.rsi_14d > 70:  # Overbought
                score -= 0.3
            elif features.rsi_14d < 30:  # Oversold
                score += 0.3
            elif 40 <= features.rsi_14d <= 60:  # Neutral zone
                score += 0.1

        # MACD: DIF above DEA (golden cross region) = bullish momentum
        if features.macd_dif is not None and features.macd_dea is not None:
            if features.macd_dif > features.macd_dea:
                score += 0.2
            else:
                score -= 0.2
            # Strong histogram divergence
            if features.macd_hist is not None:
                if features.macd_hist > 0.5:
                    score += 0.1
                elif features.macd_hist < -0.5:
                    score -= 0.1

        return max(-1.0, min(1.0, score))
    
    def calculate_trend_score(self, features: TechnicalFeatures) -> float:
        """Calculate trend score from moving averages and Bollinger Bands."""
        score = 0.0

        # Check if price is above moving averages
        if features.ma_5d and features.close > features.ma_5d:
            score += 0.3
        elif features.ma_5d and features.close < features.ma_5d:
            score -= 0.3

        if features.ma_20d and features.close > features.ma_20d:
            score += 0.4
        elif features.ma_20d and features.close < features.ma_20d:
            score -= 0.4

        # Check MA alignment (bullish: MA5 > MA20 > MA60)
        if features.ma_5d and features.ma_20d and features.ma_60d:
            if features.ma_5d > features.ma_20d > features.ma_60d:
                score += 0.3
            elif features.ma_5d < features.ma_20d < features.ma_60d:
                score -= 0.3

        # Bollinger Bands: price near lower band = potential reversal (oversold),
        # near upper band = potential reversal (overbought)
        if features.bb_pct_b is not None:
            if features.bb_pct_b < 0.0:  # below lower band
                score += 0.2  # mean-reversion bounce signal
            elif features.bb_pct_b > 1.0:  # above upper band
                score -= 0.2  # overextended, potential pullback
            elif features.bb_pct_b > 0.8:  # near upper but inside = strong uptrend
                score += 0.1

        return max(-1.0, min(1.0, score))
    
    def calculate_volume_score(self, features: TechnicalFeatures) -> float:
        """Calculate volume score from volume ratio and turnover."""
        score = 0.0
        
        # Volume surge with positive returns is bullish
        if features.volume_ratio_5d > 1.5:  # 50% above average
            if features.returns_1d > 0:
                score += 0.5
            else:
                score -= 0.3  # Volume surge with negative returns is bearish
        elif features.volume_ratio_5d < 0.7:  # Low volume
            score -= 0.2
        
        # High turnover rate
        if features.turnover_rate > 5.0:  # > 5% turnover
            score += 0.2
        elif features.turnover_rate < 1.0:  # < 1% turnover (low liquidity)
            score -= 0.3
        
        return max(-1.0, min(1.0, score))
    
    def calculate_volatility_score(self, features: TechnicalFeatures) -> float:
        """Calculate volatility score (lower volatility is better for stability)."""
        score = 0.0
        
        # Penalize high volatility
        if features.volatility_20d > 0.03:  # > 3% daily volatility
            score -= 0.5
        elif features.volatility_20d < 0.015:  # < 1.5% daily volatility
            score += 0.3
        
        return max(-1.0, min(1.0, score))

    def calculate_kdj_score(self, features: TechnicalFeatures) -> float:
        """KDJ stochastic oscillator signal.

        Returns 0.0 when KDJ values are unavailable (OHLCV not supplied).
        """
        if features.kdj_k is None or features.kdj_d is None:
            return 0.0

        k, d = features.kdj_k, features.kdj_d
        score = 0.0

        # Oversold / overbought zone
        if k < 20:
            score += 0.4   # oversold → potential reversal up
        elif k < 30:
            score += 0.2
        elif k > 80:
            score -= 0.4   # overbought → potential reversal down
        elif k > 70:
            score -= 0.2

        # K/D crossover
        if k > d:
            score += 0.2   # K above D → bullish momentum
        else:
            score -= 0.2   # K below D → bearish momentum

        return max(-1.0, min(1.0, score))

    def calculate_fundamental_score(
        self, fundamentals: Optional[FundamentalFeatures]
    ) -> float:
        """Blend valuation + growth into a single [-1, 1] fundamental score.

        Returns 0.0 when *fundamentals* is ``None``.
        """
        if fundamentals is None:
            return 0.0
        val = score_valuation(fundamentals)
        gro = score_growth(fundamentals)
        # Equal blend; both already in [-1, 1]
        return max(-1.0, min(1.0, (val + gro) / 2.0))

    def generate_signal(
        self,
        features: TechnicalFeatures,
        *,
        fundamentals: Optional[FundamentalFeatures] = None,
        market_state: Optional[MarketState] = None,
    ) -> SignalScore:
        """Generate a multi-source trading signal.

        Parameters
        ----------
        features:
            Technical features (close prices, indicators …).
        fundamentals:
            Optional fundamental features; adds valuation / growth scoring.
        market_state:
            Optional macro regime; applies a regime bias and confidence
            scaling to the final score.
        """
        # --- Technical components ---
        momentum_score   = self.calculate_momentum_score(features)
        kdj_score        = self.calculate_kdj_score(features)
        trend_score      = self.calculate_trend_score(features)
        volume_score     = self.calculate_volume_score(features)
        volatility_score = self.calculate_volatility_score(features)

        # --- Fundamental component (optional) ---
        fundamental_score = self.calculate_fundamental_score(fundamentals)

        # --- Weighted combination ---
        # When fundamentals absent: redistribute fundamental_weight
        # proportionally across technical components so weights still sum to 1.
        if fundamentals is not None:
            tech_scale = 1.0 - self.fundamental_weight
            fund_contrib = fundamental_score * self.fundamental_weight
        else:
            tech_scale = 1.0
            fund_contrib = 0.0

        raw_score = (
            momentum_score   * self.momentum_weight   * tech_scale
            + kdj_score      * self.kdj_weight        * tech_scale
            + trend_score    * self.trend_weight      * tech_scale
            + volume_score   * self.volume_weight     * tech_scale
            + volatility_score * self.volatility_weight * tech_scale
            + fund_contrib
        )

        # --- Market-regime adjustment ---
        regime_bias       = 0.0
        confidence_factor = 1.0
        if market_state is not None:
            regime_bias       = self._REGIME_BIAS.get(market_state.regime, 0.0)
            confidence_factor = self._REGIME_CONFIDENCE.get(market_state.regime, 1.0)
            raw_score += regime_bias

        raw_score = max(-1.0, min(1.0, raw_score))

        # --- Confidence ---
        component_scores = [momentum_score, kdj_score, trend_score,
                            volume_score, volatility_score]
        avg_abs_score = sum(abs(s) for s in component_scores) / len(component_scores)
        score_variance = sum(
            (s - raw_score) ** 2 for s in component_scores
        ) / len(component_scores)
        consistency_factor = 1.0 / (1.0 + score_variance * 2)
        confidence = min(1.0, avg_abs_score * consistency_factor * confidence_factor)

        components: dict[str, float] = {
            "momentum":    momentum_score,
            "kdj":         kdj_score,
            "trend":       trend_score,
            "volume":      volume_score,
            "volatility":  volatility_score,
        }
        if fundamentals is not None:
            components["fundamental"] = fundamental_score
        if market_state is not None:
            components["regime_bias"] = regime_bias

        return SignalScore(
            symbol=features.symbol,
            raw_score=raw_score,
            confidence=confidence,
            components=components,
            timestamp=datetime.now(),
        )
    
    def signal_to_action(self, signal: SignalScore, threshold: float = 0.2) -> RecommendationAction:
        """Convert signal score to recommendation action."""
        if signal.raw_score > threshold:
            return RecommendationAction.BUY
        elif signal.raw_score < -threshold:
            return RecommendationAction.SELL
        else:
            return RecommendationAction.HOLD
