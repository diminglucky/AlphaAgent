"""Shared fixtures for unit tests that need a DB session."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from apps.api.app.db.base import Base


@pytest.fixture(autouse=True)
def _isolate_llm_runtime_config(tmp_path, monkeypatch):
    """Prevent tests from picking up the user's persisted LLM config.

    Without this, tests run against real DeepSeek when a key is saved
    in ``data/llm_runtime.json`` — leading to flaky/slow runs and tests
    that assumed fallback behaviour suddenly hitting the network.
    """
    monkeypatch.setenv("QUANT_LLM_CONFIG_PATH", str(tmp_path / "llm.json"))
    # Also clear any cached override that prior tests / imports may have set.
    from libs.llm_analyst import runtime_config as rc
    rc._OVERRIDE = None
    # Clear any provider env vars that might short-circuit the fallback path.
    for var in ("QUANT_LLM_PROVIDER", "QUANT_LLM_API_KEY", "QUANT_LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)
    yield
    rc._OVERRIDE = None


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
    """Session with sample positions, instruments, risk rules, etc. seeded."""
    from apps.api.app.db.bootstrap import seed_demo_data
    session, engine = _make_session()
    try:
        seed_demo_data(session)
        session.commit()
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()
