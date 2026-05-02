"""Tests for portfolio optimizer."""

import pytest

from libs.portfolio.optimizer import (
    PortfolioConstraints,
    PortfolioOptimizer,
    WeightingScheme,
)
from libs.quant_core.models import Position


# 5-stock fixtures: avg raw weight = 0.95/5 = 0.19, well below 30% cap,
# so the differentiation between schemes is preserved.
SIGNALS_5 = {"A": 0.8, "B": 0.6, "C": 0.5, "D": 0.4, "E": 0.3}
VOLS_5 = {"A": 0.030, "B": 0.020, "C": 0.010, "D": 0.025, "E": 0.015}


def test_equal_weight_scheme():
    optimizer = PortfolioOptimizer()
    weights = optimizer.calculate_target_weights(
        SIGNALS_5, [], 1_000_000.0, scheme=WeightingScheme.EQUAL_WEIGHT,
    )
    assert len(weights) == 5
    values = list(weights.values())
    # All weights should be equal
    for v in values[1:]:
        assert abs(v - values[0]) < 1e-9


def test_inverse_volatility_scheme():
    """Lowest-vol stock should get the largest weight."""
    optimizer = PortfolioOptimizer()
    weights = optimizer.calculate_target_weights(
        SIGNALS_5, [], 1_000_000.0,
        scheme=WeightingScheme.INVERSE_VOLATILITY,
        volatilities=VOLS_5,
    )
    # C has lowest vol (0.010) → largest weight; A has highest vol (0.030) → smallest
    assert weights["C"] > weights["E"]   # 0.010 vs 0.015
    assert weights["E"] > weights["B"]   # 0.015 vs 0.020
    assert weights["B"] > weights["D"]   # 0.020 vs 0.025
    assert weights["D"] > weights["A"]   # 0.025 vs 0.030


def test_inverse_volatility_no_vol_data_falls_back():
    """Without vols, INVERSE_VOLATILITY falls back to equal weight."""
    optimizer = PortfolioOptimizer()
    weights = optimizer.calculate_target_weights(
        SIGNALS_5, [], 1_000_000.0,
        scheme=WeightingScheme.INVERSE_VOLATILITY,
        volatilities=None,
    )
    values = list(weights.values())
    for v in values[1:]:
        assert abs(v - values[0]) < 1e-9  # equal-weight fallback


def test_risk_adjusted_scheme():
    """Risk-adjusted: weight ∝ signal / vol.

    Compare A (0.8/0.030 = 26.7) vs C (0.5/0.010 = 50).
    Despite lower raw signal, C should outweigh A.
    """
    optimizer = PortfolioOptimizer()
    weights = optimizer.calculate_target_weights(
        SIGNALS_5, [], 1_000_000.0,
        scheme=WeightingScheme.RISK_ADJUSTED,
        volatilities=VOLS_5,
    )
    assert weights["C"] > weights["A"]


def test_signal_proportional_default():
    """Default scheme remains signal-proportional (legacy behaviour)."""
    optimizer = PortfolioOptimizer()
    weights_default = optimizer.calculate_target_weights(SIGNALS_5, [], 1_000_000.0)
    weights_explicit = optimizer.calculate_target_weights(
        SIGNALS_5, [], 1_000_000.0,
        scheme=WeightingScheme.SIGNAL_PROPORTIONAL,
    )
    assert weights_default == weights_explicit
    # A has highest signal → largest weight
    assert weights_default["A"] > weights_default["E"]


def test_inverse_volatility_floor():
    """Vol floor (0.5%) prevents division blow-up for halted/zero-vol stocks."""
    optimizer = PortfolioOptimizer()
    # Use 5 stocks so the cap doesn't bind
    weights = optimizer.calculate_target_weights(
        {"A": 0.5, "B": 0.5, "C": 0.5, "D": 0.5, "E": 0.5}, [], 1_000_000.0,
        scheme=WeightingScheme.INVERSE_VOLATILITY,
        volatilities={"A": 0.0, "B": 0.02, "C": 0.02, "D": 0.02, "E": 0.02},
    )
    assert all(0 < w < 1 for w in weights.values())
    # A (floored to 0.005) gets bigger inverse-vol score (200) vs others (50)
    assert weights["A"] > weights["B"]


def test_portfolio_optimizer_initialization():
    """Test optimizer initializes with default constraints."""
    optimizer = PortfolioOptimizer()
    
    assert optimizer.constraints.max_single_stock_weight == 0.30
    assert optimizer.constraints.max_industry_weight == 0.40


def test_calculate_target_weights():
    """Test target weight calculation."""
    optimizer = PortfolioOptimizer()
    
    signals = {
        "600519.SH": 0.8,
        "000001.SZ": 0.5,
        "300750.SZ": 0.6,
    }
    
    positions = []
    total_value = 1_000_000.0
    
    weights = optimizer.calculate_target_weights(signals, positions, total_value)
    
    assert len(weights) == 3
    # Each weight should be positive and total should be less than 1 (reserve cash)
    assert all(w > 0 for w in weights.values())
    assert sum(weights.values()) < 1.0


def test_calculate_target_weights_with_cap():
    """Test weight calculation with constraints."""
    optimizer = PortfolioOptimizer()
    
    # Multiple signals
    signals = {
        "600519.SH": 0.9,
        "000001.SZ": 0.1,
        "300750.SZ": 0.5,
    }
    
    positions = []
    total_value = 1_000_000.0
    
    weights = optimizer.calculate_target_weights(signals, positions, total_value)
    
    # Should have weights for all symbols
    assert len(weights) == 3
    # Total should reserve cash
    assert sum(weights.values()) < 1.0
    # All should be positive
    assert all(w > 0 for w in weights.values())


def test_generate_rebalance_actions():
    """Test rebalancing action generation."""
    optimizer = PortfolioOptimizer()
    
    target_weights = {
        "600519.SH": 0.25,
        "000001.SZ": 0.15,
    }
    
    current_positions = [
        Position(
            position_id="pos1",
            account_id="acc1",
            symbol="600519.SH",
            quantity=100,
            available_quantity=100,
            avg_cost=1600.0,
            market_value=170_000.0,
            unrealized_pnl=10_000.0,
            realized_pnl=0.0,
            updated_at=None,
        )
    ]
    
    total_value = 1_000_000.0
    current_prices = {
        "600519.SH": 1700.0,
        "000001.SZ": 11.0,
    }
    
    actions = optimizer.generate_rebalance_actions(
        target_weights, current_positions, total_value, current_prices
    )
    
    assert len(actions) > 0
    assert any(a.symbol == "000001.SZ" and a.action == "BUY" for a in actions)


def test_optimize_with_warnings():
    """Test optimization with constraint violations."""
    constraints = PortfolioConstraints(
        max_turnover=0.10,  # Very low turnover limit
    )
    optimizer = PortfolioOptimizer(constraints)
    
    signals = {
        "600519.SH": 0.8,
        "000001.SZ": 0.7,
        "300750.SZ": 0.6,
    }
    
    current_positions = []
    total_value = 1_000_000.0
    current_prices = {
        "600519.SH": 1700.0,
        "000001.SZ": 11.0,
        "300750.SZ": 230.0,
    }
    
    result = optimizer.optimize(
        signals, current_positions, total_value, current_prices
    )
    
    # Should have warnings about high turnover
    assert len(result.warnings) > 0
    assert any("换手率" in w for w in result.warnings)
