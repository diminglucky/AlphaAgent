"""Replay tests use local lightweight fixtures for the current schema."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.app.db.base import Base
from apps.api.app.db.models import PositionORM, WatchlistORM


@pytest.fixture()
def seeded_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=True, autocommit=False, future=True)
    session = factory()
    try:
        session.add_all([
            WatchlistORM(symbol="600519.SH", name="贵州茅台", sort_order=0),
            WatchlistORM(symbol="000001.SZ", name="平安银行", sort_order=1),
            PositionORM(symbol="600519.SH", name="贵州茅台", quantity=100, avg_cost=100.0),
        ])
        session.commit()
        yield session
    finally:
        session.close()
        engine.dispose()
