# End-to-End Verification

Reproducible verification of the complete PisoNet workflow:
server setup, station enrollment, authentication, heartbeat
and recovery, session lifecycle, administrative lock, command
delivery, billing ledger, admin security, and restart
persistence.

This document distinguishes three test layers:

- **Automated** — pytest (server, 98 tests) and xUnit
  (client, 71 tests). Runs in CI (`.github/workflows/ci.yml`).
- **Live integration** — the same workflow executed over real
  HTTP against an isolated, disposable server instance.
- **Manual-only** — scenarios that require physical hardware,
  a real network partition, or interactive UI inspection.
  These are marked **NOT TESTED** below; nothing in this
  document claims they were exercised.

All testing uses disposable databases and test credentials.
No production station, production ledger, or production
administrator account is involved.

## Test environment

Server (Python 3.12, FastAPI):

```powershell
# isolated, disposable database
$env:SECRET_KEY = "<random 64-hex test key>"
$env:ENROLLMENT_SECRET = "smoke-enrollment-secret"
$env:DATABASE_URL = "sqlite:///./pisonet-e2e-test.db"
$env:ENVIRONMENT = "development"
$env:STATION_HEARTBEAT_TIMEOUT = "30"

.venv\Scripts\python.exe -m app.db.migrate --upgrade
.venv\Scripts\python.exe scripts/provision_admin.py --username root --password <test-password>
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8123
```

Client (.NET 10):

```powershell
dotnet build client\PisoNet.Client.slnx
dotnet test client\PisoNet.Client.slnx --no-build
```

Cleanup: stop the server and delete `pisonet-e2e-test.db`.
The database is the only state; everything is persisted there.

## Scenario matrix

### 1. Initial server setup and configuration — PASS

- **Prerequisites:** Python 3.12+, pip, writable directory.
- **Actions:** create venv, `pip install -e ".[dev]"`, run
  migrations, provision the first administrator, start uvicorn.
- **Expected:** migrations apply once and are repeatable; the
  server refuses to start without a ≥32-char `SECRET_KEY`;
  provisioning fails when an administrator already exists.
- **Actual:** live run applied migration `[1]` and provisioned
  `root` (id=1). Automated: `tests/test_config.py` (7 tests),
  `tests/test_migrations.py` (7 tests) — including
  `test_missing_secret_key_raises`, `test_fresh_upgrade_applies_initial_schema`,
  `test_upgrade_is_repeatable`, `test_database_newer_than_code_fails_loudly`.
- **Cleanup:** none (disposable DB).

### 2. Station enrollment — PASS

- **Actions:** `POST /api/v1/stations/register` with the
  enrollment secret; with a wrong, short, or empty secret; with
  an invalid `station_code`; twice with the same code.
- **Expected:** `201` with a one-time token (only the SHA-256
  verifier is stored); `403` for a wrong secret (audited);
  `422` for short/empty secret or invalid code; `409` for a
  duplicate code.
- **Actual:** live — `201` (token returned once), `403`
  (`Invalid enrollment secret`), `409`, and `422` for
  `short`, `""`, and `"PC 01"` (space not allowed).
  Automated: `tests/test_stations.py` (12 tests) and
  `tests/test_e2e.py::test_register_rejects_short_enrollment_secret`,
  `test_register_rejects_empty_enrollment_secret`,
  `test_register_rejects_invalid_station_code`.

### 3. Station authentication and API version enforcement — PASS

- **Actions:** requests without `X-Api-Version`, with an
  unsupported version, without a bearer token, and with a wrong
  token.
- **Expected:** `400` (missing/unsupported version), `401`
  (missing/wrong/revoked credentials), `200` for a valid token.
- **Actual:** live — `400` (`Missing required header
  X-Api-Version`), `401` (`Invalid or revoked station
  credentials`) for both missing and wrong tokens; every 401 is
  audited as `station.auth_failure`. Automated:
  `tests/test_api.py` (version header, unsupported version,
  bearer required, wrong token), `tests/test_stations.py`
  (`test_authenticate_accepts_valid_token_only`,
  `test_rotation_invalidates_old_token`,
  `test_revoked_station_cannot_authenticate`).

### 4. Heartbeat success, network failure, recovery, unauthorized — PASS

- **Actions:** heartbeat while available; credit time and
  heartbeat again; stop heartbeating past the 30 s timeout;
  heartbeat again.
- **Expected:** `available`/`locked` with no session; then
  `occupied`/`unlocked` with server-computed
  `remaining_seconds`; then the operator view reports `offline`;
  after a fresh heartbeat the station recovers to `available`.
  The heartbeat never creates sessions or awards time.
