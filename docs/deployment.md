# Production Deployment Guide

Evidence-based guide for operating the MKY PisoNet
Central server securely behind HTTPS and as a managed
service in a single-shop LAN.

**Labeling convention used throughout:**

- **Verified** — confirmed against the source code in
  this repository (file references included).
- **Recommendation** — operational guidance; the
  examples are **not executed by CI** and must be
  validated in the target environment before use.

This guide documents the supported configuration only.
Nothing here deploys publicly, creates production
credentials, or installs services.

## 1. Host prerequisites and installation

**Verified requirements:**

- Python **3.12+** (`pyproject.toml`: `requires-python
  = ">=3.12"`).
- pip, and a writable directory for the database,
  logs, and backups.
- The server is a single-process, single-shop LAN
  service (`docs/architecture.md`).

```powershell
# install (Windows; adjust for Linux)
py -3.12 -m venv C:\pisonet\.venv
C:\pisonet\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

`.[dev]` installs the runtime dependencies
(FastAPI, uvicorn[standard], SQLAlchemy,
pydantic-settings, argon2-cffi, pyjwt, python-multipart,
jinja2) plus the test tools (pytest, httpx). The `dev`
extra is optional at runtime.

## 2. Environment configuration and secrets

**Verified** (`app/core/config.py`): settings are read
from environment variables with a `.env` file at the
**project root** as fallback (`extra="ignore"`). All
values are validated; the server **refuses to start**
when required secrets are missing or malformed.

| Variable | Default | Validation / behavior |
|---|---|---|
| `SECRET_KEY` | _(none)_ | **Required**, ≥ 32 chars. Signs admin session JWTs. Server refuses to start without it. |
| `ENROLLMENT_SECRET` | _(generated)_ | Optional. When unset, a random secret is generated **once**, persisted to `server_config`, and surfaced as a startup NOTICE (the value is never logged). Environment wins over the persisted value. |
| `ENVIRONMENT` | `development` | Must be `development` or `production`. `production` sets the `Secure` flag on cookies. |
| `DATABASE_URL` | `sqlite:///./pisonet.db` | Only `sqlite:///` **file** paths; `:memory:` is rejected. Relative paths resolve against the process working directory. Parent directories are created automatically. |
| `STATION_HEARTBEAT_TIMEOUT` | `30` | Positive integer (seconds without a heartbeat before a station is `offline`). |
| `SERVER_HOST`, `SERVER_PORT` | `127.0.0.1`, `8000` | **Known gap:** these settings are validated but **not consumed** by the application. The bind address/port are set by the uvicorn CLI flags (§4). Do not rely on these variables for binding. |

Generate secrets (never reuse across installs):

```powershell
python -c "import secrets; print(secrets.token_hex(32))"   # SECRET_KEY
python -c "import secrets; print(secrets.token_hex(32))"   # ENROLLMENT_SECRET
```

**Secret rotation (verified behavior):**

- Rotating `SECRET_KEY` invalidates **all admin
  sessions** immediately (JWT signature check fails);
  station credentials are unaffected (station tokens
  use independent SHA-256 verifiers). Plan an operator
  re-login.
- Changing `ENROLLMENT_SECRET` only guards **new**
  enrollments; existing station tokens keep working.
  If the variable is unset at boot, the value
  persisted in `server_config` is used instead.
- `.env` is git-ignored; never commit it.

## 3. First-boot initialization

**Verified CLI tools** (all read the same configuration):

```powershell
# apply pending migrations (idempotent; also runs at startup)
.venv\Scripts\python.exe -m app.db.migrate --upgrade
.venv\Scripts\python.exe -m app.db.migrate --status

# provision the FIRST administrator (fails if any admin exists;
# password is prompted when --password is omitted; minimum 8 chars)
.venv\Scripts\python.exe -m scripts.provision_admin --username ops

# consistent online backup (SQLite backup API; safe while running)
.venv\Scripts\python.exe -m scripts.backup_db
# default destination: <db-directory>\backups\pisonet-<UTC>.db.bak
```

