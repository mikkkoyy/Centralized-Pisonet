"""End-to-end workflow tests: the complete operator/station
flow chained over the real HTTP stack, plus contract-gap
checks (schema validation, version enforcement on heartbeat,
cross-station command isolation)."""

from __future__ import annotations


def _enroll_admin(test_app):
    from app.services.admin import provision_admin

    with test_app.db() as db:
        provision_admin(db, username="root", password="sup3rsecret!")


def _admin_headers(test_app):
    from app.core.security import create_admin_token

    settings = test_app.client.app.state.settings
    token = create_admin_token("root", settings)
    return {"X-Api-Version": "1", "Authorization": f"Bearer {token}"}


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


def _heartbeat(test_app, code, token):
    return test_app.client.post(
        f"/api/v1/stations/{code}/heartbeat",
        headers={"X-Api-Version": "1", "Authorization": f"Bearer {token}"},
        json={},
    )


def test_full_operator_workflow_end_to_end(test_app):
    """Enroll -> heartbeat -> credit -> occupied -> admin lock
    -> lock command delivered -> acknowledged -> clean state."""
    _enroll_admin(test_app)
    admin = _admin_headers(test_app)

    register = _register(test_app, code="PC01")
    assert register.status_code == 201
    token = register.json()["token"]

    # Station online, no session: available and locked.
    hb = _heartbeat(test_app, "PC01", token)
    assert hb.status_code == 200
    body = hb.json()
    assert body["station_state"] == "available"
    assert body["lock"] == "locked"
    assert body["session"] is None
    assert body["commands"] == []

    # Credit creates the session atomically.
    credit = test_app.client.post(
        "/api/v1/admin/ledger/credits",
        headers=admin,
        json={
            "station_code": "PC01",
            "amount_cents": 5000,
            "seconds": 1800,
            "idempotency_key": "e2e-1",
        },
    )
    assert credit.status_code == 201
    assert credit.json()["session_state"] == "active"

    # Station now occupied/unlocked with server-computed remaining time.
    hb = _heartbeat(test_app, "PC01", token)
    body = hb.json()
    assert body["station_state"] == "occupied"
    assert body["lock"] == "unlocked"
    assert body["session"]["state"] == "active"
    assert body["session"]["granted_seconds"] == 1800
    assert 0 < body["session"]["remaining_seconds"] <= 1800

    # Administrative lock terminates the session and queues a lock command.
    locked = test_app.client.post("/api/v1/admin/stations/PC01/lock", headers=admin)
    assert locked.status_code == 200

    hb = _heartbeat(test_app, "PC01", token)
    body = hb.json()
    assert body["session"] is None
    assert body["lock"] == "locked"
    commands = body["commands"]
    assert len(commands) == 1
    assert commands[0]["command_type"] == "lock"
    assert commands[0]["expires_at"] > body["server_time"]

    # The station applies the command and acknowledges it.
    command_id = commands[0]["id"]
    ack = test_app.client.post(
        f"/api/v1/stations/PC01/commands/{command_id}/ack",
        headers={"X-Api-Version": "1", "Authorization": f"Bearer {token}"},
        json={},
    )
    assert ack.status_code == 200
    assert ack.json() == {"acknowledged": True, "command_id": command_id}

    # Acknowledged command is no longer delivered; repeat ack is 404.
    hb = _heartbeat(test_app, "PC01", token)
    assert hb.json()["commands"] == []
    repeat = test_app.client.post(
        f"/api/v1/stations/PC01/commands/{command_id}/ack",
        headers={"X-Api-Version": "1", "Authorization": f"Bearer {token}"},
        json={},
    )
    assert repeat.status_code == 404


def test_cross_station_command_ack_is_isolated(test_app):
    """A station cannot acknowledge another station's command."""
    _enroll_admin(test_app)
    admin = _admin_headers(test_app)

    first = _register(test_app, code="PC01")
    second = _register(test_app, code="PC02")
    assert first.status_code == 201
    assert second.status_code == 201

    locked = test_app.client.post("/api/v1/admin/stations/PC01/lock", headers=admin)
    assert locked.status_code == 200

    hb = _heartbeat(test_app, "PC01", first.json()["token"])
    command_id = hb.json()["commands"][0]["id"]

    # PC02 tries to acknowledge PC01's command.
    ack = test_app.client.post(
        f"/api/v1/stations/PC02/commands/{command_id}/ack",
        headers={
            "X-Api-Version": "1",
            "Authorization": f"Bearer {second.json()['token']}",
        },
        json={},
    )
    assert ack.status_code == 404

    # The owning station can still acknowledge it.
    ack = test_app.client.post(
        f"/api/v1/stations/PC01/commands/{command_id}/ack",
        headers={"X-Api-Version": "1", "Authorization": f"Bearer {first.json()['token']}"},
        json={},
    )
    assert ack.status_code == 200


def test_register_rejects_short_enrollment_secret(test_app):
    response = test_app.client.post(
        "/api/v1/stations/register",
        headers={"X-Api-Version": "1"},
        json={"station_code": "ST01", "enrollment_secret": "short"},
    )
    assert response.status_code == 422


def test_register_rejects_empty_enrollment_secret(test_app):
    response = test_app.client.post(
        "/api/v1/stations/register",
        headers={"X-Api-Version": "1"},
        json={"station_code": "ST01", "enrollment_secret": ""},
    )
    assert response.status_code == 422


def test_register_rejects_invalid_station_code(test_app):
    response = test_app.client.post(
        "/api/v1/stations/register",
        headers={"X-Api-Version": "1"},
        json={"station_code": "PC 01", "enrollment_secret": "x" * 16},
    )
    assert response.status_code == 422


def test_heartbeat_requires_api_version_header(test_app):
    _register(test_app)
    response = test_app.client.post(
        "/api/v1/stations/ST01/heartbeat",
        json={},
    )
    assert response.status_code == 400
    assert "X-Api-Version" in response.json()["detail"]
