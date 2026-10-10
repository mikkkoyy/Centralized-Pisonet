"""Station service tests: enrollment, credentials, status, commands."""

from __future__ import annotations

import pytest

from app.core.security import hash_verifier
from app.services.session import create_session
from app.services import station as station_service


def _enroll(db, code="STATION-01", clock=None):
    return station_service.enroll_station(
        db,
        station_code=code,
        enrollment_secret="enroll-secret",
        provided_secret="enroll-secret",
        display_name="Station 01",
        clock=clock,
    )


def test_enroll_requires_valid_secret(db_session, clock):
    with pytest.raises(station_service.EnrollmentError):
        station_service.enroll_station(
            db_session,
            station_code="STATION-01",
            enrollment_secret="enroll-secret",
            provided_secret="wrong-secret",
            clock=clock,
        )


def test_enroll_returns_token_once_and_stores_only_hash(db_session, clock):
    result = _enroll(db_session, clock=clock)
    assert result.token
    assert result.station.token_hash == hash_verifier(result.token)
    assert result.station.token_prefix == result.token[:8]
    assert result.station.is_active is True


def test_enroll_duplicate_code_rejected(db_session, clock):
    _enroll(db_session, clock=clock)
    with pytest.raises(station_service.StationError):
        _enroll(db_session, clock=clock)


def test_enrollment_rejection_is_audited(db_session, clock):
    with pytest.raises(station_service.EnrollmentError):
        station_service.enroll_station(
            db_session,
            station_code="STATION-01",
            enrollment_secret="enroll-secret",
            provided_secret="wrong",
            clock=clock,
        )
    from app.services.audit import list_events

    events = list_events(db_session)
    assert any(e.event_type == "station.enrollment_rejected" for e in events)


def test_authenticate_accepts_valid_token_only(db_session, clock):
    result = _enroll(db_session, clock=clock)
    station = station_service.authenticate_station(
        db_session, "STATION-01", result.token
    )
    assert station is not None
    assert station.id == result.station.id
    assert station_service.authenticate_station(db_session, "STATION-01", "wrong") is None
    assert station_service.authenticate_station(db_session, "UNKNOWN", result.token) is None


def test_rotation_invalidates_old_token(db_session, clock):
    result = _enroll(db_session, clock=clock)
    new_token = station_service.issue_new_token(
        db_session, result.station, actor_id=1, clock=clock
    )
    assert station_service.authenticate_station(db_session, "STATION-01", result.token) is None
    assert station_service.authenticate_station(db_session, "STATION-01", new_token) is not None


def test_revoked_station_cannot_authenticate(db_session, clock):
    result = _enroll(db_session, clock=clock)
    station_service.set_station_active(db_session, result.station, False, actor_id=1, clock=clock)
    assert station_service.authenticate_station(db_session, "STATION-01", result.token) is None
    station_service.set_station_active(db_session, result.station, True, actor_id=1, clock=clock)
    assert station_service.authenticate_station(db_session, "STATION-01", result.token) is not None


def test_heartbeat_updates_last_seen_and_ip(db_session, clock):
    result = _enroll(db_session, clock=clock)
    assert result.station.last_seen_at is None
    station_service.touch_heartbeat(
        db_session, result.station, "192.168.1.10", clock=clock
    )
    assert result.station.last_seen_at == clock.now
    assert result.station.ip_address == "192.168.1.10"


def test_status_transitions(db_session, clock):
    result = _enroll(db_session, clock=clock)
    station = result.station
    # No heartbeat yet -> offline
    assert station_service.compute_status(station, None, clock()).state == "offline"
    station_service.touch_heartbeat(db_session, station, None, clock=clock)
    status = station_service.compute_status(station, None, clock())
    assert status.state == "available"
    assert status.lock == "locked"
    # Active session -> occupied + unlocked
    session = create_session(db_session, station.id, 3600, clock=clock)
    db_session.commit()
    status = station_service.compute_status(station, session, clock())
    assert status.state == "occupied"
    assert status.lock == "unlocked"
    # Stale heartbeat -> offline even with a live session
    clock.advance(60)
    assert station_service.compute_status(station, session, clock()).state == "offline"
    # Revoked -> revoked/locked regardless of session
    station_service.set_station_active(db_session, station, False, actor_id=1, clock=clock)
    assert station_service.compute_status(station, session, clock()).state == "revoked"


def test_command_queue_delivery_expiry_and_ack(db_session, clock):
    result = _enroll(db_session, clock=clock)
    station = result.station
    cmd = station_service.queue_command(
        db_session, station, "lock", actor_id=1, payload='{"force": true}', clock=clock
    )
    assert cmd.expires_at == clock.now + 300
    pending = station_service.pending_commands(db_session, station, clock=clock)
    assert [c.id for c in pending] == [cmd.id]
    # Owner acknowledgement succeeds exactly once
    assert station_service.acknowledge_command(db_session, station, cmd.id, clock=clock) is True
    assert station_service.acknowledge_command(db_session, station, cmd.id, clock=clock) is False
    assert station_service.pending_commands(db_session, station, clock=clock) == []


def test_expired_commands_are_purged(db_session, clock):
    result = _enroll(db_session, clock=clock)
    station_service.queue_command(db_session, result.station, "lock", actor_id=1, clock=clock)
    clock.advance(301)
    assert station_service.pending_commands(db_session, result.station, clock=clock) == []


def test_queue_replaces_outstanding_command_of_same_type(db_session, clock):
    result = _enroll(db_session, clock=clock)
    station = result.station
    first = station_service.queue_command(db_session, station, "lock", actor_id=1, clock=clock)
    second = station_service.queue_command(db_session, station, "lock", actor_id=1, clock=clock)
    pending = station_service.pending_commands(db_session, station, clock=clock)
    assert [c.id for c in pending] == [second.id]
    assert first.id != second.id
