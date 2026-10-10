"""Shared fixtures: migrated temp databases, deterministic
clocks, and a lifespan-running TestClient against a temp app DB."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.migration_runner import upgrade


class FixedClock:
    """Deterministic clock for time-dependent logic."""

    def __init__(self, now: int = 1_700_000_000) -> None:
        self.now = now

    def __call__(self) -> int:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock()


@pytest.fixture
def db_session(tmp_path) -> Session:
    """A database session backed by a fully migrated temp SQLite file.

    Uses the real migration runner so schema constraints (the partial
    unique index, checks, triggers) are exactly as in production.
    """
    db_file = tmp_path / "test.db"
    conn = sqlite3.connect(db_file)
    try:
        upgrade(conn)
    finally:
        conn.close()
    engine = create_engine(
        f"sqlite:///{db_file}", connect_args={"timeout": 30}
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


class TestApp:
    """TestClient plus a session factory bound to the same database."""

    def __init__(self, client: TestClient, factory: sessionmaker) -> None:
        self.client = client
        self.session_factory = factory

    def db(self) -> Session:
        return self.session_factory()


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    """Isolate configuration: explicit secrets, temp database."""
    db_file = tmp_path / "app.db"
    monkeypatch.setenv("SECRET_KEY", "t" * 64)
    monkeypatch.setenv("ENROLLMENT_SECRET", "test-enrollment-secret-0000")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("STATION_HEARTBEAT_TIMEOUT", "30")
    get_settings.cache_clear()
    try:
        yield db_file
    finally:
        get_settings.cache_clear()


@pytest.fixture
def test_app(app_env) -> TestApp:
    """Run the real application lifespan against a temp database."""
    from app.db.database import create_engine_from_settings, get_session_factory
    from app.main import app

    settings = get_settings()
    engine = create_engine_from_settings(settings)
    factory = get_session_factory(engine)
    with TestClient(app) as client:
        yield TestApp(client, factory)
    engine.dispose()
