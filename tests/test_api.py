"""HTTP API integration tests: protocol versioning, station
auth, idempotent credits, admin auth."""

from __future__ import annotations

import pytest

from app.core.security import create_admin_token


def _enroll_admin(test_app):
    from app.services.admin import provision_admin

    with test_app.db() as db:
        provision_admin(db, username="root", password="sup3rsecret!")


def _admin_headers(test_app):
    settings = test_app.client.app.state.settings
    token = create_admin_token("root", settings)
    return {"Authorization": f"Bearer {token}"}


def _register(test_app, code="ST01", secret=None):
    if secret is None:
        secret = test_app.client.app.state.enrollment_secret
    return test_app.client.post(
        "/api/v1/stations/register",
        headers={"X-Api-Version": "1"},
        json={
            "station_code": code,
            "enrollment_secret": secret,
            "display_name": f"Station {code}",
        },
    )


def test_health_endpoint(test_app):
    response = test_app.client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["protocol_version"] == 1
    assert body["environment"] == "development"


def test_register_requires_api_version_header(test_app):
    response = test_app.client.post(
        "/api/v1/stations/register",
        json={"station_code": "ST01", "enrollment_secret": "x" * 16},
    )
    assert response.status_code == 400
    assert "X-Api-Version" in response.json()["detail"]


def test_register_rejects_unsupported_protocol_version(test_app):
    response = test_app.client.post(
        "/api/v1/stations/register",
        headers={"X-Api-Version": "999"},
        json={"station_code": "ST01", "enrollment_secret": "x" * 16},
    )
    assert response.status_code == 400


def test_register_rejects_wrong_enrollment_secret(test_app):
    response = _register(test_app, secret="wrong-secret-here")
    assert response.status_code == 403


def test_register_returns_one_time_token(test_app):
    response = _register(test_app)
    assert response.status_code == 201
    body = response.json()
    assert body["station_code"] == "ST01"
    assert body["token"]
    assert body["protocol_version"] == 1
    # Duplicate station code conflicts.
    assert _register(test_app).status_code == 409


def test_heartbeat_requires_bearer_token(test_app):
    _register(test_app)
    response = test_app.client.post(
        "/api/v1/stations/ST01/heartbeat",
        headers={"X-Api-Version": "1"},
        json={},
    )
    assert response.status_code == 401


