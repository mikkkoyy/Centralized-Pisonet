"""Explicit, versioned schema migrations.

Each migration is a numbered module in ``app/db/migrations/`` with
``VERSION``, ``NAME``, ``up(conn)`` and ``down(conn)`` operating on a
raw ``sqlite3`` connection. Applied versions are recorded in the
``schema_migrations`` table inside the same transaction as the schema
change, so a migration is either fully applied or fully absent.

Rules enforced by the runner:
- Migrations are applied in strict version order; gaps are errors.
- Re-running ``upgrade`` when already current is a no-op (repeatable).
- A database whose applied version exceeds the latest known migration
  is an unsupported state and fails loudly.
- A non-contiguous applied history is an error.
- The application never mutates the schema outside this runner.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable


class MigrationError(RuntimeError):
    """Raised for unsupported or inconsistent migration states."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    up: Callable[[sqlite3.Connection], None]
    down: Callable[[sqlite3.Connection], None]


def _migration_modules() -> list[Migration]:
    from app.db import migrations as migrations_pkg
    from importlib import import_module
    import pkgutil

    found: list[Migration] = []
    for mod_info in pkgutil.iter_modules(migrations_pkg.__path__):
        # Migration modules are named _NNN_description.py: the leading
        # underscore keeps the importable module name valid.
        name = mod_info.name.lstrip("_")
        if not name or not name[0].isdigit():
            continue
        module = import_module(f"app.db.migrations.{mod_info.name}")
        found.append(
            Migration(
                version=module.VERSION,
                name=module.NAME,
                up=module.up,
                down=module.down,
            )
        )
    found.sort(key=lambda m: m.version)
    versions = [m.version for m in found]
    if len(set(versions)) != len(versions):
        raise MigrationError(f"Duplicate migration versions registered: {versions}")
    return found


def ensure_tracking_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     INTEGER PRIMARY KEY,
            name        TEXT NOT NULL,
            applied_at  INTEGER NOT NULL
        )
        """
    )
    conn.commit()


def applied_versions(conn: sqlite3.Connection) -> set[int]:
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {int(row[0]) for row in rows}


def current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
    return int(row[0])


def _validate_history(conn: sqlite3.Connection, registry: list[Migration]) -> None:
    applied = applied_versions(conn)
    if not applied:
        return
    known = {m.version for m in registry}
    unknown = sorted(applied - known)
    if unknown:
        raise MigrationError(
            "Database schema version(s) %s are newer than the latest "
            "supported migration (%d). Upgrade the server before use."
            % (", ".join(map(str, unknown)), registry[-1].version)
        )
    expected = set(range(1, max(applied) + 1))
    if applied != expected:
        missing = sorted(expected - applied)
        raise MigrationError(
            f"Inconsistent migration history; missing versions: {missing}"
        )


def upgrade(conn: sqlite3.Connection, target: int | None = None) -> list[int]:
    """Apply pending migrations in order. Returns applied versions."""
    ensure_tracking_table(conn)
    registry = _migration_modules()
    _validate_history(conn, registry)
    latest = registry[-1].version
    target_version = latest if target is None else target
    if target_version not in {m.version for m in registry}:
        raise MigrationError(f"Unknown target migration version: {target_version}")

    current = current_version(conn)
    applied_now: list[int] = []
    for migration in registry:
        if migration.version <= current or migration.version > target_version:
            continue
        if migration.version != current + 1:
            raise MigrationError(
                f"Migration gap: cannot apply version {migration.version} "
                f"while database is at version {current}"
            )
        conn.execute("BEGIN IMMEDIATE")
        try:
            migration.up(conn)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) "
                "VALUES (?, ?, ?)",
                (migration.version, migration.name, int(__import__("time").time())),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        current = migration.version
        applied_now.append(migration.version)
    return applied_now


def downgrade(conn: sqlite3.Connection, steps: int = 1) -> list[int]:
    """Reverse the last ``steps`` migrations. Returns reverted versions."""
    ensure_tracking_table(conn)
    registry = _migration_modules()
    _validate_history(conn, registry)
    current = current_version(conn)
    reverted: list[int] = []
    by_version = {m.version: m for m in registry}
    for _ in range(steps):
        if current == 0:
            break
        migration = by_version.get(current)
        if migration is None:
            raise MigrationError(f"Cannot downgrade unknown version {current}")
        conn.execute("BEGIN IMMEDIATE")
        try:
            migration.down(conn)
            conn.execute("DELETE FROM schema_migrations WHERE version = ?", (current,))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        reverted.append(current)
        current -= 1
    return reverted
