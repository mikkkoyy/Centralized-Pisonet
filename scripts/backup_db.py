"""SQLite backup utility — consistent online backup.

Usage:
    python -m scripts.backup_db [destination]

Uses SQLite's online backup API so the copy is consistent even
while the server is running. Default destination:
backups/pisonet-<UTC timestamp>.db.bak
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import get_settings
from app.db.database import sqlite_path_from_url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Back up the PisoNet database")
    parser.add_argument("destination", nargs="?", help="Backup file path")
    args = parser.parse_args(argv)

    settings = get_settings()
    settings.validate_or_generate_secrets()
    source = sqlite_path_from_url(settings).resolve()
    if not source.exists():
        print(f"ERROR: database not found at {source}", file=sys.stderr)
        return 1

    if args.destination:
        dest = Path(args.destination)
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dest = source.parent / "backups" / f"pisonet-{stamp}.db.bak"
    dest.parent.mkdir(parents=True, exist_ok=True)

    # The SQLite online backup API produces a consistent
    # copy even while the server is running.
    src = sqlite3.connect(str(source))
    dst = sqlite3.connect(str(dest))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    print(f"Backup written to {dest} ({dest.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
