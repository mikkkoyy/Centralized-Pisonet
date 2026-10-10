"""Versioned migration tests: apply, repeat, revert, fail loudly."""

from __future__ import annotations

import sqlite3

import pytest

from app.db.migration_runner import (
    MigrationError,
    current_version,
    downgrade,
    upgrade,
)

EXPECTED_TABLES = {
    "stations",
    "sessions",
    "ledger_entries",
    "admins",
    "admin_login_attempts",
    "audit_events",
    "server_config",
    "station_commands",
    "schema_migrations",
}


def _connect(tmp_path) -> sqlite3.Connection:
    return sqlite3.connect(tmp_path / "migrate.db")


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def _indexes(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
    }


def test_fresh_upgrade_applies_initial_schema(tmp_path):
    conn = _connect(tmp_path)
    try:
        assert upgrade(conn) == [1]
        assert current_version(conn) == 1
        assert EXPECTED_TABLES <= _tables(conn)
    finally:
        conn.close()


def test_one_active_session_partial_unique_index_exists(tmp_path):
    conn = _connect(tmp_path)
    try:
        upgrade(conn)
        assert "idx_sessions_one_active" in _indexes(conn)
    finally:
        conn.close()


def test_upgrade_is_repeatable(tmp_path):
    conn = _connect(tmp_path)
    try:
        assert upgrade(conn) == [1]
        assert upgrade(conn) == []
        assert current_version(conn) == 1
    finally:
        conn.close()


def test_downgrade_reverts_schema_and_reupgrade_reapplies(tmp_path):
    conn = _connect(tmp_path)
    try:
        upgrade(conn)
        assert downgrade(conn) == [1]
        assert current_version(conn) == 0
        assert not ({"stations", "sessions", "ledger_entries"} & _tables(conn))
        assert upgrade(conn) == [1]
        assert EXPECTED_TABLES <= _tables(conn)
    finally:
        conn.close()


def test_database_newer_than_code_fails_loudly(tmp_path):
    conn = _connect(tmp_path)
    try:
        upgrade(conn)
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) "
            "VALUES (99, 'future_migration', 1)"
        )
        conn.commit()
        with pytest.raises(MigrationError, match="newer than"):
            upgrade(conn)
    finally:
        conn.close()


def test_inconsistent_history_fails_loudly(tmp_path):
    """A gap in the applied history (1 and 3 applied, 2 missing)
    is an error even though all versions are known."""
    conn = _connect(tmp_path)
    try:
        upgrade(conn)
        from app.db.migration_runner import Migration, _validate_history

        conn.execute("DELETE FROM schema_migrations")
        conn.executemany(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, 1)",
            [(1, "a"), (3, "c")],
        )
        conn.commit()
        noop = lambda c: None
        registry = [
            Migration(1, "a", noop, noop),
            Migration(2, "b", noop, noop),
            Migration(3, "c", noop, noop),
        ]
        with pytest.raises(MigrationError, match="[Ii]nconsistent"):
            _validate_history(conn, registry)
    finally:
        conn.close()


def test_schema_changes_and_tracking_are_atomic(tmp_path):
    """A failed migration leaves no partial schema or tracking row."""
    conn = _connect(tmp_path)
    try:
        from app.db import migrations as migrations_pkg
        from importlib import import_module

        module = import_module("app.db.migrations._0001_initial")
        original_up = module.up

        def failing_up(c):
            original_up(c)
            raise RuntimeError("injected failure after DDL")

        module.up = failing_up
        try:
            from app.db.migration_runner import _migration_modules

            with pytest.raises(RuntimeError, match="injected failure"):
                upgrade(conn)
        finally:
            module.up = original_up
        assert _tables(conn) == {"schema_migrations"}
        assert current_version(conn) == 0
    finally:
        conn.close()
