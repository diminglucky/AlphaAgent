"""Unit tests for the walk-forward validator."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from libs.quant_core.models import MarketBar
from libs.research.backtest import BacktestConfig
from libs.research.walk_forward import (
    WalkForwardConfig,
    WalkForwardResult,
    WalkForwardValidator,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_bars(
    symbol: str,
    n: int,
    start: date | None = None,
    price_start: float = 100.0,
    price_step: float = 1.0,
) -> list[MarketBar]:
    """Generate n synthetic daily bars (uptrend by default)."""
    start = start or date(2020, 1, 2)
    bars = []
    day = start
    for i in range(n):
        close = price_start + i * price_step
        bars.append(
            MarketBar(
                symbol=symbol,
                trade_date=day,
                open=close - 0.5,
                high=close + 1.0,
                low=close - 1.0,
                close=close,
                volume=100_000,
                amount=close * 100_000,
                turnover_rate=0.5,
                adj_type="qfq",
                data_source="test",
            )
        )
        day += timedelta(days=1)
    return bars


def _buy_hold_factory():
    """Returns a fresh buy-hold strategy callable."""
    bought: set[str] = set()

    def strategy(d, current_data):
        actions = []
        for sym in current_data:
            if sym not in bought:
                actions.append((sym, "BUY"))
                bought.add(sym)
        return actions

    return strategy


# ---------------------------------------------------------------------------
# WalkForwardConfig validation
# ---------------------------------------------------------------------------

def test_config_defaults():
    cfg = WalkForwardConfig()
    assert cfg.in_sample_bars == 252
    assert cfg.oos_bars == 63
    assert cfg.step_bars == 63   # defaults to oos_bars


def test_config_custom_step():
    cfg = WalkForwardConfig(in_sample_bars=100, oos_bars=20, step_bars=10)
    assert cfg.step_bars == 10


def test_config_invalid_in_sample():
    with pytest.raises(ValueError):
        WalkForwardConfig(in_sample_bars=5)


def test_config_invalid_oos():
    with pytest.raises(ValueError):
        WalkForwardConfig(oos_bars=0)


# ---------------------------------------------------------------------------
# WalkForwardValidator core behaviour
# ---------------------------------------------------------------------------

def test_walk_forward_produces_correct_fold_count():
    # 400 bars: IS=200, OOS=100, step=100 → 2 folds
    data = {"A.SH": _make_bars("A.SH", 400)}
    cfg = WalkForwardConfig(in_sample_bars=200, oos_bars=100, step_bars=100, min_folds=2)
    validator = WalkForwardValidator(cfg)
    result = validator.run(data, _buy_hold_factory)
    assert result.n_folds == 2
    assert len(result.folds) == 2


def test_walk_forward_fold_dates_non_overlapping():
    data = {"A.SH": _make_bars("A.SH", 400)}
    cfg = WalkForwardConfig(in_sample_bars=200, oos_bars=100, step_bars=100, min_folds=2)
    result = WalkForwardValidator(cfg).run(data, _buy_hold_factory)
    fold0, fold1 = result.folds
    # Second fold's OOS starts after first fold's OOS ends
    assert fold1.oos_start > fold0.oos_end


def test_walk_forward_oos_metrics_present():
    data = {"A.SH": _make_bars("A.SH", 400)}
    cfg = WalkForwardConfig(in_sample_bars=200, oos_bars=100, step_bars=100, min_folds=2)
    result = WalkForwardValidator(cfg).run(data, _buy_hold_factory)
    for fold in result.folds:
        assert fold.metrics is not None
        assert fold.metrics.total_trades >= 0


def test_walk_forward_aggregate_fields_populated():
    data = {"A.SH": _make_bars("A.SH", 400)}
    cfg = WalkForwardConfig(in_sample_bars=200, oos_bars=100, step_bars=100, min_folds=2)
    result = WalkForwardValidator(cfg).run(data, _buy_hold_factory)
    assert isinstance(result.oos_sharpe_mean, float)
    assert isinstance(result.oos_max_drawdown_mean, float)
    assert 0.0 <= result.pct_profitable_folds <= 1.0
    assert 0.0 <= result.consistency_score <= 1.0


def test_walk_forward_insufficient_data_raises():
    data = {"A.SH": _make_bars("A.SH", 50)}
    cfg = WalkForwardConfig(in_sample_bars=100, oos_bars=50, min_folds=1)
    with pytest.raises(ValueError, match="Not enough data"):
        WalkForwardValidator(cfg).run(data, _buy_hold_factory)


def test_walk_forward_too_few_folds_raises():
    # 350 bars: IS=200, OOS=100, step=100 → only 1 fold; min_folds=2 should fail
    data = {"A.SH": _make_bars("A.SH", 350)}
    cfg = WalkForwardConfig(in_sample_bars=200, oos_bars=100, step_bars=100, min_folds=2)
    with pytest.raises(ValueError, match="fold"):
        WalkForwardValidator(cfg).run(data, _buy_hold_factory)


def test_walk_forward_uptrend_profitable():
    """Buy-hold on strong uptrend should yield positive OOS returns.

    Price starts at 10 with +0.1/day so at bar 200 it is ~30.
    With capital=1_000_000 and 10% position, quantity = int(100_000/30/100)*100 = 300.
    """
    data = {"A.SH": _make_bars("A.SH", 400, price_start=10.0, price_step=0.1)}
    cfg = WalkForwardConfig(
        in_sample_bars=200, oos_bars=100, step_bars=100, min_folds=2,
        backtest_config=BacktestConfig(initial_capital=1_000_000.0),
    )
    result = WalkForwardValidator(cfg).run(data, _buy_hold_factory)
    assert result.oos_total_return_mean > 0
    assert result.pct_profitable_folds == 1.0


def test_walk_forward_overlapping_oos_folds():
    """step_bars < oos_bars creates overlapping OOS windows → more folds."""
    data = {"A.SH": _make_bars("A.SH", 500)}
    cfg = WalkForwardConfig(
        in_sample_bars=200, oos_bars=100, step_bars=50, min_folds=2,
    )
    result = WalkForwardValidator(cfg).run(data, _buy_hold_factory)
    # step=50, window=200+100: folds start at 0, 50, 100, 150 → 4 folds
    assert result.n_folds >= 3


def test_walk_forward_multi_symbol():
    data = {
        "A.SH": _make_bars("A.SH", 400),
        "B.SZ": _make_bars("B.SZ", 400, price_start=50.0, price_step=0.5),
    }
    cfg = WalkForwardConfig(in_sample_bars=200, oos_bars=100, step_bars=100, min_folds=2)
    result = WalkForwardValidator(cfg).run(data, _buy_hold_factory)
    assert result.n_folds == 2