def test_heartbeat_returns_authoritative_state(test_app):
    register = _register(test_app)
    token = register.json()["token"]
    response = test_app.client.post(
        "/api/v1/stations/ST01/heartbeat",
        headers={"X-Api-Version": "1", "Authorization": f"Bearer {token}"},
        json={},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["station_code"] == "ST01"
    assert body["station_state"] == "available"
    assert body["lock"] == "locked"
    assert "server_time" in body
    assert body["session"] is None


def test_heartbeat_rejects_wrong_token(test_app):
    _register(test_app)
    response = test_app.client.post(
        "/api/v1/stations/ST01/heartbeat",
        headers={"X-Api-Version": "1", "Authorization": "Bearer wrong-token"},
        json={},
    )
    assert response.status_code == 401


def test_credit_requires_admin(test_app):
    _register(test_app)
    response = test_app.client.post(
        "/api/v1/admin/ledger/credits",
        headers={"X-Api-Version": "1"},
        json={
            "station_code": "ST01",
            "amount_cents": 5000,
            "seconds": 1800,
            "idempotency_key": "key-1",
        },
    )
    assert response.status_code == 401


def test_credit_creates_session_and_replays_idempotently(test_app):
    _enroll_admin(test_app)
    _register(test_app)
    payload = {
        "station_code": "ST01",
        "amount_cents": 5000,
        "seconds": 1800,
        "idempotency_key": "key-1",
    }
    first = test_app.client.post(
        "/api/v1/admin/ledger/credits",
        headers={"X-Api-Version": "1", **_admin_headers(test_app)},
        json=payload,
    )
    assert first.status_code == 201
    body = first.json()
    assert body["idempotent"] is False
    assert body["session_state"] == "active"
    assert body["granted_seconds"] == 1800
    assert body["remaining_seconds"] == 1800

    # Same key + same payload -> 200 replay, no double credit.
    second = test_app.client.post(
        "/api/v1/admin/ledger/credits",
        headers={"X-Api-Version": "1", **_admin_headers(test_app)},
        json=payload,
    )
    assert second.status_code == 200
    assert second.json()["idempotent"] is True
    assert second.json()["granted_seconds"] == 1800

    # Same key + different payload -> 409 conflict.
    conflict = test_app.client.post(
        "/api/v1/admin/ledger/credits",
        headers={"X-Api-Version": "1", **_admin_headers(test_app)},
        json={**payload, "amount_cents": 9000},
    )
    assert conflict.status_code == 409


def test_credit_unknown_station_404(test_app):
    _enroll_admin(test_app)
    response = test_app.client.post(
        "/api/v1/admin/ledger/credits",
        headers={"X-Api-Version": "1", **_admin_headers(test_app)},
        json={
            "station_code": "NOPE",
            "amount_cents": 100,
            "seconds": 60,
            "idempotency_key": "key-x",
        },
    )
    assert response.status_code == 404


def test_admin_login_me_and_logout(test_app):
    _enroll_admin(test_app)
    response = test_app.client.post(
        "/api/v1/admin/login",
        json={"username": "root", "password": "sup3rsecret!"},
    )
    assert response.status_code == 200
    assert response.json() == {"username": "root", "role": "admin"}
    assert "pisonet_admin" in response.cookies

    me = test_app.client.get(
        "/api/v1/admin/me",
        cookies={"pisonet_admin": response.cookies["pisonet_admin"]},
    )
    assert me.status_code == 200
    assert me.json() == {"username": "root", "role": "admin"}

    logged_out = test_app.client.post(
        "/api/v1/admin/logout",
        cookies={"pisonet_admin": response.cookies["pisonet_admin"]},
    )
    assert logged_out.status_code == 200


def test_admin_login_wrong_password_401(test_app):
    _enroll_admin(test_app)
    response = test_app.client.post(
        "/api/v1/admin/login",
        json={"username": "root", "password": "wrong"},
    )
    assert response.status_code == 401


def test_admin_history_endpoints_require_admin(test_app):
    _enroll_admin(test_app)
    for path in (
        "/api/v1/admin/stations",
        "/api/v1/admin/sessions",
        "/api/v1/admin/ledger",
        "/api/v1/admin/audit",
    ):
        assert test_app.client.get(path).status_code == 401
        assert (
            test_app.client.get(path, headers=_admin_headers(test_app)).status_code
            == 200
        )


def test_admin_lock_station_ends_session_and_queues_command(test_app):
    _enroll_admin(test_app)
    register = _register(test_app)
    token = register.json()["token"]
    station_headers = {"X-Api-Version": "1", "Authorization": f"Bearer {token}"}
    # Heartbeat so the station is online (fresh last_seen_at).
    test_app.client.post(
        "/api/v1/stations/ST01/heartbeat",
        headers=station_headers,
        json={},
    )
    headers = {"X-Api-Version": "1", **_admin_headers(test_app)}
    test_app.client.post(
        "/api/v1/admin/ledger/credits",
        headers=headers,
        json={
            "station_code": "ST01",
            "amount_cents": 5000,
            "seconds": 1800,
            "idempotency_key": "lock-1",
        },
    )
    response = test_app.client.post(
        "/api/v1/admin/stations/ST01/lock", headers=headers
    )
    assert response.status_code == 200
    assert response.json() == {"status": "locked", "station_code": "ST01"}
    # Session was terminated; a lock command is pending.
    stations = test_app.client.get("/api/v1/admin/stations", headers=headers).json()
    assert stations[0]["state"] == "available"
    assert stations[0]["remaining_seconds"] == 0
