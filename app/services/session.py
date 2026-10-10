"""Session lifecycle service.

Invariants:
- At most one active session per station (partial unique index
  ``idx_sessions_one_active`` enforces this in the database).
- Remaining time is always computed server-side from persisted
  ``granted_seconds`` and ``started_at``; client countdowns are
  never authoritative.
- Sessions survive server restarts because all state is persisted;
  nothing is held in process memory.
- Time is never silently reset: extension adds to
  ``granted_seconds``; expiry and termination set ``ended_at``
  with an explicit reason exactly once.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.session import END_ADMIN, END_COMPLETED, END_EXPIRED, Session
from app.services.station import active_session_for
from app.services.timeutil import Clock, utcnow


class SessionError(RuntimeError):
    pass


class DuplicateActiveSessionError(SessionError):
    pass


def create_session(
    db: Session,
    station_id: int,
    granted_seconds: int,
    clock: Clock = utcnow,
) -> Session:
    """Create a new active session. Raises
    DuplicateActiveSessionError when one already exists
    (database-enforced)."""
    session = Session(
        station_id=station_id,
        granted_seconds=granted_seconds,
        started_at=clock(),
        created_at=clock(),
    )
    db.add(session)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise DuplicateActiveSessionError(
            f"Station {station_id} already has an active session"
        )
    return session


def extend_session(db: Session, session: Session, seconds: int) -> None:
    """Add seconds to an active session's granted time.
    Caller is responsible for the transaction boundary."""
    if session.ended_at is not None:
        raise SessionError("Cannot extend a completed session")
    session.granted_seconds += seconds


def end_session(
    db: Session,
    session: Session,
    reason: str,
    clock: Clock = utcnow,
) -> None:
    """Terminate a session with an explicit reason.
    Idempotent: ending an already-ended session is a no-op."""
    if session.ended_at is not None:
        return
    if reason not in (END_EXPIRED, END_ADMIN, END_COMPLETED):
        raise SessionError(f"Invalid end reason: {reason!r}")
    session.ended_at = clock()
    session.end_reason = reason


def expire_stale_sessions(db: Session, now: Optional[int] = None) -> list[Session]:
    """End every active session whose time has run out.
    Called from heartbeat and the background sweeper."""
    now = now if now is not None else utcnow()
    expired: list[Session] = []
    active = (
        db.query(Session).filter(Session.ended_at.is_(None)).all()
    )
    for session in active:
        if session.remaining_seconds(now) <= 0:
            end_session(db, session, END_EXPIRED, clock=lambda: now)
            expired.append(session)
    if expired:
        db.commit()
    return expired


def get_active_session(db: Session, station_id: int) -> Optional[Session]:
    return active_session_for(db, station_id)


def get_session_by_id(db: Session, session_id: int) -> Optional[Session]:
    return db.query(Session).filter(Session.id == session_id).first()


def list_sessions(
    db: Session,
    *,
    offset: int = 0,
    limit: int = 25,
    station_id: Optional[int] = None,
) -> list[Session]:
    query = db.query(Session).order_by(Session.id.desc())
    if station_id is not None:
        query = query.filter(Session.station_id == station_id)
    return query.offset(offset).limit(limit).all()


def count_sessions(db: Session, station_id: Optional[int] = None) -> int:
    query = db.query(Session)
    if station_id is not None:
        query = query.filter(Session.station_id == station_id)
    return query.count()
