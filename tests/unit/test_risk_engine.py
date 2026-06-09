"""Tests for risk engine."""

import pytest

from libs.risk.engine import (
    RiskDecision,
    RiskEngine,
    RiskRule,
    RiskRuleType,
    RiskSeverity,
)


def _base_validate(**kwargs):
    engine = RiskEngine()
    return engine.validate_recommendation(
        symbol="600519.SH",
        action="BUY",
        target_weight=0.12,
        current_weight=0.08,
        industry="白酒",
        industry_weight=0.30,
        **kwargs,
    )


def test_risk_engine_initialization():
    """Test risk engine initializes with default rules."""
    engine = RiskEngine()
    
    assert len(engine.rules) > 0
    assert "single_stock_max_weight" in engine.rules
    assert "industry_max_weight" in engine.rules


def test_single_stock_weight_check_pass():
    """Test single stock weight check passes when within limit."""
    engine = RiskEngine()
    
    result = engine.check_single_stock_weight(
        symbol="600519.SH",
        target_weight=0.12,  # 12%, within 15%
        current_weight=0.08,
    )
    
    assert result.passed is True
    assert result.decision == RiskDecision.ALLOW


def test_single_stock_weight_check_fail():
    """Test single stock weight check fails when exceeding limit."""
    engine = RiskEngine()
    
    result = engine.check_single_stock_weight(
        symbol="600519.SH",
        target_weight=0.18,  # 18%, exceeds 15% limit
        current_weight=0.12,
    )
    
    assert result.passed is False
    assert result.decision == RiskDecision.BLOCK
    assert result.severity == RiskSeverity.ERROR


def test_industry_concentration_check():
    """Test industry concentration check."""
    engine = RiskEngine()
    
    # Pass case
    result = engine.check_industry_concentration(
        industry="白酒",
        target_weight=0.35,  # 35%
    )
    assert result.passed is True
    
    # Fail case
    result = engine.check_industry_concentration(
        industry="白酒",
        target_weight=0.45,  # 45%, exceeds 40% limit
    )
    assert result.passed is False
    assert result.decision == RiskDecision.WARN


def test_validate_recommendation():
    """Test recommendation validation."""
    engine = RiskEngine()
    
    results = engine.validate_recommendation(
        symbol="600519.SH",
        action="BUY",
        target_weight=0.12,
        current_weight=0.08,
        industry="白酒",
        industry_weight=0.35,
    )
    
    assert len(results) == 2  # Single stock + industry checks
    assert all(r.passed for r in results)


def test_get_final_decision():
    """Test final decision aggregation."""
    engine = RiskEngine()
    
    # All pass
    results = engine.validate_recommendation(
        symbol="600519.SH",
        action="BUY",
        target_weight=0.12,
        current_weight=0.08,
        industry="白酒",
        industry_weight=0.30,
    )
    decision = engine.get_final_decision(results)
    assert decision == RiskDecision.ALLOW
    
    # One blocks
    results = engine.validate_recommendation(
        symbol="600519.SH",
        action="BUY",
        target_weight=0.18,  # Exceeds limit
        current_weight=0.12,
        industry="白酒",
        industry_weight=0.30,
    )
    decision = engine.get_final_decision(results)
    assert decision == RiskDecision.BLOCK


def test_add_custom_rule():
    """Test adding custom risk rule."""
    engine = RiskEngine()
    
    custom_rule = RiskRule(
        rule_id="custom_volatility_check",
        rule_type=RiskRuleType.MAX_DRAWDOWN,
        scope="portfolio",
        threshold=0.15,
        action_on_breach=RiskDecision.BLOCK,
        description="Max 15% drawdown allowed",
    )
    
    engine.add_rule(custom_rule)
    
    assert "custom_volatility_check" in engine.rules
    assert engine.rules["custom_volatility_check"].threshold == 0.15


def test_check_stop_loss_pass():
    engine = RiskEngine()
    result = engine.check_position_stop_loss("600519.SH", -0.05)  # -5%, within -8%
    assert result.passed is True
    assert result.decision == RiskDecision.ALLOW


def test_check_stop_loss_breach():
    engine = RiskEngine()
    result = engine.check_position_stop_loss("600519.SH", -0.10)  # -10%, breaches -8%
    assert result.passed is False
    assert result.decision == RiskDecision.BLOCK
    assert result.severity == RiskSeverity.CRITICAL


def test_check_portfolio_drawdown_pass():
    engine = RiskEngine()
    result = engine.check_portfolio_drawdown(-0.10)  # -10%, within -15%
    assert result.passed is True


def test_check_portfolio_drawdown_breach():
    engine = RiskEngine()
    result = engine.check_portfolio_drawdown(-0.20)  # -20%, breaches -15%
    assert result.passed is False
    assert result.decision == RiskDecision.BLOCK


def test_check_volatility_warn():
    engine = RiskEngine()
    result = engine.check_volatility("000001.SZ", 0.05)  # 5% vol, above 4% threshold
    assert result.passed is False
    assert result.decision == RiskDecision.WARN


def test_check_volatility_pass():
    engine = RiskEngine()
    result = engine.check_volatility("000001.SZ", 0.02)  # 2% vol, below 4%
    assert result.passed is True


def test_check_leverage_breach():
    engine = RiskEngine()
    result = engine.check_leverage(1.5)  # 1.5x, above 1.0x limit
    assert result.passed is False
    assert result.decision == RiskDecision.BLOCK


def test_check_leverage_pass():
    engine = RiskEngine()
    result = engine.check_leverage(0.9)  # 0.9x, within 1.0x
    assert result.passed is True


def test_check_daily_turnover_breach():
    engine = RiskEngine()
    result = engine.check_daily_turnover(0.60)  # 60%, above 50% limit
    assert result.passed is False
    assert result.decision == RiskDecision.BLOCK


def test_validate_recommendation_with_drawdown_blocks():
    """Portfolio in deep drawdown should block new BUY."""
    results = _base_validate(portfolio_drawdown=-0.20)
    decision = RiskEngine().get_final_decision(results)
    assert decision == RiskDecision.BLOCK


def test_validate_recommendation_with_stop_loss_blocks():
    """Adding to a -10% position should be blocked."""
    results = _base_validate(position_return=-0.10)
    decision = RiskEngine().get_final_decision(results)
    assert decision == RiskDecision.BLOCK


def test_validate_recommendation_with_high_vol_warns():
    """High volatility should trigger WARN but not BLOCK."""
    results = _base_validate(volatility_20d=0.05)
    decision = RiskEngine().get_final_decision(results)
    assert decision == RiskDecision.WARN


def test_validate_recommendation_healthy_portfolio():
    """All metrics healthy → ALLOW."""
    results = _base_validate(
        portfolio_drawdown=-0.05,
        position_return=-0.02,
        volatility_20d=0.015,
        leverage_ratio=0.90,
        daily_turnover_ratio=0.20,
    )
    decision = RiskEngine().get_final_decision(results)
    assert decision == RiskDecision.ALLOW


def test_default_rule_count():
    """Engine should load 7 default rules."""
    engine = RiskEngine()
    assert len(engine.rules) == 7


def test_remove_rule():
    """Test removing a risk rule."""
    engine = RiskEngine()
    
    initial_count = len(engine.rules)
    engine.remove_rule("single_stock_max_weight")
    
    assert len(engine.rules) == initial_count - 1
    assert "single_stock_max_weight" not in engine.rules