There is **no default administrator and no default
password** (`app/services/admin.py`). Administrator
passwords are Argon2id
(time_cost=3, memory_cost=64 MiB, parallelism=4).

## 4. Production startup and process supervision

**Verified startup command** (binding is via CLI flags,
not `SERVER_HOST`/`SERVER_PORT`):

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --host 192.168.1.50 --port 8000
```

At startup (lifespan, `app/main.py`): configuration is
validated, the SQLite engine is opened, pending
migrations are applied (repeatable, tracked, fails
loudly on unsupported states), the enrollment secret is
resolved, and a 30-second background session sweeper
starts. Shutdown is graceful (sweeper stopped, engine
disposed).

**Recommendation (not executed by CI):** run uvicorn
under a service manager so it restarts on failure and
after reboots. On Windows, NSSM or WinSW are common
choices; on Linux, a systemd unit. Example systemd unit
(**untested — adapt and validate**):

```ini
[Unit]
Description=MKY PisoNet Central
After=network.target

[Service]
WorkingDirectory=/opt/pisonet
EnvironmentFile=/opt/pisonet/.env
ExecStart=/opt/pisonet/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Bind to the shop LAN interface (or loopback when a
reverse proxy runs on the same host — §5). Do not bind
to `0.0.0.0` on an untrusted network.

## 5. HTTPS termination (reverse proxy)

**Verified:** the application has **no built-in TLS**.
The `.env.example` explicitly requires terminating TLS
at a reverse proxy for any non-loopback deployment:
station bearer tokens and admin cookies must never
cross plain HTTP. In `production` both cookies carry
the `Secure` flag (`app/api/v1/admin.py`,
`app/web/deps.py`), so browsers will only send them
over HTTPS — **a plain-HTTP dashboard deployment in
production mode will not keep users logged in**.

**Recommendation (untested examples — validate before
use):** terminate TLS with Caddy or nginx on the shop
LAN and proxy to the uvicorn listener. The proxy must:

- listen on HTTPS only (port 443) with a valid
  certificate (internal CA or Let's Encrypt, as the
  network allows);
- forward to `http://127.0.0.1:8000` (or the LAN
  address) preserving the `Host` header and setting
  `X-Forwarded-For` / `X-Forwarded-Proto`;
- **not** expose uvicorn's port directly (firewall it
  to the proxy or loopback, §7).

Caddyfile example (**untested**):

```
pisonet.shop.lan {
    reverse_proxy 127.0.0.1:8000
}
```

nginx example (**untested**):

```nginx
server {
    listen 443 ssl;
    server_name pisonet.shop.lan;
    ssl_certificate     /etc/ssl/certs/pisonet.crt;
    ssl_certificate_key /etc/ssl/private/pisonet.key;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

## 6. Trusted proxy and forwarding headers

**Verified:** the application contains **no
trusted-proxy middleware**. Client IP addresses seen by
the app (`request.client.host`) are used for station
IP recording, admin login-attempt records, and audit
entries.

uvicorn can trust `X-Forwarded-For` when started with
its native `--proxy-headers` flag:

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers
```

By default uvicorn only trusts proxy headers from
loopback (`--forwarded-allow-ips` defaults to
`127.0.0.1,::1`); widen that list only when the
proxy runs on another host.

**Trust caveat:** with `--proxy-headers`, any client
that can reach uvicorn from a trusted address can
spoof its source IP in audit and throttling records.
Only enable it when uvicorn is reachable
**exclusively** through the trusted reverse proxy
(firewall, §7). Without the flag, the recorded IP
is the proxy's address — accurate for connectivity,
but not the operator's real IP.

## 7. Firewall exposure and interface binding

**Recommendation:** expose only HTTPS to the shop LAN:

