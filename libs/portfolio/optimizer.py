"""Portfolio optimization and rebalancing.

Supported allocation schemes (see :class:`WeightingScheme`):
  - SIGNAL_PROPORTIONAL: weight ∝ signal score (default; legacy behaviour)
  - EQUAL_WEIGHT: equal weight across all candidates
  - INVERSE_VOLATILITY: weight ∝ 1 / σ (low-vol stocks get more capital)
  - RISK_ADJUSTED: weight ∝ signal / σ (Sharpe-flavoured allocation)

All schemes respect :class:`PortfolioConstraints` (single-stock cap, cash buffer,
max positions) and are renormalised iteratively to satisfy the cap.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from libs.quant_core.models import Position


class WeightingScheme(str, Enum):
    """Allocation strategy for converting signals into target weights."""
    SIGNAL_PROPORTIONAL = "signal_proportional"
    EQUAL_WEIGHT = "equal_weight"
    INVERSE_VOLATILITY = "inverse_volatility"
    RISK_ADJUSTED = "risk_adjusted"


@dataclass(frozen=True)
class PortfolioConstraints:
    """Portfolio optimization constraints."""
    max_single_stock_weight: float = 0.15
    max_industry_weight: float = 0.40
    max_turnover: float = 0.50
    min_cash_ratio: float = 0.05
    max_positions: int = 30


@dataclass(frozen=True)
class RebalanceAction:
    """Rebalancing action for a symbol."""
    symbol: str
    current_weight: float
    target_weight: float
    action: str  # BUY, SELL, HOLD
    quantity_change: int
    estimated_value_change: float
    reason: str


@dataclass(frozen=True)
class PortfolioOptimizationResult:
    """Portfolio optimization result."""
    actions: list[RebalanceAction]
    expected_turnover: float
    expected_cash_ratio: float
    risk_metrics: dict[str, float]
    warnings: list[str]


class PortfolioOptimizer:
    """Optimize portfolio allocation and rebalancing."""
    
    def __init__(self, constraints: Optional[PortfolioConstraints] = None) -> None:
        self.constraints = constraints or PortfolioConstraints()
    
    def calculate_target_weights(
        self,
        signals: dict[str, float],  # symbol -> signal score
        current_positions: list[Position],
        total_value: float,
        *,
        scheme: WeightingScheme = WeightingScheme.SIGNAL_PROPORTIONAL,
        volatilities: Optional[dict[str, float]] = None,
    ) -> dict[str, float]:
        """Calculate target weights based on signals, constraints, and chosen scheme.

        Args:
            signals: Signal scores for each symbol (-1.0 to 1.0).
            current_positions: Current portfolio positions (used for context only).
            total_value: Total portfolio value (used for context only).
            scheme: Allocation strategy. See :class:`WeightingScheme`.
            volatilities: Per-symbol 20-day daily volatility, REQUIRED for
                INVERSE_VOLATILITY and RISK_ADJUSTED schemes.

        Returns:
            Target weights for each symbol (sum may be < 1 due to cash buffer).
        """
        # Filter positive signals
        positive_signals = {s: score for s, score in signals.items() if score > 0}
        if not positive_signals:
            return {}

        # --- Compute raw weights according to chosen scheme ---
        raw_weights = self._raw_weights(positive_signals, scheme, volatilities)
        if not raw_weights:
            return {}
        if self.constraints.max_positions <= 0:
            return {}

        if len(raw_weights) > self.constraints.max_positions:
            selected = sorted(
                raw_weights,
                key=lambda symbol: (raw_weights[symbol], positive_signals.get(symbol, 0.0), symbol),
                reverse=True,
            )[: self.constraints.max_positions]
            raw_weights = {symbol: raw_weights[symbol] for symbol in selected}

        investable_ratio = 1.0 - self.constraints.min_cash_ratio
        cap = self.constraints.max_single_stock_weight
        if investable_ratio <= 0 or cap <= 0:
            return {}

        # Water-filling allocation: capped names keep their cap while the
        # residual budget is redistributed across uncapped names only.
        remaining = set(raw_weights)
        remaining_budget = investable_ratio
        target_weights: dict[str, float] = {}

        while remaining and remaining_budget > 1e-9:
            total_raw = sum(raw_weights[symbol] for symbol in remaining)
            if total_raw <= 0:
                break

            capped_this_round = []
            for symbol in sorted(remaining):
                proposed = remaining_budget * (raw_weights[symbol] / total_raw)
                if proposed > cap:
                    target_weights[symbol] = cap
                    capped_this_round.append(symbol)

            if not capped_this_round:
                for symbol in sorted(remaining):
                    target_weights[symbol] = remaining_budget * (raw_weights[symbol] / total_raw)
                break

            for symbol in capped_this_round:
                remaining.remove(symbol)
                remaining_budget -= cap

            if remaining_budget <= 1e-9:
                break

        return target_weights

    def _raw_weights(
        self,
        positive_signals: dict[str, float],
        scheme: WeightingScheme,
        volatilities: Optional[dict[str, float]],
    ) -> dict[str, float]:
        """Convert positive signals into raw (unnormalised→normalised) weights."""
        if scheme == WeightingScheme.EQUAL_WEIGHT:
            n = len(positive_signals)
            return {symbol: 1.0 / n for symbol in positive_signals}

        if scheme == WeightingScheme.INVERSE_VOLATILITY:
            if not volatilities:
                # Fall back to equal weight when no vol data is supplied
                n = len(positive_signals)
                return {symbol: 1.0 / n for symbol in positive_signals}
            inv_vol = {}
            for symbol in positive_signals:
                vol = volatilities.get(symbol, 0.0)
                # Floor vol at 0.5% to avoid blow-ups for halted/low-vol names
                vol = max(vol, 0.005)
                inv_vol[symbol] = 1.0 / vol
            total = sum(inv_vol.values())
            return {s: w / total for s, w in inv_vol.items()} if total > 0 else {}

        if scheme == WeightingScheme.RISK_ADJUSTED:
            # Sharpe-flavoured: weight ∝ signal / vol
            if not volatilities:
                # No vol data → same as signal proportional
                total = sum(positive_signals.values())
                return {s: v / total for s, v in positive_signals.items()}
            ratios = {}
            for symbol, score in positive_signals.items():
                vol = max(volatilities.get(symbol, 0.0), 0.005)
                ratios[symbol] = score / vol
            total = sum(ratios.values())
            return {s: w / total for s, w in ratios.items()} if total > 0 else {}

        # Default: SIGNAL_PROPORTIONAL
        total = sum(positive_signals.values())
        if total <= 0:
            return {}
        return {symbol: score / total for symbol, score in positive_signals.items()}
    
    def generate_rebalance_actions(
        self,
        target_weights: dict[str, float],
        current_positions: list[Position],
        total_value: float,
        current_prices: dict[str, float],
    ) -> list[RebalanceAction]:
        """
        Generate rebalancing actions.
        
        Args:
            target_weights: Target weights for each symbol
            current_positions: Current positions
            total_value: Total portfolio value
            current_prices: Current prices for each symbol
            
        Returns:
            List of rebalancing actions
        """
        actions = []

        def _lot_quantity(value_change: float, price: float) -> int:
            if price <= 0:
                return 0
            return int(abs(value_change) / price / 100) * 100
        
        # Calculate current weights
        current_weights = {}
        for pos in current_positions:
            current_weights[pos.symbol] = pos.market_value / total_value
        
        # Process all symbols (current + target)
        all_symbols = set(current_weights.keys()) | set(target_weights.keys())

        for symbol in sorted(all_symbols):
            current_weight = current_weights.get(symbol, 0.0)
            target_weight = target_weights.get(symbol, 0.0)
            
            weight_diff = target_weight - current_weight
            
            # Determine action
            if abs(weight_diff) < 0.01:  # Less than 1% difference
                action_type = "HOLD"
                quantity_change = 0
                value_change = 0.0
                reason = "权重差异小于1%，保持不变"
            elif weight_diff > 0:
                action_type = "BUY"
                value_change = weight_diff * total_value
                price = current_prices.get(symbol, 0.0)
                quantity_change = _lot_quantity(value_change, price)
                reason = f"增加仓位至目标权重{target_weight:.2%}"
            else:
                action_type = "SELL"
                value_change = weight_diff * total_value
                price = current_prices.get(symbol, 0.0)
                quantity_change = _lot_quantity(value_change, price)
                reason = f"减少仓位至目标权重{target_weight:.2%}"

            if action_type != "HOLD" and quantity_change > 0:
                actions.append(RebalanceAction(
                    symbol=symbol,
                    current_weight=current_weight,
                    target_weight=target_weight,
                    action=action_type,
                    quantity_change=quantity_change,
                    estimated_value_change=value_change,
                    reason=reason,
                ))
        
        return actions
    
    def optimize(
        self,
        signals: dict[str, float],
        current_positions: list[Position],
        total_value: float,
        current_prices: dict[str, float],
        industry_map: Optional[dict[str, str]] = None,
        *,
        scheme: WeightingScheme = WeightingScheme.SIGNAL_PROPORTIONAL,
        volatilities: Optional[dict[str, float]] = None,
    ) -> PortfolioOptimizationResult:
        """
        Optimize portfolio allocation.
        
        Args:
            signals: Signal scores for each symbol
            current_positions: Current positions
            total_value: Total portfolio value
            current_prices: Current prices
            industry_map: Symbol to industry mapping
            
        Returns:
            Optimization result with rebalancing actions
        """
        # Calculate target weights
        target_weights = self.calculate_target_weights(
            signals,
            current_positions,
            total_value,
            scheme=scheme,
            volatilities=volatilities,
        )
        
        # Generate rebalancing actions
        actions = self.generate_rebalance_actions(
            target_weights, current_positions, total_value, current_prices
        )
        
        # Calculate expected turnover
        expected_turnover = sum(
            abs(action.estimated_value_change) for action in actions
        ) / total_value
        
        # Calculate expected cash ratio
        total_target_weight = sum(target_weights.values())
        expected_cash_ratio = 1.0 - total_target_weight
        
        # Check constraints and generate warnings
        warnings = []
        positive_signal_count = sum(1 for score in signals.values() if score > 0)
        if positive_signal_count > self.constraints.max_positions:
            warnings.append(
                f"候选信号数{positive_signal_count}超过最大持仓数{self.constraints.max_positions}，已保留权重最高的{self.constraints.max_positions}只"
            )
        
        if expected_turnover > self.constraints.max_turnover:
            warnings.append(
                f"预期换手率{expected_turnover:.2%}超过限制{self.constraints.max_turnover:.2%}"
            )
        
        if expected_cash_ratio < self.constraints.min_cash_ratio:
            warnings.append(
                f"预期现金比例{expected_cash_ratio:.2%}低于最低要求{self.constraints.min_cash_ratio:.2%}"
            )
        
        # Check industry concentration
        if industry_map:
            industry_weights = {}
            for symbol, weight in target_weights.items():
                industry = industry_map.get(symbol, "未知")
                industry_weights[industry] = industry_weights.get(industry, 0.0) + weight
            
            for industry, weight in industry_weights.items():
                if weight > self.constraints.max_industry_weight:
                    warnings.append(
                        f"行业{industry}权重{weight:.2%}超过限制{self.constraints.max_industry_weight:.2%}"
                    )
        
        # Calculate risk metrics
        risk_metrics = {
            "turnover": expected_turnover,
            "cash_ratio": expected_cash_ratio,
            "num_positions": len(target_weights),
            "max_single_weight": max(target_weights.values()) if target_weights else 0.0,
        }
        
        return PortfolioOptimizationResult(
            actions=actions,
            expected_turnover=expected_turnover,
            expected_cash_ratio=expected_cash_ratio,
            risk_metrics=risk_metrics,
            warnings=warnings,
        )
