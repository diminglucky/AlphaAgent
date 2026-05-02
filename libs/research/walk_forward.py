"""Walk-forward validation for trading strategies.

Walk-forward testing divides the full history into rolling windows:

  |←── in-sample (train) ──→|←─ OOS (test) ─→|
                         |←── in-sample ──→|←─ OOS ─→|
                                         |←── in-sample ──→|← OOS →|

Each OOS (out-of-sample) fold is run independently with a freshly
re-initialised strategy, eliminating look-ahead bias.  Aggregate
metrics across all OOS folds give a realistic picture of live performance.

Public API
----------
>>> validator = WalkForwardValidator(config)
>>> result    = validator.run(data, strategy_factory)
>>> print(result.oos_sharpe_mean, result.oos_max_drawdown_mean)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Optional

from libs.quant_core.models import MarketBar
from libs.research.backtest import Backtest, BacktestConfig, BacktestMetrics


@dataclass(frozen=True)
class WalkForwardConfig:
    """Parameters controlling the rolling-window schedule.

    Attributes
    ----------
    in_sample_bars:
        Number of trading days in each in-sample (training) window.
    oos_bars:
        Number of trading days in each out-of-sample (test) window.
    step_bars:
        How many days to advance before the next fold.  Defaults to
        ``oos_bars`` (non-overlapping OOS); set smaller for anchored /
        expanding windows.
    min_folds:
        Minimum number of complete OOS folds required; raises ``ValueError``
        if there is not enough data.
    backtest_config:
        Config forwarded to each :class:`~libs.research.backtest.Backtest`
        instance.
    """
    in_sample_bars: int = 252          # ~1 trading year
    oos_bars: int = 63                 # ~1 quarter
    step_bars: int = 0                 # 0 → equal to oos_bars (rolling)
    min_folds: int = 2
    backtest_config: BacktestConfig = field(default_factory=BacktestConfig)

    def __post_init__(self) -> None:
        if self.in_sample_bars < 10:
            raise ValueError("in_sample_bars must be ≥ 10")
        if self.oos_bars < 1:
            raise ValueError("oos_bars must be ≥ 1")
        object.__setattr__(
            self, "step_bars",
            self.oos_bars if self.step_bars <= 0 else self.step_bars,
        )


@dataclass
class WalkForwardFold:
    """Results for a single OOS fold."""
    fold_idx: int
    in_sample_start: date
    in_sample_end: date
    oos_start: date
    oos_end: date
    metrics: BacktestMetrics


@dataclass
class WalkForwardResult:
    """Aggregated walk-forward results across all OOS folds.

    Attributes
    ----------
    folds:
        Per-fold detail (in-sample window + OOS metrics).
    n_folds:
        Number of completed OOS folds.
    oos_total_return_mean:
        Mean per-fold OOS total return.
    oos_sharpe_mean:
        Mean per-fold OOS Sharpe ratio.
    oos_max_drawdown_mean:
        Mean per-fold OOS max drawdown.
    oos_win_rate_mean:
        Mean per-fold OOS trade win-rate.
    oos_profit_factor_mean:
        Mean per-fold OOS profit factor.
    pct_profitable_folds:
        Fraction of OOS folds with positive total return (robustness score).
    consistency_score:
        ``pct_profitable_folds * clip(oos_sharpe_mean, 0, 3) / 3``
        — a single [0, 1] number summarising strategy robustness.
    """
    folds: list[WalkForwardFold]
    n_folds: int
    oos_total_return_mean: float
    oos_sharpe_mean: float
    oos_max_drawdown_mean: float
    oos_win_rate_mean: float
    oos_profit_factor_mean: float
    pct_profitable_folds: float
    consistency_score: float


# Strategy factory type: called once per fold; returns a strategy callable.
StrategyFactory = Callable[[], Callable[[date, dict], list[tuple[str, str]]]]


class WalkForwardValidator:
    """Run walk-forward validation over historical bar data.

    Parameters
    ----------
    config:
        Window sizes and backtest parameters.
    """

    def __init__(self, config: Optional[WalkForwardConfig] = None) -> None:
        self.config = config or WalkForwardConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        data: dict[str, list[MarketBar]],
        strategy_factory: StrategyFactory,
    ) -> WalkForwardResult:
        """Run walk-forward validation.

        Parameters
        ----------
        data:
            Full history as ``{symbol: [MarketBar, ...]}`` (oldest first).
        strategy_factory:
            Callable that returns a *fresh* strategy function each time it is
            called.  The strategy function has signature
            ``(date, dict[str, MarketBar]) -> list[(symbol, action)]``.

        Returns
        -------
        WalkForwardResult
        """
        all_dates = sorted(
            {bar.trade_date for bars in data.values() for bar in bars}
        )
        n_dates = len(all_dates)

        cfg = self.config
        total_needed = cfg.in_sample_bars + cfg.oos_bars
        if n_dates < total_needed:
            raise ValueError(
                f"Not enough data: need ≥{total_needed} trading days, "
                f"got {n_dates}."
            )

        # Build fold windows
        folds: list[WalkForwardFold] = []
        fold_idx = 0
        start = 0

        while start + total_needed <= n_dates:
            is_dates = all_dates[start: start + cfg.in_sample_bars]
            oos_dates = all_dates[
                start + cfg.in_sample_bars: start + cfg.in_sample_bars + cfg.oos_bars
            ]
            if not oos_dates:
                break

            is_set = {d for d in is_dates}
            oos_set = {d for d in oos_dates}

            is_data = _filter_bars(data, is_set)
            oos_data = _filter_bars(data, oos_set)

            if not is_data or not oos_data:
                start += cfg.step_bars
                continue

            # Run OOS backtest with fresh strategy
            bt = Backtest(cfg.backtest_config)
            strategy = strategy_factory()
            metrics = bt.run(oos_data, strategy)

            folds.append(WalkForwardFold(
                fold_idx=fold_idx,
                in_sample_start=is_dates[0],
                in_sample_end=is_dates[-1],
                oos_start=oos_dates[0],
                oos_end=oos_dates[-1],
                metrics=metrics,
            ))

            fold_idx += 1
            start += cfg.step_bars

        if len(folds) < cfg.min_folds:
            raise ValueError(
                f"Only {len(folds)} OOS fold(s) completed; "
                f"need ≥{cfg.min_folds}.  Reduce min_folds or supply more data."
            )

        return self._aggregate(folds)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _aggregate(folds: list[WalkForwardFold]) -> WalkForwardResult:
        n = len(folds)
        metrics_list = [f.metrics for f in folds]

        def mean(vals: list[float]) -> float:
            return sum(vals) / len(vals) if vals else 0.0

        tr_mean = mean([m.total_return for m in metrics_list])
        sh_mean = mean([m.sharpe_ratio for m in metrics_list])
        dd_mean = mean([m.max_drawdown for m in metrics_list])
        wr_mean = mean([m.win_rate for m in metrics_list])
        pf_mean = mean([m.profit_factor for m in metrics_list])

        pct_profit = sum(
            1 for m in metrics_list if m.total_return > 0
        ) / n

        # Consistency: fraction of profitable folds × normalised Sharpe
        capped_sharpe = min(max(sh_mean, 0.0), 3.0) / 3.0
        consistency = pct_profit * capped_sharpe

        return WalkForwardResult(
            folds=folds,
            n_folds=n,
            oos_total_return_mean=tr_mean,
            oos_sharpe_mean=sh_mean,
            oos_max_drawdown_mean=dd_mean,
            oos_win_rate_mean=wr_mean,
            oos_profit_factor_mean=pf_mean,
            pct_profitable_folds=pct_profit,
            consistency_score=consistency,
        )


def _filter_bars(
    data: dict[str, list[MarketBar]],
    date_set: set[date],
) -> dict[str, list[MarketBar]]:
    """Return a sub-dict keeping only bars whose trade_date is in *date_set*."""
    filtered = {}
    for symbol, bars in data.items():
        subset = [b for b in bars if b.trade_date in date_set]
        if subset:
            filtered[symbol] = subset
    return filtered
