"""Ledger service — idempotent, atomic credit operations.

Invariants:
- Every credit-producing operation requires a caller-supplied
  idempotency key. Uniqueness is enforced by a database UNIQUE
  constraint, not by in-memory state, so credits survive
  process restarts and concurrent duplicates.
- The ledger row and the session time adjustment are written in
  ONE database transaction: a failure anywhere leaves neither
  behind (no partial credit, no double charge).
- Repeating a request with the same key AND the same payload
  returns the original record without crediting again.
- Repeating a key with a DIFFERENT payload is rejected with a
  conflict and audited; no credit is applied.
- Failed operations never leave a partially updated session.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.ledger import LedgerEntry
from app.models.session import Session
from app.models.station import Station
from app.services.audit import record
from app.services.session import (
    DuplicateActiveSessionError,
    extend_session,
    create_session,
)
from app.services.station import get_station
from app.services.timeutil import Clock, utcnow


class LedgerError(RuntimeError):
    pass


class UnknownStationError(LedgerError):
    pass


class IdempotencyConflictError(LedgerError):
    """Same idempotency key presented with a different payload."""


@dataclass
class LedgerCreditResult:
    entry: LedgerEntry
    session: Optional[Session]
    idempotent: bool

    @property
    def session_state(self) -> str:
        if self.session is None or self.session.ended_at is not None:
            return "none"
        return "active"


def _payload_hash(
    station_code: str,
    amount_cents: int,
    seconds: int,
    reference: Optional[str],
) -> str:
    """Stable hash of the credit payload used to distinguish
    idempotent replays from conflicting retries."""
    canonical = json.dumps(
        {
            "station_code": station_code,
            "amount_cents": amount_cents,
            "seconds": seconds,
            "reference": reference,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _apply_credit(
    db: Session,
    station: Station,
    seconds: int,
    entry: LedgerEntry,
    clock: Clock,
) -> Session:
    """Create or extend the station's active session.

    Called inside the same transaction as the ledger insert so
    the credit and the time adjustment commit atomically.
    Separated for testability (failure injection point).
    """
    session = (
        db.query(Session)
        .filter(Session.station_id == station.id, Session.ended_at.is_(None))
        .first()
    )
    if session is None:
        session = create_session(db, station.id, seconds, clock=clock)
        entry.session_id = session.id
    else:
        extend_session(db, session, seconds)
        entry.session_id = session.id
    return session


def credit(
    db: Session,
    *,
    station_code: str,
    amount_cents: int,
    seconds: int,
    idempotency_key: str,
    reference: Optional[str] = None,
    actor_id: Optional[int] = None,
    clock: Clock = utcnow,
) -> LedgerCreditResult:
    """Credit a station with ``seconds`` of session time for
    ``amount_cents``. Safe to retry: duplicates with the same
    payload return the original record; conflicting payloads
    under the same key are rejected."""
    station = get_station(db, station_code)
    if station is None:
        raise UnknownStationError(f"Unknown station {station_code!r}")

    payload = _payload_hash(station_code, amount_cents, seconds, reference)
    entry = LedgerEntry(
        idempotency_key=idempotency_key,
        station_id=station.id,
        session_id=None,
        amount_cents=amount_cents,
        seconds_credited=seconds,
        payload_hash=payload,
        created_at=clock(),
    )
    db.add(entry)
    try:
        db.flush()  # INSERT — raises IntegrityError on duplicate key
        session = _apply_credit(db, station, seconds, entry, clock=clock)
        record(
            db,
            actor_type="admin" if actor_id is not None else "system",
            actor_id=actor_id,
            event_type="ledger.credited",
            summary=(
                f"Credit {amount_cents}c/{seconds}s to station "
                f"{station_code} via key {idempotency_key!r}"
            ),
            entity_type="ledger",
            entity_id=entry.id,
            clock=clock,
        )
        db.commit()
        return LedgerCreditResult(entry=entry, session=session, idempotent=False)
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(LedgerEntry)
            .filter(LedgerEntry.idempotency_key == idempotency_key)
            .first()
        )
        if existing is None:
            # A different constraint failed; surface it clearly.
            raise LedgerError("Ledger insert failed (constraint violation)")
        if existing.payload_hash != payload:
            record(
                db,
                actor_type="admin" if actor_id is not None else "system",
                actor_id=actor_id,
                event_type="ledger.idempotency_conflict",
                summary=(
                    f"Conflicting retry rejected for key {idempotency_key!r} "
                    f"on station {station_code}"
                ),
                entity_type="ledger",
                entity_id=existing.id,
                clock=clock,
            )
            db.commit()
            raise IdempotencyConflictError(
                "Idempotency key already used with a different payload"
            )
        # Idempotent replay: return the original record. The session
        # state reflects the current (post-original-credit) state.
        session = (
            db.query(Session)
            .filter(Session.station_id == station.id, Session.ended_at.is_(None))
            .first()
        )
        return LedgerCreditResult(entry=existing, session=session, idempotent=True)


def list_entries(
    db: Session,
    *,
    offset: int = 0,
    limit: int = 25,
    station_id: Optional[int] = None,
) -> list[LedgerEntry]:
    query = db.query(LedgerEntry).order_by(LedgerEntry.id.desc())
    if station_id is not None:
        query = query.filter(LedgerEntry.station_id == station_id)
    return query.offset(offset).limit(limit).all()


def count_entries(db: Session, station_id: Optional[int] = None) -> int:
    query = db.query(LedgerEntry)
    if station_id is not None:
        query = query.filter(LedgerEntry.station_id == station_id)
    return query.count()
