"""Database engine, session factory and bootstrapping."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import ROOT_DIR, settings


class Base(DeclarativeBase):
    pass


def _resolve(url: str) -> str:
    """Allow relative sqlite paths (resolved against project root)."""
    if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
        rel = url.replace("sqlite:///", "", 1)
        Path(ROOT_DIR / rel).parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{ROOT_DIR / rel}"
    return url


engine = create_engine(
    _resolve(settings.database_url),
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):  # better concurrency for the dashboard
    try:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()
    except Exception:
        pass


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope() -> Session:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)

    Base.metadata.create_all(engine)
    _ensure_sqlite_columns()


def _ensure_sqlite_columns() -> None:
    """Add newly introduced nullable/defaulted columns to existing SQLite DBs.

    The project intentionally avoids a heavyweight migration dependency, but
    `create_all()` does not alter an already existing table. These idempotent
    ALTER statements keep upgrades safe for existing local installations.
    """
    if not str(engine.url).startswith("sqlite"):
        return
    required = {
        "videos": {
            "review_status": "VARCHAR(20) DEFAULT 'pending'",
            "review_notes": "TEXT DEFAULT ''",
            "reviewed_at": "DATETIME",
            "reviewed_by": "VARCHAR(120)",
        },
    }
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, columns in required.items():
            if table not in inspector.get_table_names():
                continue
            existing = {col["name"] for col in inspector.get_columns(table)}
            for name, definition in columns.items():
                if name not in existing:
                    conn.execute(text(
                        f"ALTER TABLE {table} ADD COLUMN {name} {definition}"
                    ))
