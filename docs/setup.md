# Setup & Operations

## Requirements

- Python 3.12+ (Windows: use the `py -3.12` launcher or the
  full interpreter path; the Microsoft Store stub is not
  sufficient)
- pip

## Install

```powershell
cd "D:\FILES\project\Centralized Pisonet"
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Configure

Copy `.env.example` to `.env` and set:

```
SECRET_KEY=<python -c "import secrets; print(secrets.token_hex(32))">
ENROLLMENT_SECRET=<python -c "import secrets; print(secrets.token_hex(32))">
DATABASE_URL=sqlite:///./pisonet.db
ENVIRONMENT=production        # or development
STATION_HEARTBEAT_TIMEOUT=30
SERVER_HOST=127.0.0.1
SERVER_PORT=8000
```

- `SECRET_KEY` is **required** (≥ 32 chars); the server refuses
  to start without it.
- `ENROLLMENT_SECRET` is optional: on first boot a random
  secret is generated, persisted to the database, and surfaced
  as a startup notice. Stations cannot enroll until the
  operator retrieves it (from the notice or
  `SELECT value FROM server_config WHERE key='enrollment_secret'`).
- Changing `ENROLLMENT_SECRET` later does not invalidate
  existing station tokens; it only guards new enrollments.

## Initialize

```powershell
# apply migrations (idempotent)
.venv\Scripts\python.exe -m app.db.migrate --upgrade

# provision the first administrator (only works when no admin exists)
.venv\Scripts\python.exe scripts/provision_admin.py --username root --password <strong-password>
```

## Run

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000/dashboard/overview`.

## Verify

```powershell
.venv\Scripts\python.exe -m pytest tests/ -q     # 92 tests
.venv\Scripts\python.exe scripts/smoke_check.py  # live server check (server must be running)
```

## Backup

```powershell
.venv\Scripts\python.exe scripts/backup_db.py --output backup/pisonet-$(Get-Date -f yyyyMMdd-HHmm).db
```

Uses the SQLite online backup API, so it is safe while the
server is running.

## Day-2 operations

- **Enroll a station**: the station client calls
  `POST /api/v1/stations/register` with the enrollment secret,
  or an administrator pre-registers via
  `POST /api/v1/admin/stations` (dashboard → Stations).
- **Rotate a compromised credential**: dashboard → station →
  rotate token (old token dies immediately).
- **Revoke a station**: dashboard → station → revoke; all its
  authentication is rejected until re-activated.
- **Lock a station**: dashboard → station → lock; terminates the
  active session and queues a `lock` command the client picks
  up on its next heartbeat.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Server refuses to start: "SECRET_KEY is not set" | Set `SECRET_KEY` (≥ 32 chars) in `.env` or the environment. |
| "Database schema version(s) … are newer" | The database was written by a newer server version; upgrade the code before use. |
| "Inconsistent migration history" | The `schema_migrations` table has gaps; restore from backup. |
| Stations cannot enroll | `ENROLLMENT_SECRET` mismatch; check the persisted value in `server_config`. |
| 403 on dashboard forms | CSRF cookie missing/expired; reload the page to obtain a fresh token. |
