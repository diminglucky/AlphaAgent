from apps.api.app.db.models import AlertORM, AnalysisCacheORM, PositionORM, WatchlistORM
from apps.api.app.db.session import init_db


def test_init_db_creates_current_alpha_agent_tables(tmp_path, monkeypatch) -> None:
    from apps.api.app.core import config as config_mod
    from apps.api.app.db import session as session_mod

    db_path = tmp_path / "quant.db"
    monkeypatch.setenv("QUANT_DATABASE_URL", f"sqlite:///{db_path}")
    config_mod.reset_settings_cache()
    session_mod._engine = None
    session_mod._SessionLocal = None

    init_db()

    engine = session_mod.get_engine()
    names = set(WatchlistORM.metadata.tables)
    assert {"watchlist", "alerts", "positions", "analysis_cache"} <= names

    with engine.connect() as conn:
        table_names = {
            row[0]
            for row in conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert {WatchlistORM.__tablename__, AlertORM.__tablename__, PositionORM.__tablename__, AnalysisCacheORM.__tablename__} <= table_names
