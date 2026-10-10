"""Provision the initial administrator account.

Usage:
    python -m scripts.provision_admin --username ops --password '...'

Fails when an administrator already exists, preventing silent
account creation on a running system.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from app.core.config import get_settings
from app.db.database import (
    create_engine_from_settings,
    get_session_factory,
    sqlite_path_from_url,
)
from app.db.migration_runner import upgrade
from app.services.admin import AdminProvisionError, provision_admin


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Provision the first administrator")
    parser.add_argument("--username", required=True, help="Administrator username")
    parser.add_argument("--password", help="Administrator password (prompted when omitted)")
    args = parser.parse_args(argv)

    password = args.password or getpass.getpass("Administrator password: ")
    if len(password) < 8:
        print("ERROR: password must be at least 8 characters", file=sys.stderr)
        return 1

    settings = get_settings()
    settings.validate_or_generate_secrets()
    engine = create_engine_from_settings(settings)
    factory = get_session_factory(engine)

    import sqlite3

    conn = sqlite3.connect(str(sqlite_path_from_url(settings)))
    try:
        upgrade(conn)
    finally:
        conn.close()

    db = factory()
    try:
        admin = provision_admin(db, username=args.username, password=password)
    except AdminProvisionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()
        engine.dispose()

    print(f"Administrator {admin.username!r} provisioned (id={admin.id}).")
    print("Keep this password confidential; it is not stored or logged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
