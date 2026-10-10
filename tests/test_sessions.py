"""Session lifecycle tests: one-active enforcement, server-authoritative
time, expiry, and persistence across connections."""

from __future__ import annotations

import pytest

from app.services.session import (
    DuplicateActiveSessionError,
    SessionError,
    create_session,
    end_session,
    extend_session,
    expire_stale_sessions,
    get_active_session,
)
from app.services.station import enroll_station


def _enrolled_station(db, code="STATION-01"):
    result = enroll_station(
        db,
        station_code=code,
        enrollment_secret="enroll-secret",
        provided_secret="enroll-secret",
    )
    db.commit()
    return result.station


def test_create_session_and_duplicate_prevented(db_session, clock):
    station = _enrolled_station(db_session)
    session = create_session(db_session, station.id, 3600, clock=clock)
    db_session.commit()
    assert get_active_session(db_session, station.id).id == session.id
    # The partial unique index enforces one active session per station.
    with pytest.raises(DuplicateActiveSessionError):
        create_session(db_session, station.id, 60, clock=clock)


def test_remaining_time_is_server_authoritative(db_session, clock):
    station = _enrolled_station(db_session)
    session = create_session(db_session, station.id, 3600, clock=clock)
    assert session.remaining_seconds(clock()) == 3600
    clock.advance(600)
    assert session.remaining_seconds(clock()) == 3000
    clock.advance(3000)
    assert session.remaining_seconds(clock()) == 0


def test_extend_adds_time_to_active_session(db_session, clock):
    station = _enrolled_station(db_session)
    session = create_session(db_session, station.id, 600, clock=clock)
    db_session.commit()
    extend_session(db_session, session, 300)
    db_session.commit()
    assert session.granted_seconds == 900
    assert session.remaining_seconds(clock()) == 900


def test_cannot_extend_completed_session(db_session, clock):
    station = _enrolled_station(db_session)
    session = create_session(db_session, station.id, 600, clock=clock)
    db_session.commit()
    end_session(db_session, session, "completed", clock=clock)
    db_session.commit()
    with pytest.raises(SessionError):
        extend_session(db_session, session, 60)


def test_end_session_requires_valid_reason_and_is_idempotent(db_session, clock):
    station = _enrolled_station(db_session)
    session = create_session(db_session, station.id, 600, clock=clock)
    db_session.commit()
    with pytest.raises(SessionError):
        end_session(db_session, session, "bogus", clock=clock)
    end_session(db_session, session, "admin_terminated", clock=clock)
    db_session.commit()
    assert session.ended_at == clock.now
    assert session.end_reason == "admin_terminated"
    # Ending again is a no-op: reason is never overwritten.
    end_session(db_session, session, "expired", clock=clock)
    db_session.commit()
    assert session.end_reason == "admin_terminated"
    assert get_active_session(db_session, station.id) is None


def test_expire_stale_sessions_ends_only_elapsed_sessions(db_session, clock):
    station = _enrolled_station(db_session)
    other = _enrolled_station(db_session, code="STATION-02")
    short = create_session(db_session, station.id, 60, clock=clock)
    long = create_session(db_session, other.id, 3600, clock=clock)
    db_session.commit()
    clock.advance(61)
    expired = expire_stale_sessions(db_session, now=clock())
    assert [s.id for s in expired] == [short.id]
    assert short.ended_at is not None
    assert short.end_reason == "expired"
    assert long.ended_at is None


def test_session_state_survives_a_new_connection(db_session, clock):
    """Sessions are persisted, never held in process memory."""
    station = _enrolled_station(db_session)
    session = create_session(db_session, station.id, 3600, clock=clock)
    db_session.commit()
    session_id, station_id = session.id, station.id
    db_session.expire_all()
    # A brand-new session over the same engine (as after a restart)
    # must observe the session with its full remaining time.
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=db_session.bind, expire_on_commit=False)
    db2 = factory()
    try:
        active = get_active_session(db2, station_id)
        assert active is not None
        assert active.id == session_id
        assert active.remaining_seconds(clock()) == 3600
    finally:
        db2.close()
