"""Tests for portfolio optimizer."""

import pytest

from libs.portfolio.optimizer import (
    PortfolioConstraints,
    PortfolioOptimizer,
    WeightingScheme,
)
from libs.quant_core.models import Position


# Use a wider cap for scheme-differentiation tests so default 15% risk caps
# do not flatten the relative ordering being tested.
SIGNALS_5 = {"A": 0.8, "B": 0.6, "C": 0.5, "D": 0.4, "E": 0.3}
VOLS_5 = {"A": 0.030, "B": 0.020, "C": 0.010, "D": 0.025, "E": 0.015}
SCHEME_TEST_CONSTRAINTS = PortfolioConstraints(max_single_stock_weight=0.50)


def test_equal_weight_scheme():
    optimizer = PortfolioOptimizer(SCHEME_TEST_CONSTRAINTS)
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
    optimizer = PortfolioOptimizer(SCHEME_TEST_CONSTRAINTS)
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
    optimizer = PortfolioOptimizer(SCHEME_TEST_CONSTRAINTS)
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
    optimizer = PortfolioOptimizer(SCHEME_TEST_CONSTRAINTS)
    weights = optimizer.calculate_target_weights(
        SIGNALS_5, [], 1_000_000.0,
        scheme=WeightingScheme.RISK_ADJUSTED,
        volatilities=VOLS_5,
    )
    assert weights["C"] > weights["A"]


def test_signal_proportional_default():
    """Default scheme remains signal-proportional (legacy behaviour)."""
    optimizer = PortfolioOptimizer(SCHEME_TEST_CONSTRAINTS)
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
    optimizer = PortfolioOptimizer(SCHEME_TEST_CONSTRAINTS)
    # Use a wide cap so the cap doesn't hide the inverse-vol ordering.
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
    
    assert optimizer.constraints.max_single_stock_weight == 0.15
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


def test_calculate_target_weights_respects_single_stock_cap():
    """A dominant signal should still be capped at the configured max weight."""
    optimizer = PortfolioOptimizer()

    weights = optimizer.calculate_target_weights(
        {"600519.SH": 1.0},
        [],
        1_000_000.0,
    )

    assert weights["600519.SH"] == pytest.approx(0.15)


def test_calculate_target_weights_respects_max_positions():
    """Optimizer should not emit more target positions than the configured cap."""
    optimizer = PortfolioOptimizer(PortfolioConstraints(max_positions=2))

    weights = optimizer.calculate_target_weights(
        {
            "A": 0.8,
            "B": 0.7,
            "C": 0.6,
            "D": 0.5,
        },
        [],
        1_000_000.0,
    )

    assert set(weights) == {"A", "B"}
    assert len(weights) == 2


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


def test_optimize_warns_when_candidates_exceed_max_positions():
    """The warning should explain why lower-ranked signals were removed."""
    optimizer = PortfolioOptimizer(PortfolioConstraints(max_positions=2))

    result = optimizer.optimize(
        {"A": 0.8, "B": 0.7, "C": 0.6},
        [],
        1_000_000.0,
        {"A": 10.0, "B": 10.0, "C": 10.0},
    )

    assert result.risk_metrics["num_positions"] == 2
    assert any("最大持仓数2" in warning for warning in result.warnings)
