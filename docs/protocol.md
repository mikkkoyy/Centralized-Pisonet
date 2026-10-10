# Station/Client Protocol (v1)

All station API endpoints require the header:

```
X-Api-Version: 1
```

Requests with a missing or unsupported version are rejected with
HTTP 400 before any other processing. This lets incompatible
clients fail loudly instead of being mis-interpreted by a newer
server.

Base URL: `http://<server>:8000/api/v1`

## Authentication

Station requests authenticate with a per-station bearer token:

```
Authorization: Bearer <station-token>
```

Tokens are issued once at enrollment (or by an administrator
via pre-registration/rotation) and are stored server-side only
as SHA-256 verifiers. MAC addresses are recorded as metadata
and are **never** accepted as proof of identity.

## Endpoints

### POST /api/v1/stations/register

Enroll a new station. Requires the server enrollment secret
(issued out of band to the operator).

Request:

```json
{
  "station_code": "PC-01",
  "enrollment_secret": "<enrollment secret>",
  "display_name": "PC 01",
  "mac_address": "AA:BB:CC:DD:EE:FF"
}
```

- `201 Created` → `{station_id, station_code, token, protocol_version, enrolled_at}`
  The plaintext token is returned **exactly once**.
- `403 Forbidden` — invalid enrollment secret (audited).
- `409 Conflict` — station code already taken.

### POST /api/v1/stations/{code}/heartbeat

Authenticated poll (bearer token). The heartbeat **never**
creates sessions or awards time; it only refreshes `last_seen_at`
and returns server-authoritative state.

Response `200 OK`:

```json
{
  "station_code": "PC-01",
  "protocol_version": 1,
  "server_time": 1791676522,
  "station_state": "available",
  "lock": "locked",
  "session": {
    "session_id": 1,
    "state": "active",
    "granted_seconds": 1800,
    "started_at": 1791676522,
    "remaining_seconds": 1500
  },
  "commands": [
    {"id": 3, "command_type": "lock", "payload": null, "expires_at": 1791676822}
  ]
}
```

- `station_state`: `available` | `occupied` | `offline` | `revoked`
- `lock`: `locked` | `unlocked` (unlocked only while an
  unexpired session is active)
- `session` is present only while an active session with
  remaining time exists.
- `commands` lists unacknowledged, unexpired commands. The
  client applies them (e.g. locks the station) and acknowledges
  each one.

### POST /api/v1/stations/{code}/commands/{id}/ack

Acknowledge delivery of a pending command. Only the owning
station may acknowledge. `200` → `{acknowledged: true, command_id}`;
`404` when the command does not exist, belongs to another
station, or was already acknowledged.

Commands expire 300 seconds after being queued and are purged
on the next heartbeat.

## Status derivation

Server-side, per station:

| Condition                                        | state    | lock    |
|--------------------------------------------------|----------|---------|
| `is_active = false`                              | revoked  | locked  |
| last heartbeat older than the timeout (30 s)     | offline  | locked  |
| active session with remaining time > 0           | occupied | unlocked|
| otherwise                                        | available| locked  |

## Administrator API

All `/api/v1/admin/*` endpoints require an administrator:
either `Authorization: Bearer <admin JWT>` or the dashboard
session cookie.

- `POST /api/v1/admin/login` `{username, password}` → sets the
  `pisonet_admin` HttpOnly cookie. `401` on bad credentials,
  `429` when throttled (5 failures per 15 minutes per
  username).
- `POST /api/v1/admin/logout` — clears the cookie.
- `GET /api/v1/admin/me` — current administrator.
- `POST /api/v1/admin/stations` `{station_code, display_name}`
  — administrator-issued enrollment; returns a one-time token.
- `POST /api/v1/admin/stations/{code}/rotate-token` — rotate
  the station credential (old token immediately invalid).
- `POST /api/v1/admin/stations/{code}/revoke` / `activate` —
  disable/enable a station's credentials.
- `POST /api/v1/admin/stations/{code}/lock` — terminate the
  active session (reason `admin_terminated`) and queue a `lock`
  command.
- `GET /api/v1/admin/stations` — all stations with computed
  state.
- `GET /api/v1/admin/sessions?page=&limit=&station_id=` —
  paginated session history (`limit` ≤ 100).
- `GET /api/v1/admin/ledger?page=&limit=&station_id=` —
  paginated ledger history.
- `GET /api/v1/admin/audit?page=&limit=` — paginated audit log.
- `POST /api/v1/admin/ledger/credits` — see below.

### POST /api/v1/admin/ledger/credits

Credit a station with session time. Requires an idempotency
key supplied by the caller (e.g. the coin-acceptor transaction
ID).

Request:

```json
{
  "station_code": "PC-01",
  "amount_cents": 5000,
  "seconds": 1800,
  "idempotency_key": "txn-2026-10-10-0001",
  "reference": "optional free-form reference"
}
```

- `201 Created` — new credit; the ledger row and the session
  time adjustment commit atomically.
- `200 OK` — idempotent replay (same key, same payload); the
  original record is returned, no additional time is credited.
- `404 Not Found` — unknown station.
- `409 Conflict` — the key was already used with a different
  payload (audited as `ledger.idempotency_conflict`).