- Allow inbound **443/tcp** from shop LAN subnets only.
- Allow inbound **8000/tcp** from loopback or the
  reverse proxy host only — never from the whole LAN.
- Station clients need HTTPS access to the API
  (`/api/v1/...`); the dashboard uses the same origin.
- No outbound internet access is required: the system
  operates fully offline (`docs/security.md`).

## 8. SQLite storage, permissions, backups, restore

**Verified** (`app/db/database.py`):

- File-based SQLite only; WAL journal mode and
  `PRAGMA foreign_keys=ON` are enforced on every
  connection; busy timeout is 30 seconds.
- WAL mode creates `-wal` and `-shm` sidecar files next
  to the database — copy/clean them together with the
  main file, or use the backup API.
- SQLite is single-writer; it is sized for a single
  shop LAN, not high concurrency.

**Operational checklist (recommendation):**

- Store the database on persistent, backed-up storage
  with restrictive permissions (the service account
  only).
- Schedule `python -m scripts.backup_db` (online,
  consistent while running) and keep an off-machine copy
  of the backups directory.
- **Restore:** stop the service, replace the database
  file (and remove stale `-wal`/`-shm`), start the
  service; migrations re-check at startup. Test restores
  periodically — an untested backup is not a backup.
- **Migration precautions:** migrations run automatically
  at startup and are tracked in `schema_migrations`.
  Never edit an applied migration; a database written by
  a newer server version fails loudly (see
  `docs/migrations.md`). Backup before any upgrade.

## 9. Logging, health checks, restart behavior

**Verified:**

- Application logging: INFO level, format
  `%(asctime)s [%(levelname)s] %(name)s: %(message)s`
  (logger `pisonet`); uvicorn adds access logs.
  Startup emits `MKY PisoNet Central vX starting
  (protocol v1, environment=...)`; first-boot
  enrollment-secret generation emits a NOTICE.
- Health endpoint: `GET /health` returns
  `{status, version, protocol_version, environment}` —
  suitable for a liveness probe.
- Restart behavior: all state is in SQLite; a restart
  replays the same database (stations, sessions, ledger,
  audit history preserved — verified live in
  `docs/e2e-testing.md` §10). The 30 s sweeper expires
  elapsed sessions even when heartbeats are sparse.
- Graceful shutdown: SIGINT/SIGTERM to uvicorn stops
  the sweeper and disposes the engine.

**Troubleshooting (verified causes):**

| Symptom | Cause / fix |
|---|---|
| Refuses to start: `SECRET_KEY is not set` / `must be at least 32 characters` | Set `SECRET_KEY` (§2). |
| `Unsupported DATABASE_URL scheme` | Only `sqlite:///` file URLs are supported. |
| `In-memory SQLite is not supported` | `DATABASE_URL` points at `:memory:`. |
| `Database schema version(s) ... are newer` | The DB was written by a newer server; upgrade the code first. |
| `Inconsistent migration history` | Gaps in `schema_migrations`; restore from backup (`docs/migrations.md`). |
| Stations cannot enroll | `ENROLLMENT_SECRET` mismatch; the persisted value lives in `server_config` when the variable is unset. |
| Dashboard keeps redirecting to login in production | Cookies require HTTPS (`Secure`); serve over HTTPS (§5). |
| 403 on dashboard forms | CSRF cookie missing/expired; reload the page (`docs/setup.md`). |

## 10. Safe updates and rollback

**Recommendation (procedure):**

1. Run `scripts.backup_db` (§8) — the rollback point.
2. Stop the service.
3. Update the code (e.g., `git fetch && git checkout
   <tag>`), reinstall dependencies, review
   `docs/migrations.md` for schema changes.
4. Start the service; migrations apply automatically
   and are logged (`Applied migrations: [...]`).