- **Actual:** live — `available` → `occupied` (session with
  `remaining_seconds`), `offline` after 31 s without a
  heartbeat, `available` again after the next heartbeat.
  Automated: `tests/test_heartbeat.py` (5 tests, including
  `test_heartbeat_never_creates_sessions_or_awards_time`,
  `test_heartbeat_sweep_expires_elapsed_session`,
  `test_heartbeat_reports_offline_when_stale`). Client-side
  reconnection (drop, backoff, recovery) is covered by the
  .NET `HeartbeatServiceTests` (scripted HTTP failures).
- **NOT TESTED:** a physical network cable unplug; only
  scripted failures were exercised.

### 5. Session start, uniqueness, countdown, expiration, termination — PASS

- **Actions:** credit time (creates the session); credit again
  (extends the same session); attempt a second concurrent
  session; let the time elapse; terminate administratively.
- **Expected:** at most one active session per station
  (database-enforced partial unique index); remaining time is
  always server-computed from `granted_seconds` and
  `started_at`; elapsed sessions are swept with reason
  `expired`; admin termination uses `admin_terminated`;
  extension adds to `granted_seconds` and never resets time.
- **Actual:** live — a 2-second session was swept on the next
  heartbeat (`session: null`, state back to `available`).
  Automated: `tests/test_sessions.py` (7 tests, including
  `test_create_session_and_duplicate_prevented`,
  `test_remaining_time_is_server_authoritative`,
  `test_expire_stale_sessions_ends_only_elapsed_sessions`).
  Client countdown interpolation is covered by the .NET
  `SessionCountdownTests`.
- **NOT TESTED:** the interactive visual countdown rendering
  in the WinForms client (no UI automation exists; the
  countdown logic itself is unit-tested).

### 6. Admin/session lock behavior and recovery — PASS

- **Actions:** credit time, then `POST /api/v1/admin/stations/{code}/lock`.
- **Expected:** the active session is terminated
  (`admin_terminated`), a `lock` command is queued, the
  station returns to `available` with zero remaining time, and
  the next heartbeat delivers the lock command.
- **Actual:** live — after lock, the station list showed
  `available`/`locked` with `remaining_seconds: 0`, and the
  station heartbeat returned the pending `lock` command.
  Automated: `tests/test_api.py::test_admin_lock_station_ends_session_and_queues_command`,
  `tests/test_dashboard.py::test_web_lock_requires_csrf_then_succeeds`.

### 7. Command creation, TTL expiration, acknowledgement, idempotency — PASS

- **Actions:** queue a command; deliver via heartbeat;
  acknowledge; re-acknowledge; have another station attempt to
  acknowledge it; queue a second command of the same type.
- **Expected:** only the owning station may acknowledge
  (`404` otherwise); repeat acknowledgement is `404`; a new
  command of the same type replaces the outstanding one;
  commands expire after 300 s and are purged.
- **Actual:** live — cross-station acknowledgement returned
  `404` (`Command not found or already acknowledged`), the
  owning station's acknowledgement returned
  `{"acknowledged":true,...}`, and the command no longer
  appeared in the next heartbeat. Automated:
  `tests/test_stations.py` (`test_command_queue_delivery_expiry_and_ack`,
  `test_expired_commands_are_purged`,
  `test_queue_replaces_outstanding_command_of_same_type`) and
  `tests/test_e2e.py::test_cross_station_command_ack_is_isolated`.
- **NOT TESTED (live):** the 300 s wall-clock TTL expiry —
  waiting five minutes per run is impractical; it is covered
  by the automated tests above using injected clocks.

### 8. Billing ledger atomicity, duplicates, conflicts, reconciliation — PASS

- **Actions:** credit a station; replay the same idempotency
  key with the same payload; replay it with a different
  payload; list the ledger.
- **Expected:** `201` for a new credit (ledger row and session
  adjustment commit atomically); `200` with `idempotent: true`
  and no double credit on replay; `409` for a conflicting
  payload (audited as `ledger.idempotency_conflict`); `404`
  for an unknown station.
- **Actual:** live — `201` (entry 1, 5000c/1800s), replay
  `200` with `idempotent:true` and unchanged
  `granted_seconds: 1800`, conflict `409`. Automated:
  `tests/test_ledger.py` (8 tests, including
  `test_credit_creates_ledger_entry_and_session_together`,
  `test_replay_same_key_and_payload_is_idempotent`,
  `test_replay_with_different_payload_is_rejected_and_audited`,
  `test_failed_credit_leaves_no_partial_state`).

