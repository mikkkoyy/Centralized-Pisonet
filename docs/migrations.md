# Migrations

Schema changes are explicit, versioned, and tracked — the
application never mutates the schema outside the migration
runner.

## How it works

- Each migration is a numbered module in `app/db/migrations/`
  named `_NNN_description.py` and exposes:

  ```python
  VERSION = 2
  NAME = "add_station_timezone"

  def up(conn: sqlite3.Connection) -> None: ...
  def down(conn: sqlite3.Connection) -> None: ...
  ```

  `up`/`down` operate on a raw `sqlite3` connection.

- Applied versions are recorded in the `schema_migrations`
  table **inside the same transaction** as the schema change,
  so a migration is either fully applied or fully absent.

- The runner (`app/db/migration_runner.py`) enforces:
  - strict version order — **gaps are errors**;
  - repeatable upgrades (re-running when current is a no-op);
  - a database whose applied version exceeds the latest known
    migration **fails loudly** ("newer than the latest supported
    migration");
  - a non-contiguous applied history is an error;
  - duplicate migration versions are rejected at discovery.

- Migrations run automatically at server startup (lifespan) and
  via the CLI:

  ```powershell
  .venv\Scripts\python.exe -m app.db.migrate --upgrade
  .venv\Scripts\python.exe -m app.db.migrate --downgrade   # revert last
  ```

## Current schema (version 1)

Tables: `stations`, `sessions`, `ledger_entries`, `admins`,
`admin_login_attempts`, `audit_events`, `server_config`,
`station_commands`, plus `schema_migrations`.

Key constraints:

- `sessions`: partial unique index
  `idx_sessions_one_active ON sessions(station_id) WHERE ended_at IS NULL`
  (one active session per station); CHECKs on
  `granted_seconds >= 0` and allowed `end_reason` values.
- `ledger_entries`: UNIQUE `idempotency_key`; CHECKs on
  non-negative amounts.
- `station_commands`: CHECK `expires_at > created_at`;
  `command_type IN ('lock','unlock')`.
- `audit_events`: CHECK `actor_type IN ('admin','station','system')`.

## Adding a migration

1. Create `app/db/migrations/_0002_your_change.py` with `up`
   and `down`.
2. Add the matching ORM model changes in `app/models/` (the
   ORM models must reflect the migrated schema).
3. Run `python -m app.db.migrate --upgrade` against a copy of
   production data first; verify with `pytest`.
4. Never edit an applied migration. If a bad migration shipped,
   write a corrective `_0003_...` migration instead.

## Why not auto-migrations (Alembic)

The schema is small and the deployment is a single shop LAN
server. Explicit migrations make every change reviewable, keep
the dependency surface minimal, and make failure modes
(gaps, future versions) loud and deterministic.
