"""Migration CLI — apply, revert, or inspect schema migrations.

Usage:
    python -m app.db.migrate --status
    python -m app.db.migrate --upgrade
    python -m app.db.migrate --downgrade 1
"""

from __future__ import annotations

import argparse
import sqlite3

from app.core.config import get_settings
from app.db.database import sqlite_path_from_url
from app.db.migration_runner import (
    MigrationError,
    current_version,
    downgrade,
    ensure_tracking_table,
    upgrade,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PisoNet schema migrations")
    parser.add_argument("--upgrade", action="store_true", help="Apply pending migrations")
    parser.add_argument("--downgrade", type=int, metavar="STEPS", help="Revert N migrations")
    parser.add_argument("--status", action="store_true", help="Show current schema version")
    args = parser.parse_args(argv)

    settings = get_settings()
    settings.validate_or_generate_secrets()
    db_path = sqlite_path_from_url(settings)
    conn = sqlite3.connect(db_path)
    try:
        if args.downgrade:
            reverted = downgrade(conn, args.downgrade)
            print(f"Reverted migrations: {reverted or 'none'}")
            return 0
        if args.upgrade:
            applied = upgrade(conn)
            print(f"Applied migrations: {applied or 'none (already current)'}")
            return 0
        ensure_tracking_table(conn)
        version = current_version(conn)
        print(f"Schema version: {version}")
        return 0
    except MigrationError as exc:
        print(f"MIGRATION ERROR: {exc}")
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
