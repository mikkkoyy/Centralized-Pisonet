# MKY PisoNet Central

Centralized management server for Philippine PisoNet (coin-operated internet café) networks.

**Status:** early development — PISO-002 server foundation. See "Verified vs planned" below.

## What this is

A central server that manages Windows station PCs over the LAN:

- Station registration with per-station credentials (not a shared API key)
- Authenticated heartbeat protocol with server-authoritative session state
- Persistent sessions with server-computed remaining time
- Idempotent coin/payment ledger (database-enforced uniqueness)
- Administrator authentication (Argon2id) with a dark Jinja2/HTMX dashboard
- Versioned, explicit database migrations with tracking

The Windows station client, physical coin-slot hardware integration, and
relay control are **not** part of this milestone (see docs/architecture.md).

## Quick start (development)

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"

# generate secrets first
$env:SECRET_KEY = [System.Security.Cryptography.RandomNumberGenerator]::new() # or:
python -c "import secrets; print(secrets.token_hex(32))"   # SECRET_KEY
python -c "import secrets; print(secrets.token_hex(32))"   # ENROLLMENT_SECRET

# provision the first administrator (creates the admin account)
.venv\Scripts\python.exe -m scripts.provision_admin --username ops --password 'choose-a-strong-password'

# run migrations and start the server
.venv\Scripts\python.exe -m app.db.migrate --upgrade
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Dashboard: http://127.0.0.1:8000/  ·  API docs: http://127.0.0.1:8000/api/v1/docs

## Verified vs planned

**Verified in this milestone (tested):** configuration validation, versioned
migrations, station enrollment/registration/heartbeat authentication, session
lifecycle and restart recovery, idempotent ledger (duplicate + conflicting
retries), admin login/logout/throttling/CSRF, dashboard pages, audit logging.

**Planned (later milestones):** Windows station client with lock screen,
GPIO coin-slot controller with debounce and level shifting, revenue reports.

## Project layout

- `app/` — FastAPI server (core, db, models, schemas, api, services, web)
- `tests/` — pytest suite (isolated temporary databases)
- `docs/` — architecture, protocol, security, setup documentation
- `scripts/` — admin provisioning and database backup utilities

Licensed under MIT (see LICENSE). Original implementation; architectural study
of the Pisonex reference only — no third-party source code is incorporated.
