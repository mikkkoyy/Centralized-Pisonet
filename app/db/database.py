"""Database engine, session factory, and SQLite configuration."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings


def sqlite_path_from_url(settings: Settings) -> Path:
    """Extract a filesystem path from a sqlite:/// URL.

    Only file-based SQLite URLs are supported; the server is a
    single-shop LAN deployment and does not use in-memory or
    remote databases in production.
    """
    url = settings.database_url
    if not url.startswith("sqlite:///"):
        raise ValueError(
            f"Unsupported DATABASE_URL scheme (only sqlite:/// is supported): {url}"
        )
    raw = url[len("sqlite:///"):]
    if raw in ("", ":memory:"):
        raise ValueError("In-memory SQLite is not supported for the persistent server database.")
    return Path(raw)


def create_engine_from_settings(settings: Settings) -> Engine:
    """Create the SQLAlchemy engine with SQLite-appropriate settings."""
    path = sqlite_path_from_url(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"timeout": 30},
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection: sqlite3.Connection, _record) -> None:
        # Enforce foreign keys on every connection (SQLite default is OFF).
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        # Busy timeout handled via connect_args timeout; WAL improves
        # read concurrency for the dashboard while sessions are written.
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine


def get_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def iter_dbapi_conn(engine: Engine) -> Generator[sqlite3.Connection, None, None]:
    """Yield raw DBAPI connections for migration work."""
    with engine.connect() as conn:
        dbapi = conn.connection.dbapi_connection if hasattr(conn, "connection") else conn.connection
        yield dbapi
