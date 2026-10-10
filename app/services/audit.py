"""Audit service — append-only security-relevant event records.

Audit events are application records (not rotated operational logs).
They never contain passwords, tokens, or full secrets.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.runtime import AuditEvent
from app.services.timeutil import Clock, utcnow


def record(
    db: Session,
    *,
    actor_type: str,
    event_type: str,
    summary: str,
    actor_id: Optional[int] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    clock: Clock = utcnow,
) -> AuditEvent:
    event = AuditEvent(
        actor_type=actor_type,
        actor_id=actor_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        summary=summary[:2000],
        created_at=clock(),
    )
    db.add(event)
    db.flush()
    return event


def list_events(
    db: Session,
    *,
    offset: int = 0,
    limit: int = 25,
) -> list[AuditEvent]:
    return (
        db.query(AuditEvent)
        .order_by(AuditEvent.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def count_events(db: Session) -> int:
    return db.query(AuditEvent).count()