5. Run post-deployment verification (§11).
6. **Rollback:** stop, restore the pre-update backup,
   restore the previous code version, start. Forward
   migrations may not be reversible — check the
   migration's `down()` first (`python -m app.db.migrate
   --downgrade N` reverts N steps); prefer the backup
   for production rollback.

## 11. Pre-deployment and post-deployment verification

**Verified commands:**

```powershell
# pre-deployment: full automated suites (98 server, 71 client tests)
.venv\Scripts\python.exe -m pytest
dotnet test client\PisoNet.Client.slnx --no-build

# post-deployment: live operator flow against a running server
# (NOTE: smoke_check.py is hardcoded for an ISOLATED instance on
# 127.0.0.1:8123 with test credentials — do not point it at a
# production deployment)
.venv\Scripts\python.exe scripts/smoke_check.py
```

Post-deployment checklist against the production URL:

1. `GET /health` returns `{"status":"ok",...}` over HTTPS.
2. Dashboard login works; `GET /dashboard/overview` renders.
3. `GET /api/v1/admin/me` with the admin cookie returns
   the operator identity (401 when unauthenticated).
4. Enroll a **test** station, credit it, confirm the
   heartbeat shows `occupied` with correct
   `remaining_seconds`, then lock it and confirm the
   session ends (`admin_terminated`) and the lock command
   is acknowledged. Full scenario matrix:
   `docs/e2e-testing.md`.
5. Run a backup and a restore drill (§8).

## 12. Security limitations and features not implemented

**Verified limitations (as of this guide):**

- **No built-in TLS** — HTTPS requires a reverse proxy
  (§5). Plain HTTP is acceptable only on an isolated
  loopback/LAN segment with `ENVIRONMENT=development`.
- **No server-side admin-session revocation:** logout
  deletes the cookie, but a captured JWT remains valid
  until its 8-hour expiry. Rotating `SECRET_KEY` is the
  only way to invalidate all sessions at once.
- **No role-based access control:** the `admins.role`
  column exists (default `admin`) but every administrator
  has full access.
- **No rate limiting on the station API** (only admin
  login is throttled: 5 failures per 15 minutes per
  username; the client IP is recorded but is not part of
  the throttle key). Mitigation: keep the API on the
  shop LAN behind the firewall (§7).
- **No audit-log retention or rotation policy** —
  `audit_events` grows unbounded; plan periodic
  archival.
- **`SERVER_HOST`/`SERVER_PORT` are not consumed** —
  binding is via uvicorn flags (§2, §4). Proposed
  follow-up: wire these settings into the startup path
  or remove them to avoid operator confusion.
- SQLite single-writer limits write concurrency
  (adequate for one shop; see `docs/architecture.md`).

**Not implemented at all (out of scope for this
milestone):** physical coin-slot hardware, kiosk
lockdown, forced shutdown, watchdog, multi-shop
federation, and public WAN deployment hardening.

## Reference: verified routes

- `GET /health` — liveness.
- `GET /` — redirects to `/dashboard/overview`.
- Dashboard (cookie auth + CSRF on state changes):
  `/dashboard/login`, `/dashboard/overview`,
  `/dashboard/stations`, `/dashboard/stations/{code}`,
  `/dashboard/sessions`, `/dashboard/ledger`,
  `/dashboard/audit`.
- Station API (`X-Api-Version: 1` + bearer token):
  `POST /api/v1/stations/register`,
  `POST /api/v1/stations/{code}/heartbeat`,
  `POST /api/v1/stations/{code}/commands/{id}/ack`.
- Admin API (Bearer JWT or cookie):
  `POST /api/v1/admin/login|logout`, `GET
  /api/v1/admin/me`, `POST/GET /api/v1/admin/stations`,
  `POST /api/v1/admin/stations/{code}/rotate-token|
  revoke|activate|lock`, `GET
  /api/v1/admin/sessions|ledger|audit`,
  `POST /api/v1/admin/ledger/credits`.

Full contract details: `docs/protocol.md`. Security
design: `docs/security.md`. End-to-end test evidence:
`docs/e2e-testing.md`.
