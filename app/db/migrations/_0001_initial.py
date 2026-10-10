"""Migration 0001: initial PISO-002 schema.

Creates every table required by the server foundation:
stations, sessions, ledger_entries, admins, admin_login_attempts,
audit_events, server_config, station_commands.

Money is stored as integer cents (``amount_cents``). Time is stored
as integer Unix epoch seconds (UTC). No floating-point columns exist.
"""

from __future__ import annotations

import sqlite3
import time

VERSION = 1
NAME = "initial"

_STATEMENTS = [
    # --- Stations ---
    """
    CREATE TABLE stations (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        station_code    TEXT    NOT NULL UNIQUE,
        display_name    TEXT,
        token_hash      TEXT    NOT NULL,
        token_prefix    TEXT,
        enrolled_at     INTEGER NOT NULL,
        last_seen_at    INTEGER,
        ip_address      TEXT,
        mac_address     TEXT,
        is_active       INTEGER NOT NULL DEFAULT 1,
        protocol_version INTEGER NOT NULL DEFAULT 1
    )
    """,
    "CREATE INDEX idx_stations_last_seen ON stations(last_seen_at)",

    # --- Sessions (one active session per station is enforced by a
    #     partial unique index; SQLite 3.8+) ---
    """
    CREATE TABLE sessions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        station_id      INTEGER NOT NULL REFERENCES stations(id) ON DELETE CASCADE,
        granted_seconds INTEGER NOT NULL,
        started_at      INTEGER NOT NULL,
        ended_at        INTEGER,
        end_reason      TEXT,
        created_at      INTEGER NOT NULL,
        CHECK (granted_seconds >= 0),
        CHECK (ended_at IS NULL OR ended_at >= started_at),
        CHECK (end_reason IS NULL OR end_reason IN
               ('expired', 'admin_terminated', 'completed'))
    )
    """,
    "CREATE INDEX idx_sessions_station ON sessions(station_id)",
    "CREATE INDEX idx_sessions_started ON sessions(started_at)",
    """
    CREATE UNIQUE INDEX idx_sessions_one_active
        ON sessions(station_id) WHERE ended_at IS NULL
    """,

    # --- Ledger (idempotency enforced by UNIQUE idempotency_key) ---
    """
    CREATE TABLE ledger_entries (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        idempotency_key  TEXT    NOT NULL UNIQUE,
        station_id       INTEGER NOT NULL REFERENCES stations(id),
        session_id       INTEGER REFERENCES sessions(id),
        amount_cents     INTEGER NOT NULL,
        seconds_credited INTEGER NOT NULL,
        payload_hash     TEXT    NOT NULL,
        created_at       INTEGER NOT NULL,
        CHECK (amount_cents >= 0),
        CHECK (seconds_credited >= 0)
    )
    """,
    "CREATE INDEX idx_ledger_station_time ON ledger_entries(station_id, created_at)",
    "CREATE INDEX idx_ledger_created ON ledger_entries(created_at)",

    # --- Administrators ---
    """
    CREATE TABLE admins (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        username      TEXT    NOT NULL UNIQUE,
        password_hash TEXT    NOT NULL,
        role          TEXT    NOT NULL DEFAULT 'admin',
        created_at    INTEGER NOT NULL,
        last_login_at INTEGER,
        is_active     INTEGER NOT NULL DEFAULT 1
    )
    """,
    """
    CREATE TABLE admin_login_attempts (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        username   TEXT    NOT NULL,
        ip_address TEXT,
        succeeded  INTEGER NOT NULL,
        attempted_at INTEGER NOT NULL
    )
    """,
    "CREATE INDEX idx_login_attempts_user_time ON admin_login_attempts(username, attempted_at)",

    # --- Audit log ---
    """
    CREATE TABLE audit_events (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_type TEXT    NOT NULL,
        actor_id   INTEGER,
        event_type TEXT    NOT NULL,
        entity_type TEXT,
        entity_id  INTEGER,
        summary    TEXT    NOT NULL,
        created_at INTEGER NOT NULL,
        CHECK (actor_type IN ('admin', 'station', 'system'))
    )
    """,
    "CREATE INDEX idx_audit_created ON audit_events(created_at)",
    "CREATE INDEX idx_audit_entity ON audit_events(entity_type, entity_id)",

    # --- Runtime configuration (persists generated enrollment secret) ---
    """
    CREATE TABLE server_config (
        key        TEXT PRIMARY KEY,
        value      TEXT NOT NULL,
        updated_at INTEGER NOT NULL
    )
    """,

    # --- Pending station commands (with expiry and acknowledgement) ---
    """
    CREATE TABLE station_commands (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        station_id       INTEGER NOT NULL REFERENCES stations(id) ON DELETE CASCADE,
        command_type     TEXT    NOT NULL,
        payload          TEXT,
        created_at       INTEGER NOT NULL,
        expires_at       INTEGER NOT NULL,
        acknowledged_at  INTEGER,
        CHECK (expires_at > created_at),
        CHECK (command_type IN ('lock', 'unlock'))
    )
    """,
    "CREATE INDEX idx_commands_station ON station_commands(station_id, created_at)",
]

_DROP_ORDER = [
    "DROP INDEX IF EXISTS idx_commands_station",
    "DROP TABLE IF EXISTS station_commands",
    "DROP TABLE IF EXISTS server_config",
    "DROP INDEX IF EXISTS idx_audit_created",
    "DROP INDEX IF EXISTS idx_audit_entity",
    "DROP TABLE IF EXISTS audit_events",
    "DROP INDEX IF EXISTS idx_login_attempts_user_time",
    "DROP TABLE IF EXISTS admin_login_attempts",
    "DROP TABLE IF EXISTS admins",
    "DROP INDEX IF EXISTS idx_ledger_station_time",
    "DROP INDEX IF EXISTS idx_ledger_created",
    "DROP TABLE IF EXISTS ledger_entries",
    "DROP INDEX IF EXISTS idx_sessions_one_active",
    "DROP INDEX IF EXISTS idx_sessions_station",
    "DROP INDEX IF EXISTS idx_sessions_started",
    "DROP TABLE IF EXISTS sessions",
    "DROP INDEX IF EXISTS idx_stations_last_seen",
    "DROP TABLE IF EXISTS stations",
]


def up(conn: sqlite3.Connection) -> None:
    for statement in _STATEMENTS:
        conn.execute(statement)


def down(conn: sqlite3.Connection) -> None:
    for statement in _DROP_ORDER:
        conn.execute(statement)


if __name__ == "__main__":  # pragma: no cover - manual smoke check
    import tempfile

    with tempfile.TemporaryDirectory():
        c = sqlite3.connect(":memory:")
        up(c)
        c.execute("INSERT INTO stations (station_code, token_hash, enrolled_at) VALUES ('PC-01', ?, ?)",
                  ("x" * 64, int(time.time())))
        print("0001 smoke OK, stations:", c.execute("SELECT COUNT(*) FROM stations").fetchone()[0])
