"""Tests for MarketAnalyst + PortfolioManager agents (§6.4)."""

from __future__ import annotations

from libs.llm_analyst.agents import (
    AnalystView,
    MarketAnalyst,
    PortfolioManager,
)
from libs.llm_analyst.llm_client import LLMClient


def _client() -> LLMClient:
    # Default config reads QUANT_LLM_PROVIDER env (defaults to "keyword")
    return LLMClient()


def test_market_analyst_detects_risk_on() -> None:
    bars = [100.0, 101.0, 102.5, 103.0, 104.5, 106.0]  # +6%, low vol
    rep = MarketAnalyst(_client()).analyze("600519.SH", bars)
    assert rep.view == AnalystView.BULLISH
    assert rep.data_used["regime"] == "risk_on"
    assert rep.data_used["regime_adjustment"] > 0


def test_market_analyst_detects_risk_off() -> None:
    bars = [100.0, 98.0, 95.0, 92.0, 90.0]  # -10%
    rep = MarketAnalyst(_client()).analyze("600519.SH", bars)
    assert rep.view == AnalystView.BEARISH
    assert rep.data_used["regime"] == "risk_off"
    assert rep.data_used["regime_adjustment"] < 0


def test_market_analyst_insufficient_data() -> None:
    rep = MarketAnalyst(_client()).analyze("600519.SH", [100, 101])
    assert rep.view == AnalystView.NEUTRAL
    assert rep.confidence < 0.5


def test_portfolio_manager_blocks_overweight_buy() -> None:
    positions = [{"symbol": "600519.SH", "market_value": 400_000, "quantity": 200}]
    rep = PortfolioManager(_client()).analyze(
        "600519.SH", positions, portfolio_total_value=1_000_000, cash=100_000,
        proposed_action="BUY",
    )
    assert rep.view == AnalystView.BEARISH
    assert "OVERWEIGHT_POSITION" in rep.risk_flags


def test_portfolio_manager_endorses_new_position() -> None:
    rep = PortfolioManager(_client()).analyze(
        "300750.SZ", [], portfolio_total_value=1_000_000, cash=500_000,
        proposed_action="BUY",
    )
    assert rep.view == AnalystView.BULLISH


def test_portfolio_manager_endorses_sell_when_overweight() -> None:
    positions = [{"symbol": "600519.SH", "market_value": 400_000, "quantity": 200}]
    rep = PortfolioManager(_client()).analyze(
        "600519.SH", positions, portfolio_total_value=1_000_000, cash=200_000,
        proposed_action="SELL",
    )
    # bullish on the SELL action == endorsing the rebalance
    assert rep.view == AnalystView.BULLISH


def test_portfolio_manager_low_cash_warning() -> None:
    rep = PortfolioManager(_client()).analyze(
        "300750.SZ", [{"symbol": "X", "market_value": 990_000, "quantity": 100}],
        portfolio_total_value=1_000_000, cash=10_000,
        proposed_action="BUY",
    )
    assert "LOW_CASH" in rep.risk_flags
