"""Unit tests for WatchlistService."""

from sqlalchemy.orm import Session

from apps.api.app.services.watchlist_service import WatchlistService, DEFAULT_SYMBOLS


def test_empty_returns_default_symbols(db_session: Session) -> None:
    svc = WatchlistService(db_session)
    syms = svc.list_symbols("acct-1")
    assert syms == DEFAULT_SYMBOLS


def test_add_and_list(db_session: Session) -> None:
    svc = WatchlistService(db_session)
    svc.add("acct-1", "600519.SH", "茅台 long-term hold")
    svc.add("acct-1", "000001.SZ", "")
    items = svc.list_items("acct-1")
    assert len(items) == 2
    assert {i.symbol for i in items} == {"600519.SH", "000001.SZ"}


def test_add_idempotent(db_session: Session) -> None:
    svc = WatchlistService(db_session)
    a = svc.add("acct-1", "600519.SH", "v1")
    b = svc.add("acct-1", "600519.SH", "v2")
    assert a.item_id == b.item_id
    assert b.note == "v2"


def test_account_isolation(db_session: Session) -> None:
    svc = WatchlistService(db_session)
    svc.add("acct-A", "600519.SH")
    svc.add("acct-B", "300750.SZ")
    assert svc.list_symbols("acct-A") == ["600519.SH"]
    assert svc.list_symbols("acct-B") == ["300750.SZ"]


def test_remove(db_session: Session) -> None:
    svc = WatchlistService(db_session)
    svc.add("acct-1", "600519.SH")
    svc.add("acct-1", "000001.SZ")
    assert svc.remove("acct-1", "600519.SH") is True
    assert svc.remove("acct-1", "MISSING.XX") is False
    assert [i.symbol for i in svc.list_items("acct-1")] == ["000001.SZ"]


def test_reorder(db_session: Session) -> None:
    svc = WatchlistService(db_session)
    svc.add("acct-1", "AAA.SH")
    svc.add("acct-1", "BBB.SH")
    svc.add("acct-1", "CCC.SH")

    n = svc.reorder("acct-1", ["CCC.SH", "AAA.SH", "BBB.SH"])
    assert n == 3
    syms = [i.symbol for i in svc.list_items("acct-1")]
    assert syms == ["CCC.SH", "AAA.SH", "BBB.SH"]


def test_normalize_symbol_case(db_session: Session) -> None:
    svc = WatchlistService(db_session)
    svc.add("acct-1", "600519.sh")
    items = svc.list_items("acct-1")
    assert items[0].symbol == "600519.SH"


def test_empty_symbol_rejected(db_session: Session) -> None:
    svc = WatchlistService(db_session)
    import pytest
    with pytest.raises(ValueError):
        svc.add("acct-1", "  ")