### 9. Admin login, session security, CSRF protection, audit records — PASS

- **Actions:** provision the first admin; log in; access
  `/api/v1/admin/me`; log out; log in with a wrong password;
  exceed the failure limit; submit the dashboard login form
  without/with a wrong CSRF token; read the audit log.
- **Expected:** no default administrator exists; passwords are
  Argon2id; login sets an HttpOnly `pisonet_admin` cookie;
  wrong credentials return a generic `401`; 5 failures within
  15 minutes per username trigger `429`; dashboard forms
  require a double-submit CSRF token; every security-relevant
  event is written to the audit log.
- **Actual:** live — login `200` with cookie, dashboard
  anonymous access redirected (302) to login, the login page
  issued the `pisonet_csrf` cookie, the form login succeeded
  only with a valid CSRF token, and the audit log contained
  `admin.provisioned`, `admin.login_succeeded`,
  `station.enrollment_rejected`, `station.auth_failure`,
  `ledger.credited`, `ledger.idempotency_conflict`,
  `session.terminated`, and `command.queued`. Automated:
  `tests/test_admin_auth.py` (9 tests),
  `tests/test_dashboard.py` (CSRF), `tests/test_security.py`
  (Argon2id, JWT, constant-time comparison).

### 10. Restart/recovery behavior and database persistence — PASS

- **Actions:** run the workflow, stop the server process,
  restart it against the same database file, re-authenticate,
  and read the station, ledger, and session history.
- **Expected:** all state is database-backed; nothing is held
  in process memory, so stations, ledger entries, and session
  history (including end reasons) survive a full restart.
- **Actual:** live — after a full process restart against the
  same database: admin login `200`; all 5 stations listed;
  3 ledger entries intact (`smoke-1`, `e2e-live-expiry`,
  `e2e-live-expiry-2`); 3 sessions intact with end reasons
  `expired`, `expired`, `admin_terminated`. Automated:
  `tests/test_sessions.py::test_session_state_survives_a_new_connection`,
  `tests/test_migrations.py` (schema tracking).

## Reproducing the live workflow

With the isolated server running (see *Test environment*):

```powershell
# Full operator flow over real HTTP (health, register,
# heartbeat, login, idempotent credit, replay, conflict,
# station list, lock, dashboard + CSRF):
.venv\Scripts\python.exe scripts/smoke_check.py
```

Expected final line: `SMOKE OK` (16 checks).

The extended live scenarios (schema validation, 401
responses, real-time session expiry, offline detection and
recovery, cross-station acknowledgement, audit contents,
restart persistence) were executed with a throwaway httpx
script against the same isolated instance; every check
returned OK (23/23) and the restart check returned
`RESTART PERSISTENCE OK`. Each of those behaviors is also
asserted by the automated suites named above, so CI covers
them on every push.

## Results summary

| Layer | Command | Result |
|---|---|---|
| Server automated | `.venv\Scripts\python.exe -m pytest` | 98 passed (25.6 s) |
| Client automated | `dotnet test client\PisoNet.Client.slnx --no-build` | 71 passed (0.4 s) |
| Client build | `dotnet build client\PisoNet.Client.slnx` | 0 warnings, 0 errors |
| Live integration | `scripts/smoke_check.py` | SMOKE OK (16/16) |
| Live extended | throwaway httpx script (isolated server) | 23/23 OK |
| Restart persistence | restart + httpx history check | OK |

## NOT TESTED / BLOCKED (explicit gaps)

- **Physical coin-slot hardware** (GPIO, debounce, level
  shifting) — not implemented; no hardware available.
- **Kiosk lockdown, forced shutdown, watchdog** — not
  implemented; explicitly out of scope for this milestone.
- **Interactive WinForms UI** (visual countdown, lock banner,
  settings dialogs) — no UI automation; client logic is
  covered by 71 automated tests, but visual inspection is a
  manual step.
- **Physical network partition** — simulated via scripted HTTP
  failures in the .NET client tests only.
- **Command TTL wall-clock expiry (300 s)** — covered by
  automated tests with injected clocks; not exercised live.
- **Production readiness** (HTTPS, reverse proxy, multi-user
  concurrency, backup/restore drill) — out of scope; see
  `docs/setup.md` and `docs/security.md`.

## Defects found and fixed

None. All scenarios behaved as documented. The six new
automated tests in `tests/test_e2e.py` close coverage gaps
(short/empty enrollment secret, invalid station code,
heartbeat version enforcement, cross-station command
isolation, and the full chained operator workflow); they are
part of the 98-test suite and run in CI.
