"""Backtest endpoints (§4.3.2 research-lab, §9.3 Phase 2)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.app.db.repositories import ModelRunRepository
from apps.api.app.db.session import get_db
from apps.api.app.services.market_service import MarketService
from libs.research.backtest import Backtest, BacktestConfig
from libs.research.walk_forward import WalkForwardConfig, WalkForwardValidator

router = APIRouter(prefix="/backtest", tags=["backtest"])


class BacktestRequest(BaseModel):
    symbols: list[str] = Field(..., description="Stock symbols to backtest")
    strategy: str = Field("ma_crossover", description="Strategy id: ma_crossover | rsi_reversion | buy_hold")
    initial_capital: float = 1_000_000.0
    stop_loss_pct: Optional[float] = 0.08
    take_profit_pct: Optional[float] = 0.20


def _strategy_factory(name: str):
    """Return a strategy callable that maps date+bars → [(symbol, action)]."""
    state: dict[str, dict] = {}

    if name == "buy_hold":
        bought: set[str] = set()

        def f(d: date, current_data: dict):
            actions = []
            for sym in current_data:
                if sym not in bought:
                    actions.append((sym, "BUY"))
                    bought.add(sym)
            return actions
        return f

    if name == "rsi_reversion":
        history: dict[str, list[float]] = {}

        def rsi(prices: list[float], period: int = 14) -> Optional[float]:
            if len(prices) < period + 1:
                return None
            gains, losses = [], []
            for i in range(1, len(prices)):
                ch = prices[i] - prices[i - 1]
                gains.append(max(0, ch))
                losses.append(max(0, -ch))
            avg_g = sum(gains[-period:]) / period
            avg_l = sum(losses[-period:]) / period
            if avg_l == 0:
                return 100.0
            rs = avg_g / avg_l
            return 100 - 100 / (1 + rs)

        def f(d: date, current_data: dict):
            actions = []
            for sym, bar in current_data.items():
                history.setdefault(sym, []).append(bar.close)
                r = rsi(history[sym])
                if r is None:
                    continue
                if r < 30:
                    actions.append((sym, "BUY"))
                elif r > 70:
                    actions.append((sym, "SELL"))
            return actions
        return f

    # Default: simple short/long MA crossover
    history: dict[str, list[float]] = {}

    def f(d: date, current_data: dict):
        actions = []
        for sym, bar in current_data.items():
            hist = history.setdefault(sym, [])
            hist.append(bar.close)
            if len(hist) < 21:
                continue
            short_ma = sum(hist[-5:]) / 5
            long_ma = sum(hist[-20:]) / 20
            prev_short = sum(hist[-6:-1]) / 5
            prev_long = sum(hist[-21:-1]) / 20
            if prev_short <= prev_long and short_ma > long_ma:
                actions.append((sym, "BUY"))
            elif prev_short >= prev_long and short_ma < long_ma:
                actions.append((sym, "SELL"))
        return actions
    return f


@router.post("/run")
def run_backtest(req: BacktestRequest = Body(...), db: Session = Depends(get_db)):
    """Run a backtest against stored bars and return metrics + equity curve."""
    import json as _json
    import uuid as _uuid
    started = datetime.now()
    market = MarketService()
    data = {}
    for sym in req.symbols:
        try:
            bars = market.get_bars(symbol=sym, freq="1d")
            if bars:
                data[sym] = bars
        except Exception:
            continue
    if not data:
        return {"ok": False, "error": "No bars available for any symbol", "symbols": req.symbols}

    config = BacktestConfig(
        initial_capital=req.initial_capital,
        stop_loss_pct=req.stop_loss_pct,
        take_profit_pct=req.take_profit_pct,
    )
    bt = Backtest(config)
    metrics = bt.run(data, _strategy_factory(req.strategy))

    # Persist model run (Design Doc §5.3.9 traceability)
    try:
        run_id = f"bt-{_uuid.uuid4().hex[:12]}"
        ModelRunRepository(db).save(
            run_id=run_id,
            model_name=req.strategy,
            model_version="v1",
            run_type="backtest",
            started_at=started,
            finished_at=datetime.now(),
            params=_json.dumps({
                "symbols": list(data.keys()),
                "initial_capital": config.initial_capital,
                "stop_loss_pct": config.stop_loss_pct,
                "take_profit_pct": config.take_profit_pct,
            }),
            score_metrics=_json.dumps({
                "total_return": round(metrics.total_return, 4),
                "annual_return": round(metrics.annual_return, 4),
                "sharpe_ratio": round(metrics.sharpe_ratio, 3),
                "max_drawdown": round(metrics.max_drawdown, 4),
                "win_rate": round(metrics.win_rate, 3),
                "total_trades": metrics.total_trades,
            }),
            status="success",
        )
        db.commit()
    except Exception:  # noqa: BLE001 — non-blocking
        db.rollback()

    return {
        "ok": True,
        "strategy": req.strategy,
        "symbols": list(data.keys()),
        "config": {
            "initial_capital": config.initial_capital,
            "stop_loss_pct": config.stop_loss_pct,
            "take_profit_pct": config.take_profit_pct,
        },
        "metrics": {
            "total_return": round(metrics.total_return, 4),
            "annual_return": round(metrics.annual_return, 4),
            "sharpe_ratio": round(metrics.sharpe_ratio, 3),
            "max_drawdown": round(metrics.max_drawdown, 4),
            "win_rate": round(metrics.win_rate, 3),
            "profit_factor": round(metrics.profit_factor, 3),
            "total_trades": metrics.total_trades,
            "winning_trades": metrics.winning_trades,
            "losing_trades": metrics.losing_trades,
            "avg_win": round(metrics.avg_win, 2),
            "avg_loss": round(metrics.avg_loss, 2),
        },
        "equity_curve": [
            {"date": d.isoformat(), "value": round(v, 2)}
            for d, v in bt.equity_curve
        ],
        "trades": [
            {
                "trade_id": t.trade_id,
                "symbol": t.symbol,
                "entry_date": t.entry_date.isoformat() if t.entry_date else None,
                "entry_price": t.entry_price,
                "exit_date": t.exit_date.isoformat() if t.exit_date else None,
                "exit_price": t.exit_price,
                "quantity": t.quantity,
                "pnl": round(t.pnl, 2),
                "pnl_pct": round(t.pnl_pct, 4),
                "reason": t.reason,
            }
            for t in bt.closed_trades
        ],
    }


class WalkForwardRequest(BaseModel):
    symbols: list[str] = Field(..., description="Stock symbols to validate")
    strategy: str = Field(
        "ma_crossover",
        description="Strategy id: ma_crossover | rsi_reversion | buy_hold",
    )
    in_sample_bars: int = Field(
        252, ge=10, description="In-sample window length (trading days)"
    )
    oos_bars: int = Field(
        63, ge=1, description="Out-of-sample window length (trading days)"
    )
    step_bars: int = Field(
        0,
        description="Slide step (0 = non-overlapping, i.e. equal to oos_bars)",
    )
    min_folds: int = Field(2, ge=1, description="Minimum required OOS folds")
    initial_capital: float = 1_000_000.0
    stop_loss_pct: Optional[float] = 0.08
    take_profit_pct: Optional[float] = 0.20


@router.post("/walk-forward")
def run_walk_forward(
    req: WalkForwardRequest = Body(...),
    db: Session = Depends(get_db),
):
    """Walk-forward strategy validation.

    Splits history into rolling in-sample / OOS windows, runs the strategy
    on each OOS fold independently, and returns aggregate robustness metrics
    plus per-fold breakdown.  No look-ahead bias — each fold uses only data
    available at that point in time.
    """
    import json as _json
    import uuid as _uuid

    started = datetime.now()
    market = MarketService()
    data = {}
    for sym in req.symbols:
        try:
            bars = market.get_bars(symbol=sym, freq="1d")
            if bars:
                data[sym] = bars
        except Exception:
            continue

    if not data:
        return {"ok": False, "error": "No bars available for any symbol"}

    wf_config = WalkForwardConfig(
        in_sample_bars=req.in_sample_bars,
        oos_bars=req.oos_bars,
        step_bars=req.step_bars,
        min_folds=req.min_folds,
        backtest_config=BacktestConfig(
            initial_capital=req.initial_capital,
            stop_loss_pct=req.stop_loss_pct,
            take_profit_pct=req.take_profit_pct,
        ),
    )

    try:
        validator = WalkForwardValidator(wf_config)
        result = validator.run(data, lambda: _strategy_factory(req.strategy))
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    # Persist model run
    try:
        run_id = f"wf-{_uuid.uuid4().hex[:12]}"
        ModelRunRepository(db).save(
            run_id=run_id,
            model_name=req.strategy,
            model_version="v1",
            run_type="walk_forward",
            started_at=started,
            finished_at=datetime.now(),
            params=_json.dumps({
                "symbols": list(data.keys()),
                "in_sample_bars": req.in_sample_bars,
                "oos_bars": req.oos_bars,
                "step_bars": wf_config.step_bars,
                "n_folds": result.n_folds,
            }),
            score_metrics=_json.dumps({
                "oos_total_return_mean": round(result.oos_total_return_mean, 4),
                "oos_sharpe_mean": round(result.oos_sharpe_mean, 3),
                "oos_max_drawdown_mean": round(result.oos_max_drawdown_mean, 4),
                "oos_win_rate_mean": round(result.oos_win_rate_mean, 3),
                "pct_profitable_folds": round(result.pct_profitable_folds, 3),
                "consistency_score": round(result.consistency_score, 3),
            }),
            status="success",
        )
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()

    return {
        "ok": True,
        "strategy": req.strategy,
        "symbols": list(data.keys()),
        "n_folds": result.n_folds,
        "aggregate": {
            "oos_total_return_mean": round(result.oos_total_return_mean, 4),
            "oos_sharpe_mean": round(result.oos_sharpe_mean, 3),
            "oos_max_drawdown_mean": round(result.oos_max_drawdown_mean, 4),
            "oos_win_rate_mean": round(result.oos_win_rate_mean, 3),
            "oos_profit_factor_mean": round(result.oos_profit_factor_mean, 3),
            "pct_profitable_folds": round(result.pct_profitable_folds, 3),
            "consistency_score": round(result.consistency_score, 3),
        },
        "folds": [
            {
                "fold": f.fold_idx,
                "in_sample": {
                    "start": f.in_sample_start.isoformat(),
                    "end": f.in_sample_end.isoformat(),
                },
                "oos": {
                    "start": f.oos_start.isoformat(),
                    "end": f.oos_end.isoformat(),
                },
                "metrics": {
                    "total_return": round(f.metrics.total_return, 4),
                    "sharpe_ratio": round(f.metrics.sharpe_ratio, 3),
                    "max_drawdown": round(f.metrics.max_drawdown, 4),
                    "win_rate": round(f.metrics.win_rate, 3),
                    "total_trades": f.metrics.total_trades,
                },
            }
            for f in result.folds
        ],
    }
