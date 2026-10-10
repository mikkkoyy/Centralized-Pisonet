"""Live smoke check against a running server (default 127.0.0.1:8123).

Exercises the full operator flow over real HTTP:
health -> station register -> heartbeat -> admin login ->
idempotent credit -> replay -> conflict -> station list -> lock.
"""

from __future__ import annotations

import sys

import httpx

BASE = "http://127.0.0.1:8123"
ENROLLMENT_SECRET = "smoke-enrollment-secret"
ADMIN_USERNAME = "root"
ADMIN_PASSWORD = "smoke-admin-pass"

client = httpx.Client(base_url=BASE, timeout=10.0)


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "OK " if condition else "FAIL"
    print(f"[{status}] {label}" + (f" — {detail}" if detail else ""))
    if not condition:
        global failed
        failed = True


failed = False

# 1. Health
r = client.get("/health")
check("health", r.status_code == 200 and r.json()["status"] == "ok", r.text)

# 2. Protocol versioning is enforced
r = client.post(
    "/api/v1/stations/register",
    json={"station_code": "PC-01", "enrollment_secret": ENROLLMENT_SECRET},
)
check("register without X-Api-Version -> 400", r.status_code == 400, r.text)

# 3. Enrollment requires the server secret
r = client.post(
    "/api/v1/stations/register",
    headers={"X-Api-Version": "1"},
    json={"station_code": "PC-01", "enrollment_secret": "wrong-secret-here"},
)
check("register wrong secret -> 403", r.status_code == 403, r.text)

# 4. Enroll a station
r = client.post(
    "/api/v1/stations/register",
    headers={"X-Api-Version": "1"},
    json={
        "station_code": "PC-01",
        "enrollment_secret": ENROLLMENT_SECRET,
        "display_name": "PC 01",
    },
)
check("register -> 201", r.status_code == 201, r.text)
station_token = r.json()["token"]

# 5. Heartbeat with the station token
r = client.post(
    "/api/v1/stations/PC-01/heartbeat",
    headers={"X-Api-Version": "1", "Authorization": f"Bearer {station_token}"},
    json={},
)
body = r.json()
check(
    "heartbeat -> 200 available",
    r.status_code == 200
    and body["station_state"] == "available"
    and body["lock"] == "locked",
    r.text,
)

# 6. Admin login (cookie session)
r = client.post(
    "/api/v1/admin/login",
    json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
)
check("admin login -> 200 + cookie", r.status_code == 200 and "pisonet_admin" in r.cookies, r.text)

# 7. Credit creates a session
r = client.post(
    "/api/v1/admin/ledger/credits",
    json={
        "station_code": "PC-01",
        "amount_cents": 5000,
        "seconds": 1800,
        "idempotency_key": "smoke-1",
    },
)
body = r.json()
check(
    "credit -> 201, session active, 1800s",
    r.status_code == 201
    and body["idempotent"] is False
    and body["session_state"] == "active"
    and body["granted_seconds"] == 1800,
    r.text,
)

# 8. Idempotent replay
r = client.post(
    "/api/v1/admin/ledger/credits",
    json={
        "station_code": "PC-01",
        "amount_cents": 5000,
        "seconds": 1800,
        "idempotency_key": "smoke-1",
    },
)
body = r.json()
check(
    "credit replay -> 200 idempotent, no double credit",
    r.status_code == 200 and body["idempotent"] is True and body["granted_seconds"] == 1800,
    r.text,
)

# 9. Conflicting payload under the same key
r = client.post(
    "/api/v1/admin/ledger/credits",
    json={
        "station_code": "PC-01",
        "amount_cents": 9000,
        "seconds": 3600,
        "idempotency_key": "smoke-1",
    },
)
check("credit conflict -> 409", r.status_code == 409, r.text)

# 10. Station list reflects occupied state
r = client.get("/api/v1/admin/stations")
stations = r.json()
check(
    "station list -> occupied with remaining time",
    r.status_code == 200
    and stations[0]["state"] == "occupied"
    and 0 < stations[0]["remaining_seconds"] <= 1800,
    r.text,
)

# 11. Administrative lock ends the session and queues the command
r = client.post("/api/v1/admin/stations/PC-01/lock")
check("lock -> 200", r.status_code == 200 and r.json()["status"] == "locked", r.text)

r = client.get("/api/v1/admin/stations")
stations = r.json()
check(
    "after lock -> available, no remaining time",
    stations[0]["state"] == "available" and stations[0]["remaining_seconds"] == 0,
    r.text,
)

# 12. Dashboard pages require auth; CSRF cookie is issued
# (fresh clients: the API client above already holds the admin cookie)
anon = httpx.Client(base_url=BASE, timeout=10.0)
r = anon.get("/dashboard/overview", follow_redirects=False)
check("dashboard anonymous -> 302 login", r.status_code == 302, r.text)
r = anon.get("/dashboard/login")
check(
    "login page sets CSRF cookie",
    r.status_code == 200 and "pisonet_csrf" in r.cookies,
    str(dict(r.headers)),
)

# 13. Dashboard login flow (double-submit CSRF)
browser = httpx.Client(base_url=BASE, timeout=10.0)
r = browser.get("/dashboard/login")
csrf = r.cookies["pisonet_csrf"]
r = browser.post(
    "/dashboard/login",
    data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD, "_csrf": csrf},
    follow_redirects=False,
)
check("dashboard login -> 302 + admin cookie", r.status_code == 302 and "pisonet_admin" in r.cookies, r.text)

r = browser.get("/dashboard/overview", follow_redirects=False)
check("dashboard overview -> 200", r.status_code == 200 and "MKY PisoNet Central" in r.text, r.text[:200])

print()
if failed:
    print("SMOKE FAILED")
    sys.exit(1)
print("SMOKE OK")
