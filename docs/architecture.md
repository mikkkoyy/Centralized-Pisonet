# Architecture

MKY PisoNet Central is a centralized management server for a
single PisoNet shop (LAN deployment). One server process is the
authority for station identity, session time, and credits;
station clients (the per-PC timer/lock applications) poll it.

## Technology choices

- **Python 3.12 + FastAPI** — async HTTP server and API.
- **SQLAlchemy 2.0 + SQLite** — persistent storage. File-based
  only (in-memory is rejected at startup); WAL mode and
  `foreign_keys=ON` are enforced on every connection.
- **Jinja2 + HTMX + hand-written CSS** — server-rendered dark
  dashboard. No JavaScript build step; `htmx.min.js` is vendored
  at `app/static/js/`.
- **Argon2id** (argon2-cffi) for administrator passwords.
- **SHA-256 verifiers** for station tokens and the enrollment
  secret (raw values are never persisted).
- **HS256 JWT** for administrator sessions.

## Process layout

```
app/
  core/        config, security primitives, protocol constants
  db/          engine, migration runner, versioned migrations
  models/      SQLAlchemy ORM models (pure schema, no logic)
  schemas/     Pydantic request/response models
  services/    all business logic (station, session, ledger,
               admin, audit, time)
  api/v1/      station + administrator HTTP API (JSON)
  web/         dashboard routes (HTML), auth + CSRF dependencies
  templates/   Jinja2 templates
  static/      CSS and vendored htmx
scripts/       operator CLI (provision admin, backup, smoke check)
tests/         pytest suite (unit + HTTP integration)
docs/          this documentation set
```

## Request flow

1. Station clients authenticate with a **per-station bearer
   token** (`Authorization: Bearer <token>`). Only the token's
   SHA-256 verifier is stored.
2. The API dependency `require_station` authenticates the
   station, records failures in the audit log, and rejects
   revoked stations.
3. Services do all work inside a database transaction; the
   request-scoped session is committed or rolled back per
   request. Nothing billing-related is held in process memory.
4. The dashboard uses a separate **HttpOnly JWT cookie**
   (`pisonet_admin`) and double-submit CSRF
   (`pisonet_csrf` cookie + `_csrf` form field or
   `X-CSRF-Token` header).

## Data model

- `stations` — identity, token verifier, heartbeat state,
  `is_active` (revocation flag).
- `sessions` — granted time and start time; `ended_at` +
  `end_reason` (`expired`, `admin_terminated`, `completed`).
  A partial unique index (`idx_sessions_one_active`) enforces
  at most one active session per station.
- `ledger_entries` — immutable credit records with a UNIQUE
  `idempotency_key` and a `payload_hash` of the canonical
  payload.
- `admins`, `admin_login_attempts` — Argon2id credentials and
  throttling state.
- `audit_events` — append-only security-relevant events.
- `server_config` — runtime configuration (persisted
  enrollment secret).
- `station_commands` — pending commands (lock/unlock) with a
  300-second delivery deadline and acknowledgement.

## Time and money model

- All timestamps are **integer Unix epoch seconds (UTC)**. The
  server clock is the only authoritative time source; clients
  never supply billing time.
- All money is **integer cents** (`amount_cents`). No floats.
- Remaining session time is always computed server-side as
  `granted_seconds - (now - started_at)`.

## Restart behavior

Every piece of state is persisted in SQLite. Restarting the
server replays the same database: sessions, ledger, stations,
and audit history are all preserved. A background sweeper
(30-second interval) expires sessions whose time ran out even
when heartbeats are sparse.
