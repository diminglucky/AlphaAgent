"""Integration test isolation for the current AlphaAgent schema."""

from __future__ import annotations

import pytest

from apps.api.app.db.session import session_scope
from apps.api.app.db.models import (
    AlertORM,
    AnalysisCacheORM,
    PositionORM,
    TradeFillORM,
    TradeOrderORM,
    TradingAccountORM,
    TradingPositionORM,
    WatchlistORM,
)


@pytest.fixture(autouse=True)
def _clean_test_state() -> None:
    """Wipe test artifacts to give each test a clean slate."""
    with session_scope() as session:
        session.query(TradeFillORM).filter(TradeFillORM.symbol.in_(("300750.SZ", "000001.SZ"))).delete(
            synchronize_session=False
        )
        session.query(TradeOrderORM).filter(TradeOrderORM.symbol.in_(("300750.SZ", "000001.SZ"))).delete(
            synchronize_session=False
        )
        session.query(TradingAccountORM).filter(TradingAccountORM.account_id == "PAPER").delete(
            synchronize_session=False
        )
        session.query(TradingPositionORM).filter(TradingPositionORM.symbol.in_(("300750.SZ", "000001.SZ"))).delete(
            synchronize_session=False
        )
        for model in (AlertORM, AnalysisCacheORM, PositionORM, WatchlistORM):
            session.query(model).filter(model.symbol.in_(("300750.SZ", "000001.SZ"))).delete(
                synchronize_session=False
            )
    yield
    with session_scope() as session:
        session.query(TradeFillORM).filter(TradeFillORM.symbol.in_(("300750.SZ", "000001.SZ"))).delete(
            synchronize_session=False
        )
        session.query(TradeOrderORM).filter(TradeOrderORM.symbol.in_(("300750.SZ", "000001.SZ"))).delete(
            synchronize_session=False
        )
        session.query(TradingAccountORM).filter(TradingAccountORM.account_id == "PAPER").delete(
            synchronize_session=False
        )
        session.query(TradingPositionORM).filter(TradingPositionORM.symbol.in_(("300750.SZ", "000001.SZ"))).delete(
            synchronize_session=False
        )
        for model in (AlertORM, AnalysisCacheORM, PositionORM, WatchlistORM):
            session.query(model).filter(model.symbol.in_(("300750.SZ", "000001.SZ"))).delete(
                synchronize_session=False
            )
