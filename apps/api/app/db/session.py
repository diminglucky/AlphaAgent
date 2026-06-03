from contextlib import contextmanager
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

from apps.api.app.core.config import get_settings
from apps.api.app.db.base import Base

_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        is_sqlite = "sqlite" in settings.database_url
        _engine = create_engine(
            settings.database_url,
            connect_args={"check_same_thread": False} if is_sqlite else {},
            echo=False,
        )
        if is_sqlite:
            # 启用 WAL 模式 + 合理的同步级别，提升并发写性能
            @event.listens_for(_engine, "connect")
            def _set_sqlite_pragma(dbapi_connection, _conn_record):
                try:
                    cur = dbapi_connection.cursor()
                    cur.execute("PRAGMA journal_mode=WAL")
                    cur.execute("PRAGMA synchronous=NORMAL")
                    cur.execute("PRAGMA busy_timeout=5000")
                    cur.close()
                except Exception:
                    pass
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autocommit=False, autoflush=True)
    return _SessionLocal


def init_db():
    """建表（首次启动）"""
    Base.metadata.create_all(bind=get_engine())
    _migrate_legacy_columns()


def _migrate_legacy_columns():
    """轻量迁移：为已有表追加新增的列（仅 SQLite）"""
    settings = get_settings()
    if "sqlite" not in settings.database_url:
        return
    engine = get_engine()
    # SQLite ALTER TABLE 不支持非常量默认值，所以新列用 NULL，由 ORM 写入时自动填值
    migrations = [
        ("positions", "last_alert_at", "DATETIME", None),
        ("positions", "last_alert_kind", "VARCHAR(32)", None),
        ("analysis_cache", "updated_at", "DATETIME", "UPDATE analysis_cache SET updated_at = created_at WHERE updated_at IS NULL"),
        ("trade_fills", "evolution_recorded_at", "DATETIME", None),
    ]
    with engine.begin() as conn:
        for table, col, coltype, backfill in migrations:
            try:
                rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
                cols = {r[1] for r in rows}
                if col not in cols:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
                    if backfill:
                        conn.exec_driver_sql(backfill)
            except Exception:
                # 表不存在则忽略，将由 create_all 创建
                pass


@contextmanager
def session_scope() -> Session:
    factory = get_session_factory()
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db():
    """FastAPI Depends 用"""
    factory = get_session_factory()
    db = factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
