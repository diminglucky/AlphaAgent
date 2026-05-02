"""Regression baseline test — backtest must produce identical metrics
for a fixed deterministic dataset.

Approach:
- Build synthetic OHLCV using a fixed RNG seed (no external deps).
- Run buy_hold and ma_crossover strategies via libs.research.backtest.
- Compare metrics against a frozen golden file in tests/regression/golden/.
- If the golden file is missing, generate it (acts as an audit trail).
- Tolerance is strict (1e-6 relative) to catch silent algorithm changes.

Update the golden file intentionally with:
    QUANT_REGEN_GOLDEN=1 pytest tests/regression -k baseline
"""

from __future__ import annotations

import json
import math
import os
import random
from datetime import date, timedelta
from pathlib import Path

import pytest

from libs.quant_core.models import MarketBar
from libs.research.backtest import Backtest, BacktestConfig

GOLDEN = Path(__file__).parent / "golden" / "backtest_baseline.json"
TOL = 1e-6


def _make_bars(symbol: str, n: int, seed: int) -> list[MarketBar]:
    rnd = random.Random(seed)
    base = 100.0
    bars: list[MarketBar] = []
    d = date(2024, 1, 2)
    for i in range(n):
        # geometric random walk with mild drift
        drift = 0.0005
        shock = rnd.gauss(0, 0.012)
        base = max(1.0, base * (1 + drift + shock))
        o = base * (1 + rnd.gauss(0, 0.002))
        h = max(o, base) * (1 + abs(rnd.gauss(0, 0.004)))
        l = min(o, base) * (1 - abs(rnd.gauss(0, 0.004)))
        c = base
        vol = int(1_000_000 * (1 + abs(rnd.gauss(0, 0.5))))
        bars.append(MarketBar(
            symbol=symbol, trade_date=d, open=round(o, 3), high=round(h, 3),
            low=round(l, 3), close=round(c, 3), volume=vol,
            amount=float(vol) * c, turnover_rate=0.01, adj_type="qfq",
            data_source="regression",
        ))
        d += timedelta(days=1)
        # skip weekends roughly
        if d.weekday() >= 5:
            d += timedelta(days=2)
    return bars


def _buy_hold(symbols: list[str]):
    bought = {s: False for s in symbols}

    def f(trade_date, daily):
        actions = []
        for s in symbols:
            if not bought[s] and s in daily:
                actions.append((s, "BUY"))
                bought[s] = True
        return actions
    return f


def _ma_cross(symbols: list[str], short: int = 5, long: int = 20):
    history: dict[str, list[float]] = {s: [] for s in symbols}

    def f(trade_date, daily):
        actions = []
        for s, bar in daily.items():
            history[s].append(bar.close)
            h = history[s]
            if len(h) < long + 1:
                continue
            short_now = sum(h[-short:]) / short
            long_now = sum(h[-long:]) / long
            short_prev = sum(h[-short - 1:-1]) / short
            long_prev = sum(h[-long - 1:-1]) / long
            if short_prev <= long_prev and short_now > long_now:
                actions.append((s, "BUY"))
            elif short_prev >= long_prev and short_now < long_now:
                actions.append((s, "SELL"))
        return actions
    return f


def _run_scenarios() -> dict:
    """Return all metrics for all baseline scenarios."""
    symbols = ["TEST.A", "TEST.B"]
    data = {symbols[0]: _make_bars(symbols[0], 250, seed=42),
            symbols[1]: _make_bars(symbols[1], 250, seed=123)}
    cfg = BacktestConfig(initial_capital=1_000_000.0)

    out: dict[str, dict] = {}
    for name, fac in [
        ("buy_hold", _buy_hold(symbols)),
        ("ma_cross", _ma_cross(symbols)),
    ]:
        bt = Backtest(cfg)
        m = bt.run(data, fac)
        out[name] = {
            "total_return": m.total_return,
            "annual_return": m.annual_return,
            "sharpe_ratio": m.sharpe_ratio,
            "max_drawdown": m.max_drawdown,
            "win_rate": m.win_rate,
            "profit_factor": m.profit_factor,
            "total_trades": m.total_trades,
            "winning_trades": m.winning_trades,
            "losing_trades": m.losing_trades,
        }
    return out


def _close(a: float, b: float, tol: float = TOL) -> bool:
    if a == b:
        return True
    if math.isnan(a) and math.isnan(b):
        return True
    if math.isinf(a) or math.isinf(b):
        return a == b
    denom = max(abs(a), abs(b), 1.0)
    return abs(a - b) / denom <= tol


def test_backtest_baseline_metrics():
    actual = _run_scenarios()

    if os.getenv("QUANT_REGEN_GOLDEN") == "1" or not GOLDEN.exists():
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(actual, indent=2, ensure_ascii=False))
        pytest.skip(f"Golden regenerated at {GOLDEN}")

    expected = json.loads(GOLDEN.read_text())
    assert set(actual.keys()) == set(expected.keys()), (
        f"Scenario keys drifted: {set(actual.keys())} vs {set(expected.keys())}"
    )
    drifted: list[str] = []
    for scenario, metrics in actual.items():
        for k, v in metrics.items():
            ev = expected[scenario][k]
            if isinstance(v, int):
                if v != ev:
                    drifted.append(f"{scenario}.{k}: {ev} -> {v}")
            else:
                if not _close(float(v), float(ev)):
                    drifted.append(f"{scenario}.{k}: {ev:.8f} -> {v:.8f}")
    assert not drifted, "Backtest metrics drifted from golden file:\n  " + "\n  ".join(drifted)
