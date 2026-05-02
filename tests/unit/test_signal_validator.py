"""Tests for signal quality validation (IC, win-rate, long-short spread)."""

import pytest

from libs.recommendations.signal_validator import (
    SignalValidationResult,
    validate_signal_quality,
    _rank,
    _spearman_ic,
    _win_rate,
)


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def test_rank_basic():
    values = [3.0, 1.0, 2.0]
    ranks = _rank(values)
    assert ranks[1] == 1.0  # smallest → rank 1
    assert ranks[2] == 2.0
    assert ranks[0] == 3.0  # largest → rank 3


def test_rank_ties():
    values = [1.0, 1.0, 3.0]
    ranks = _rank(values)
    assert ranks[0] == ranks[1] == 1.5  # tied average
    assert ranks[2] == 3.0


def test_spearman_ic_perfect_positive():
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert abs(_spearman_ic(x, y) - 1.0) < 1e-9


def test_spearman_ic_perfect_negative():
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [5.0, 4.0, 3.0, 2.0, 1.0]
    assert abs(_spearman_ic(x, y) + 1.0) < 1e-9


def test_spearman_ic_insufficient_data():
    assert _spearman_ic([1.0, 2.0], [1.0, 2.0]) is None


def test_win_rate_all_correct():
    signals = [0.5, -0.3, 0.8]
    returns = [0.02, -0.01, 0.03]
    assert _win_rate(signals, returns) == 1.0


def test_win_rate_all_wrong():
    signals = [0.5, 0.3, 0.8]
    returns = [-0.02, -0.01, -0.03]
    assert _win_rate(signals, returns) == 0.0


def test_win_rate_zero_signals_excluded():
    signals = [0.0, 0.5, -0.3]
    returns = [-0.01, 0.02, -0.01]
    # Only non-zero signals counted: (0.5, 0.02) ✓, (-0.3, -0.01) ✓ → 100%
    assert _win_rate(signals, returns) == 1.0


# ---------------------------------------------------------------------------
# validate_signal_quality
# ---------------------------------------------------------------------------

def _make_bullish_signals(n: int = 30):
    """Perfect bullish signal: positive scores correlate with positive returns."""
    scores = [0.1 * (i - n // 2) for i in range(n)]
    returns_1d = [0.005 * (i - n // 2) for i in range(n)]
    returns_5d = [0.010 * (i - n // 2) for i in range(n)]
    return scores, returns_1d, returns_5d


def test_validate_signal_quality_perfect_signal():
    scores, ret1, ret5 = _make_bullish_signals(30)
    result = validate_signal_quality(scores, ret1, ret5)
    assert result.n_observations == 30
    assert result.ic_1d is not None
    assert result.ic_1d > 0.9            # near-perfect correlation
    assert result.win_rate_1d is not None
    assert result.win_rate_1d > 0.9
    assert result.is_useful_1d is True
    assert result.long_short_spread_1d is not None
    assert result.long_short_spread_1d > 0  # longs beat shorts


def test_validate_signal_quality_noise_signal():
    import random
    random.seed(42)
    n = 50
    scores = [random.uniform(-1, 1) for _ in range(n)]
    returns = [random.uniform(-0.05, 0.05) for _ in range(n)]
    result = validate_signal_quality(scores, returns)
    # Random signal should not reliably pass usefulness threshold
    assert result.n_observations == n
    assert result.ic_1d is not None     # computable even if near zero
    # is_useful_1d might be True or False for random data (no strong assertion)


def test_validate_signal_quality_no_5d():
    scores = [0.1 * i for i in range(10)]
    ret1d = [0.005 * i for i in range(10)]
    result = validate_signal_quality(scores, ret1d)
    assert result.ic_5d is None
    assert result.win_rate_5d is None
    assert result.long_short_spread_5d is None


def test_validate_signal_quality_length_mismatch():
    with pytest.raises(ValueError, match="same length"):
        validate_signal_quality([0.1, 0.2], [0.01])


def test_validate_signal_quality_5d_length_mismatch():
    with pytest.raises(ValueError):
        validate_signal_quality([0.1, 0.2], [0.01, 0.02], [0.05])


def test_validate_signal_negative_ic():
    """Contrarian signal: positive scores → negative returns → IC < 0."""
    scores = [0.1 * i for i in range(20)]
    returns = [-0.005 * i for i in range(20)]
    result = validate_signal_quality(scores, returns)
    assert result.ic_1d is not None
    assert result.ic_1d < 0
    assert result.is_useful_1d is False


def test_long_short_spread_direction():
    """When positive signals predict gains and negative predict losses, spread > 0."""
    scores = [0.8, 0.6, -0.6, -0.8]
    returns = [0.03, 0.02, -0.02, -0.03]
    result = validate_signal_quality(scores, returns)
    assert result.long_short_spread_1d is not None
    assert result.long_short_spread_1d > 0
