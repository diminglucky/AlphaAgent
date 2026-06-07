"""Shared fixtures for unit tests that need a DB session."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from apps.api.app.db.base import Base
from apps.api.app.db.models import PositionORM, WatchlistORM


@pytest.fixture(autouse=True)
def _isolate_llm_runtime_config(tmp_path, monkeypatch):
    """Prevent tests from picking up the user's persisted LLM config.

    Without this, tests run against real DeepSeek when a key is saved
    in ``data/llm_runtime.json`` — leading to flaky/slow runs and tests
    that assumed fallback behaviour suddenly hitting the network.
    """
    monkeypatch.setenv("QUANT_LLM_CONFIG_PATH", str(tmp_path / "llm.json"))
    monkeypatch.setenv("QUANT_RUNTIME_CONFIG_PATH", str(tmp_path / "runtime.json"))
    monkeypatch.setenv("QUANT_AUTH_ENABLED", "false")
    # Also clear any cached override that prior tests / imports may have set.
    from libs.llm_analyst import runtime_config as rc
    from apps.api.app.core import config as config_mod
    from apps.api.app.core import runtime_config as app_rc
    rc._OVERRIDE = None
    rc._OVERRIDE_MTIME = 0.0
    config_mod.reset_settings_cache()
    app_rc.reset_runtime_config_cache()
    # Clear any provider env vars that might short-circuit the fallback path.
    for var in ("QUANT_LLM_PROVIDER", "QUANT_LLM_API_KEY", "QUANT_LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)
    yield
    rc._OVERRIDE = None
    rc._OVERRIDE_MTIME = 0.0
    config_mod.reset_settings_cache()
    app_rc.reset_runtime_config_cache()


def _make_session() -> tuple[Session, "Engine"]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=True, autocommit=False, future=True)
    return factory(), engine


@pytest.fixture()
def db_session() -> Session:
    session, engine = _make_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def seeded_session() -> Session:
    """Session with sample AlphaAgent watchlist and positions."""
    session, engine = _make_session()
    try:
        session.add_all([
            WatchlistORM(symbol="600519.SH", name="贵州茅台", sort_order=0),
            WatchlistORM(symbol="000001.SZ", name="平安银行", sort_order=1),
            PositionORM(symbol="600519.SH", name="贵州茅台", quantity=100, avg_cost=100.0),
            PositionORM(symbol="000001.SZ", name="平安银行", quantity=1000, avg_cost=10.0),
        ])
        session.commit()
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()
