# Security Design

## Threat model

- Station clients are on the shop LAN but must not be able to
  forge each other's identity or self-award time.
- Coin-acceptor integrations may retry requests (network
  hiccups); retries must never double-credit.
- The dashboard is used by the operator from the LAN; session
  hijacking and CSRF must be mitigated.
- No component phones home; the system operates fully offline.

## Station identity

- Enrollment requires a server-side **enrollment secret**
  (env `ENROLLMENT_SECRET`; generated once and persisted to
  `server_config` when unset). A bare registration request
  cannot claim an arbitrary station number.
- Each station receives a cryptographically random token
  (`secrets.token_urlsafe`). Only its **SHA-256 verifier** is
  stored; the plaintext token is shown exactly once.
- Comparison is constant-time (`hmac.compare_digest`).
- Tokens can be **rotated** (old token immediately invalid) and
  stations can be **revoked** (all authentication rejected
  while revoked).
- MAC addresses are informational metadata, never proof of
  identity.

## Administrator credentials

- **No default administrator and no default password exist.**
  The first administrator is provisioned explicitly:
  `python scripts/provision_admin.py --username root --password <strong>`.
- Passwords are hashed with **Argon2id**
  (time_cost=3, memory_cost=64 MiB, parallelism=4).
- Login failures are recorded; **5 failures within 15 minutes**
  per username block further attempts for the window. Unknown
  usernames are verified against a dummy hash so response time
  does not reveal existence, and errors are generic
  ("Invalid username or password").
- Administrator sessions are **HS256 JWTs** signed with
  `SECRET_KEY` (≥ 32 characters, required at startup), delivered
  as an **HttpOnly, SameSite=Lax** cookie
  (`pisonet_admin`) with an 8-hour expiry.

## CSRF

State-changing dashboard requests use **double-submit CSRF**:
a random token in a readable cookie (`pisonet_csrf`,
SameSite=Strict) must match the `_csrf` form field or the
`X-CSRF-Token` header. Mismatches are rejected with 403.

## Ledger integrity

- Every credit requires a caller-supplied **idempotency key**;
  uniqueness is enforced by a database UNIQUE constraint, so
  credits survive restarts and concurrent duplicates.
- The ledger row and the session time adjustment are written in
  **one transaction** — a failure anywhere leaves neither
  behind (no partial credit, no double charge).
- Same key + same payload → original record returned (200),
  no double credit.
- Same key + different payload → 409 conflict, audited, no
  credit applied.
- Ledger entries are immutable history; `payload_hash` stores
  the SHA-256 of the canonical JSON payload.

## Sessions

- At most one active session per station, enforced by a partial
  unique index (`idx_sessions_one_active`), not by application
  checks.
- Remaining time is computed server-side from persisted
  `granted_seconds` and `started_at`; client countdowns are
  never authoritative.
- Time is never silently reset: extension adds to
  `granted_seconds`; expiry/termination set `ended_at` with an
  explicit reason exactly once.

## Audit log

Security-relevant events (enrollment, auth failures, credential
rotation/revocation, logins, credits, conflicts, commands,
session termination) are appended to `audit_events`. Audit
records never contain passwords, tokens, or raw secrets.

## Protocol versioning

Every station API request must declare `X-Api-Version`. Unknown
versions are rejected with 400 so incompatible clients fail
loudly instead of being mis-interpreted.

## Cookies summary

| Cookie        | Purpose            | HttpOnly | SameSite | Secure in production |
|---------------|--------------------|----------|----------|----------------------|
| `pisonet_admin` | admin session JWT | yes      | Lax      | yes                  |
| `pisonet_csrf`  | double-submit CSRF| no       | Strict   | yes                  |

## Known operational notes

- `SECRET_KEY` and `ENROLLMENT_SECRET` must be kept
  confidential; `.env` is git-ignored.
- The SQLite file is the system of record; back it up with
  `scripts/backup_db.py` (uses the SQLite online backup API,
  safe under load) or filesystem snapshots.
