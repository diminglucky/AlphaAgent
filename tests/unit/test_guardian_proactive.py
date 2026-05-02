"""Tests for PortfolioGuardian's PROACTIVE risk-avoidance logic.

Specifically validates that the agent fires WATCH/REDUCE *before* losses
materialize — exercising the new severity-priority ladder added when the
user demanded predictive (not reactive) risk management.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from libs.agents.portfolio_guardian import PortfolioGuardianAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_obs(overview: dict):
    """Mimic a tool result object with .output / .error attributes."""
    return SimpleNamespace(output=overview, error=None)


def _patched_registry(*, health: dict, pattern: dict, news: dict | None = None):
    """Patch get_default_registry().execute so each per-symbol call returns
    canned data, allowing us to test the verdict ladder in isolation.
    """
    news = news or {"avg_sentiment": 0, "negative_events_count": 0}

    def _execute(call, context=None):
        if call.name == "check_position_health":
            return SimpleNamespace(output=dict(health), error=None)
        if call.name == "detect_chart_pattern":
            return SimpleNamespace(output=dict(pattern), error=None)
        if call.name == "analyze_news_sentiment":
            return SimpleNamespace(output=dict(news), error=None)
        return SimpleNamespace(output={}, error=None)

    return _execute


def _verdict_for(*, health: dict, pattern: dict, news: dict | None = None) -> dict:
    """Run only the fallback summarizer with canned per-symbol observations."""
    agent = PortfolioGuardianAgent()
    overview = {
        "positions": [{"symbol": "TEST.SH"}],
        "summary": {},
        "n_holdings": 1,
    }
    obs = [_make_obs(overview)]

    with patch("libs.agents.skills.get_default_registry") as mock_reg:
        mock_reg.return_value.execute = _patched_registry(
            health=health, pattern=pattern, news=news
        )
        result = agent._summarize_observations("test", obs)
    return result["verdicts"][0]


# ---------------------------------------------------------------------------
# Reactive baseline (existing rules — unchanged)
# ---------------------------------------------------------------------------

def test_hard_stop_loss_at_minus_8pct_yields_sell_all():
    v = _verdict_for(
        health={"pnl_pct": -0.09, "drawdown_from_peak": -0.09},
        pattern={"patterns": []},
    )
    assert v["action"] == "SELL_ALL"
    assert any("止损" in r for r in v["reasons"])


def test_confirmed_death_cross_yields_reduce():
    v = _verdict_for(
        health={"pnl_pct": -0.02, "drawdown_from_peak": -0.03},
        pattern={"patterns": [{"name": "death_cross", "desc": "死叉"}]},
    )
    assert v["action"] == "REDUCE_HALF"
    assert any("死叉" in r for r in v["reasons"])


# ---------------------------------------------------------------------------
# A. PREDICTIVE WARNINGS (fire BEFORE the loss)
# ---------------------------------------------------------------------------

def test_single_warning_no_profit_yields_watch():
    """One warning + no meaningful profit → WATCH (don't act, just alert)."""
    v = _verdict_for(
        health={"pnl_pct": 0.02, "drawdown_from_peak": -0.01},
        pattern={"patterns": [
            {"name": "rsi_bearish_divergence", "desc": "RSI 顶背离", "severity": "warning"},
        ]},
    )
    assert v["action"] == "WATCH"
    assert "rsi_bearish_divergence" in v["warning_patterns"]


def test_two_concurrent_warnings_yields_reduce():
    """Two simultaneous warnings → REDUCE preemptively (high conviction top)."""
    v = _verdict_for(
        health={"pnl_pct": 0.05, "drawdown_from_peak": -0.01},
        pattern={"patterns": [
            {"name": "rsi_bearish_divergence", "severity": "warning", "desc": "x"},
            {"name": "macd_weakening", "severity": "warning", "desc": "y"},
        ]},
    )
    assert v["action"] == "REDUCE_HALF"
    assert "提前减仓" in v["reasons"][0] or "顶部信号" in v["reasons"][0]


def test_warning_plus_meaningful_profit_yields_reduce_to_lock_gains():
    """Single warning + 10%+ profit → lock half, don't ride it back down."""
    v = _verdict_for(
        health={"pnl_pct": 0.12, "drawdown_from_peak": -0.02},
        pattern={"patterns": [
            {"name": "volume_price_divergence", "severity": "warning", "desc": "z"},
        ]},
    )
    assert v["action"] == "REDUCE_HALF"
    assert any("浮盈" in r and "落袋" in r for r in v["reasons"])


# ---------------------------------------------------------------------------
# B. PROFIT PROTECTION (don't give back what you earned)
# ---------------------------------------------------------------------------

def test_trailing_stop_after_15pct_profit_with_5pct_drawdown():
    """+15% gain followed by -5% pullback from peak → REDUCE."""
    v = _verdict_for(
        health={"pnl_pct": 0.15, "drawdown_from_peak": -0.05},
        pattern={"patterns": []},
    )
    assert v["action"] == "REDUCE_HALF"
    assert any("trailing" in r.lower() or "回撤" in r for r in v["reasons"])


def test_take_profit_at_25pct_gain():
    v = _verdict_for(
        health={"pnl_pct": 0.30, "drawdown_from_peak": -0.01},
        pattern={"patterns": []},
    )
    assert v["action"] == "REDUCE_HALF"
    assert any("止盈" in r or "+25" in r for r in v["reasons"])


def test_approaching_resistance_with_profit_yields_reduce():
    v = _verdict_for(
        health={"pnl_pct": 0.12, "drawdown_from_peak": -0.01},
        pattern={"patterns": [{"name": "approaching_resistance", "desc": "near R"}]},
    )
    # Note: approaching_resistance has severity "warning" too in real output, so
    # this can be triggered via either the warning path OR the explicit B8 rule.
    assert v["action"] == "REDUCE_HALF"


# ---------------------------------------------------------------------------
# Healthy holdings stay HOLD
# ---------------------------------------------------------------------------

def test_healthy_position_stays_hold():
    v = _verdict_for(
        health={"pnl_pct": 0.04, "drawdown_from_peak": -0.01},
        pattern={"patterns": []},
    )
    assert v["action"] == "HOLD"
    assert v["reasons"] == ["持仓健康，继续持有"]


def test_small_drawdown_no_warnings_stays_hold():
    v = _verdict_for(
        health={"pnl_pct": -0.03, "drawdown_from_peak": -0.04},
        pattern={"patterns": []},
    )
    assert v["action"] == "HOLD"


# ---------------------------------------------------------------------------
# Severity ladder — highest priority wins
# ---------------------------------------------------------------------------

def test_sell_all_overrides_reduce_signals():
    """If both -8% loss AND warnings present, SELL beats REDUCE."""
    v = _verdict_for(
        health={"pnl_pct": -0.10, "drawdown_from_peak": -0.10},
        pattern={"patterns": [
            {"name": "rsi_bearish_divergence", "severity": "warning", "desc": "x"},
            {"name": "macd_weakening", "severity": "warning", "desc": "y"},
        ]},
    )
    assert v["action"] == "SELL_ALL"


def test_reduce_overrides_watch():
    """REDUCE rule (e.g. take-profit) beats a single WATCH-level warning."""
    v = _verdict_for(
        health={"pnl_pct": 0.30, "drawdown_from_peak": -0.01},
        pattern={"patterns": [
            {"name": "rsi_bearish_divergence", "severity": "warning", "desc": "x"},
        ]},
    )
    assert v["action"] == "REDUCE_HALF"


# ---------------------------------------------------------------------------
# Summary aggregation
# ---------------------------------------------------------------------------

def test_summary_breakdown_by_action_level():
    agent = PortfolioGuardianAgent()
    overview = {
        "positions": [
            {"symbol": "A.SH"}, {"symbol": "B.SZ"}, {"symbol": "C.SH"},
        ],
    }
    obs = [_make_obs(overview)]

    def _exec(call, context=None):
        sym = call.arguments.get("symbol")
        if call.name == "check_position_health":
            return SimpleNamespace(output={
                "A.SH": {"pnl_pct": -0.10, "drawdown_from_peak": -0.10},
                "B.SZ": {"pnl_pct": 0.05, "drawdown_from_peak": -0.01},
                "C.SH": {"pnl_pct": 0.30, "drawdown_from_peak": -0.01},
            }[sym], error=None)
        if call.name == "detect_chart_pattern":
            return SimpleNamespace(output={
                "A.SH": {"patterns": []},
                "B.SZ": {"patterns": [
                    {"name": "rsi_bearish_divergence", "severity": "warning", "desc": "x"}
                ]},
                "C.SH": {"patterns": []},
            }[sym], error=None)
        if call.name == "analyze_news_sentiment":
            return SimpleNamespace(output={"avg_sentiment": 0, "negative_events_count": 0}, error=None)
        return SimpleNamespace(output={}, error=None)

    with patch("libs.agents.skills.get_default_registry") as mock_reg:
        mock_reg.return_value.execute = _exec
        result = agent._summarize_observations("test", obs)

    assert result["sell_count"] == 1   # A.SH -10%
    assert result["watch_count"] == 1  # B.SZ single warning
    assert result["reduce_count"] == 1 # C.SH +30%
    assert "SELL" in result["summary"]
    assert "WATCH" in result["summary"]
    assert "REDUCE" in result["summary"]
