"""Unit tests for SignalService."""

from sqlalchemy.orm import Session

from apps.api.app.services.signal_service import SignalService


def test_save_and_retrieve_snapshot(db_session: Session) -> None:
    svc = SignalService(db_session)
    snap = svc.save_snapshot(
        symbol="600519.SH",
        signal_type="TECHNICAL",
        raw_score=0.65,
        confidence=0.78,
        components={"momentum": 0.7, "trend": 0.6},
        expected_horizon="swing_5d",
    )
    assert snap.signal_id is not None
    assert snap.raw_score == 0.65
    assert snap.confidence == 0.78
    assert snap.components["momentum"] == 0.7


def test_list_latest_returns_most_recent(db_session: Session) -> None:
    svc = SignalService(db_session)
    svc.save_snapshot("600519.SH", "TECHNICAL", 0.3, 0.5, {}, "swing_5d")
    svc.save_snapshot("600519.SH", "TECHNICAL", 0.7, 0.8, {}, "swing_5d")
    svc.save_snapshot("300750.SZ", "MOMENTUM", 0.4, 0.6, {}, "intraday")

    latest = svc.list_latest()
    symbols = {s.symbol for s in latest}
    assert "600519.SH" in symbols
    assert "300750.SZ" in symbols

    mao_signals = [s for s in latest if s.symbol == "600519.SH"]
    assert len(mao_signals) == 1
    assert mao_signals[0].raw_score == 0.7


def test_model_version_from_config(db_session: Session) -> None:
    svc = SignalService(db_session)
    snap = svc.save_snapshot("600519.SH", "TECHNICAL", 0.5, 0.6, {}, "swing_5d")
    assert snap.model_version != ""


def test_save_multiple_symbols(db_session: Session) -> None:
    svc = SignalService(db_session)
    symbols = ["600519.SH", "300750.SZ", "000858.SZ", "601318.SH"]
    for sym in symbols:
        svc.save_snapshot(sym, "COMBINED", 0.5, 0.6, {}, "swing_5d")
    latest = svc.list_latest()
    latest_symbols = {s.symbol for s in latest}
    assert set(symbols) == latest_symbols
