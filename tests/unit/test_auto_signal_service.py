"""Tests for AutoSignalService — confirms signal+rec persistence pipeline."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from apps.api.app.db.repositories import RecommendationRepository, SignalRepository
from apps.api.app.services.auto_signal_service import AutoSignalService
from apps.api.app.services.watchlist_service import WatchlistService


def test_run_once_generates_signals_and_recs(seeded_session: Session) -> None:
    db_session = seeded_session
    # Seed watchlist with a symbol that has bars in sample_data
    WatchlistService(db_session).add("acct-demo-001", "300750.SZ")

    svc = AutoSignalService(db_session)
    res = svc.run_once()

    # 300750 has only 5 bars in sample data — engine requires >=5
    assert res.symbols_scanned >= 1
    assert res.signals_saved >= 1
    assert res.recommendations_saved >= 1

    signals = SignalRepository(db_session).list_latest_per_symbol()
    assert any(s.symbol == "300750.SZ" for s in signals)


def test_run_once_handles_unknown_symbol_gracefully(db_session: Session) -> None:
    WatchlistService(db_session).add("acct-demo-001", "FAKE.XX")
    res = AutoSignalService(db_session).run_once()
    assert "FAKE.XX" in " ".join(res.errors) or res.signals_saved == 0


def test_run_once_includes_held_positions(seeded_session: Session) -> None:
    db_session = seeded_session
    """Even without watchlist entries, held positions should be scanned."""
    # PortfolioRepository sample seeds have 600519 + 000001
    res = AutoSignalService(db_session).run_once()
    signals = SignalRepository(db_session).list_latest_per_symbol()
    symbols = {s.symbol for s in signals}
    # Sample positions held — at least one should produce a signal
    assert symbols & {"600519.SH", "000001.SZ"}
