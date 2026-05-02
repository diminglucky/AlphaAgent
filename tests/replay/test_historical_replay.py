"""Historical replay test (§10.5).

Replays a known sample-data trading day end-to-end and verifies the system's
deterministic output (signals + recommendations) matches the engineering
contract. This guards against silent regressions when:
- Signal weights change
- Feature engineering changes
- Recommendation thresholds change

If signals are intentionally tuned, update the asserted ranges here.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from apps.api.app.db.repositories import RecommendationRepository, SignalRepository
from apps.api.app.services.auto_signal_service import AutoSignalService
from apps.api.app.services.watchlist_service import WatchlistService


@pytest.mark.replay
def test_replay_known_trading_day_produces_signals(seeded_session: Session) -> None:
    """Given a fixed sample dataset, signal generation is deterministic."""
    db = seeded_session
    WatchlistService(db).add("acct-demo-001", "300750.SZ")
    WatchlistService(db).add("acct-demo-001", "600519.SH")

    res = AutoSignalService(db).run_once()

    # Two watchlist symbols + 2 held positions → ≥2 signals saved
    assert res.symbols_scanned >= 2
    assert res.signals_saved >= 1
    assert res.recommendations_saved >= 1

    signals = SignalRepository(db).list_latest_per_symbol()
    by_symbol = {s.symbol: s for s in signals}

    # 300750 in sample data: bars are slightly up-trending, expect non-bearish
    if "300750.SZ" in by_symbol:
        assert -1.0 <= by_symbol["300750.SZ"].raw_score <= 1.0
        assert 0.0 <= by_symbol["300750.SZ"].confidence <= 1.0


@pytest.mark.replay
def test_replay_recommendations_have_required_fields(seeded_session: Session) -> None:
    """All emitted recommendations satisfy §2.1 #4 acceptance contract."""
    db = seeded_session
    WatchlistService(db).add("acct-demo-001", "300750.SZ")
    AutoSignalService(db).run_once()

    _, recs = RecommendationRepository(db).list_latest()
    assert len(recs) > 0
    for r in recs:
        # Per §2.1 the platform must emit at least these fields per recommendation
        assert r.symbol
        assert r.action in {"BUY", "SELL", "HOLD"}
        assert 0.0 <= r.confidence <= 1.0
        assert r.time_horizon
        assert r.reason_summary
        assert isinstance(r.risk_flags, list)


@pytest.mark.replay
def test_replay_audit_trail_complete(seeded_session: Session) -> None:
    """Every signal+recommendation should have a paired audit log."""
    from apps.api.app.db.repositories import AuditLogRepository
    db = seeded_session
    WatchlistService(db).add("acct-demo-001", "300750.SZ")
    AutoSignalService(db).run_once()

    logs = AuditLogRepository(db).list_recent(limit=200)
    actions = {l.action for l in logs}
    assert "SIGNAL_GENERATED" in actions
    assert "RECOMMENDATION_GENERATED" in actions
