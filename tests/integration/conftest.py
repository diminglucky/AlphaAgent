"""Integration test isolation — clean up test-induced state between tests.

The integration suite uses FastAPI's TestClient which talks to the *real*
app and the persistent dev DB. Without isolation, repeated runs accumulate
positions from prior runs and trip the risk engine.

This fixture removes any 300750.SZ test artifacts before each test (it is
the symbol used by all order-lifecycle tests).
"""

from __future__ import annotations

import pytest

from apps.api.app.db.session import session_scope
from apps.api.app.db.models import OrderORM, PositionORM, TradeFillORM


@pytest.fixture(autouse=True)
def _clean_test_state() -> None:
    """Wipe 300750.SZ test artifacts to give each test a clean slate."""
    with session_scope() as session:
        session.query(TradeFillORM).filter(TradeFillORM.symbol == "300750.SZ").delete()
        session.query(OrderORM).filter(
            OrderORM.symbol == "300750.SZ",
            OrderORM.source == "MANUAL",
        ).delete()
        session.query(PositionORM).filter(PositionORM.symbol == "300750.SZ").delete()
    yield
    # Optionally clean again after — safer in case a test left state
    with session_scope() as session:
        session.query(TradeFillORM).filter(TradeFillORM.symbol == "300750.SZ").delete()
        session.query(OrderORM).filter(
            OrderORM.symbol == "300750.SZ",
            OrderORM.source == "MANUAL",
        ).delete()
        session.query(PositionORM).filter(PositionORM.symbol == "300750.SZ").delete()
