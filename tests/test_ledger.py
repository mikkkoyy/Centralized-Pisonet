"""Ledger tests: idempotent credits, conflict rejection, atomicity."""

from __future__ import annotations

import pytest

from app.services.audit import list_events
from app.services.ledger import (
    IdempotencyConflictError,
    UnknownStationError,
    credit,
    list_entries,
)
from app.services.session import end_session, get_active_session
from app.services.station import enroll_station


def _enrolled(db, code="STATION-01"):
    result = enroll_station(
        db,
        station_code=code,
        enrollment_secret="enroll-secret",
        provided_secret="enroll-secret",
    )
    db.commit()
    return result.station


def _credit(db, station_code, key, cents=5000, seconds=1800, clock=None):
    return credit(
        db,
        station_code=station_code,
        amount_cents=cents,
        seconds=seconds,
        idempotency_key=key,
        clock=clock,
    )


def test_credit_creates_ledger_entry_and_session_together(db_session, clock):
    station = _enrolled(db_session)
    result = _credit(db_session, station.station_code, "key-1", clock=clock)
    assert result.idempotent is False
    assert result.entry.amount_cents == 5000
    assert result.entry.seconds_credited == 1800
    assert result.session is not None
    assert result.session.granted_seconds == 1800
    assert result.session_state == "active"
    assert result.entry.session_id == result.session.id


def test_replay_same_key_and_payload_is_idempotent(db_session, clock):
    station = _enrolled(db_session)
    first = _credit(db_session, station.station_code, "key-1", clock=clock)
    second = _credit(db_session, station.station_code, "key-1", clock=clock)
    assert second.idempotent is True
    assert second.entry.id == first.entry.id
    # Exactly one ledger row and no double credit.
    assert len(list_entries(db_session)) == 1
    assert second.session.granted_seconds == 1800


def test_replay_with_different_payload_is_rejected_and_audited(db_session, clock):
    station = _enrolled(db_session)
    _credit(db_session, station.station_code, "key-1", clock=clock)
    with pytest.raises(IdempotencyConflictError):
        _credit(
            db_session,
            station.station_code,
            "key-1",
            cents=9000,
            seconds=3600,
            clock=clock,
        )
    # Original credit is untouched; the conflict is audited.
    assert len(list_entries(db_session)) == 1
    assert any(e.event_type == "ledger.idempotency_conflict" for e in list_events(db_session))


def test_unknown_station_rejected(db_session, clock):
    with pytest.raises(UnknownStationError):
        _credit(db_session, "NOPE", "key-1", clock=clock)


def test_second_credit_extends_the_same_session(db_session, clock):
    station = _enrolled(db_session)
    first = _credit(db_session, station.station_code, "key-1", clock=clock)
    second = _credit(
        db_session, station.station_code, "key-2", cents=200, seconds=300, clock=clock
    )
    assert second.session.id == first.session.id
    assert second.session.granted_seconds == 2100
    assert len(list_entries(db_session)) == 2


def test_failed_credit_leaves_no_partial_state(db_session, clock, monkeypatch):
    """Ledger row and session adjustment commit atomically: a failure
    in the session step must leave neither behind."""
    import app.services.ledger as ledger_module

    station = _enrolled(db_session)

    def boom(*args, **kwargs):
        raise RuntimeError("injected failure")

    monkeypatch.setattr(ledger_module, "_apply_credit", boom)
    with pytest.raises(RuntimeError, match="injected failure"):
        _credit(db_session, station.station_code, "key-1", clock=clock)
    db_session.rollback()
    assert list_entries(db_session) == []
    assert get_active_session(db_session, station.id) is None


def test_replay_after_session_ended_reports_no_active_session(db_session, clock):
    station = _enrolled(db_session)
    _credit(db_session, station.station_code, "key-1", clock=clock)
    session = get_active_session(db_session, station.id)
    end_session(db_session, session, "completed", clock=clock)
    db_session.commit()
    result = _credit(db_session, station.station_code, "key-1", clock=clock)
    assert result.idempotent is True
    assert result.session_state == "none"


def test_ledger_entries_are_immutable_history(db_session, clock):
    station = _enrolled(db_session)
    _credit(db_session, station.station_code, "key-1", clock=clock)
    entries = list_entries(db_session)
    assert len(entries) == 1
    assert entries[0].amount_cents == 5000
    assert entries[0].payload_hash
    assert entries[0].created_at == clock.now
