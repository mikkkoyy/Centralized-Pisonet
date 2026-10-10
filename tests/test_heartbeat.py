"""Heartbeat semantics: server-authoritative state, no time awards,
and the expiry sweep that runs on every heartbeat."""

from __future__ import annotations

from app.services import session as session_service
from app.services import station as station_service
from app.services.ledger import credit, list_entries


def _enroll(db, code="STATION-01"):
    result = station_service.enroll_station(
        db,
        station_code=code,
        enrollment_secret="enroll-secret",
        provided_secret="enroll-secret",
    )
    db.commit()
    return result.station


def _heartbeat(db, station, clock):
    """The station heartbeat flow as executed by the API: refresh the
    heartbeat, sweep expired sessions, then derive authoritative state."""
    station_service.touch_heartbeat(db, station, "10.0.0.9", clock=clock)
    expired = session_service.expire_stale_sessions(db, now=clock())
    active = station_service.active_session_for(db, station.id)
    remaining = active.remaining_seconds(clock()) if active else 0
    status = station_service.compute_status(station, active, clock())
    return {"expired": expired, "active": active, "remaining": remaining, "status": status}


def test_heartbeat_never_creates_sessions_or_awards_time(db_session, clock):
    station = _enroll(db_session)
    for _ in range(3):
        result = _heartbeat(db_session, station, clock)
        assert result["active"] is None
        assert result["remaining"] == 0
    assert list_entries(db_session) == []
    assert session_service.get_active_session(db_session, station.id) is None


def test_heartbeat_reports_available_state(db_session, clock):
    station = _enroll(db_session)
    result = _heartbeat(db_session, station, clock)
    assert result["status"].state == "available"
    assert result["status"].lock == "locked"


def test_heartbeat_reports_occupied_state_with_remaining_time(db_session, clock):
    station = _enroll(db_session)
    station_service.touch_heartbeat(db_session, station, None, clock=clock)
    credit(
        db_session,
        station_code=station.station_code,
        amount_cents=1000,
        seconds=1800,
        idempotency_key="hb-1",
        clock=clock,
    )
    clock.advance(300)
    result = _heartbeat(db_session, station, clock)
    assert result["status"].state == "occupied"
    assert result["status"].lock == "unlocked"
    assert result["remaining"] == 1500
    assert result["active"].granted_seconds == 1800


def test_heartbeat_sweep_expires_elapsed_session(db_session, clock):
    station = _enroll(db_session)
    station_service.touch_heartbeat(db_session, station, None, clock=clock)
    credit(
        db_session,
        station_code=station.station_code,
        amount_cents=1000,
        seconds=60,
        idempotency_key="hb-2",
        clock=clock,
    )
    clock.advance(61)
    result = _heartbeat(db_session, station, clock)
    assert len(result["expired"]) == 1
    assert result["expired"][0].end_reason == "expired"
    assert result["active"] is None
    assert result["status"].state == "available"


def test_heartbeat_reports_offline_when_stale(db_session, clock):
    station = _enroll(db_session)
    station_service.touch_heartbeat(db_session, station, None, clock=clock)
    clock.advance(31)  # beyond the 30s heartbeat timeout
    result = _heartbeat(db_session, station, clock)
    # touch_heartbeat just ran, so the station is fresh again; verify the
    # stale path directly through compute_status instead.
    station.last_seen_at = clock.now - 31
    assert station_service.compute_status(station, None, clock()).state == "offline"
