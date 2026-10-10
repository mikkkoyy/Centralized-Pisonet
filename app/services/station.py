"""Station service — enrollment, credentials, heartbeat state.

Security properties:
- Enrollment requires the server's enrollment secret (issued out of
  band to the operator); a bare registration request cannot claim an
  arbitrary station number.
- Each station receives a unique random token; only its SHA-256
  verifier is stored.
- MAC addresses are recorded as informational metadata and are NEVER
  accepted as proof of identity.
- Tokens can be rotated (old token immediately invalid) and stations
  can be revoked (all authentication rejected while revoked).
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.protocol import COMMAND_TTL_SECONDS
from app.core.security import generate_token, hash_verifier, secrets_equal
from app.models.runtime import StationCommand
from app.models.session import Session
from app.models.station import Station
from app.services.audit import record
from app.services.timeutil import Clock, utcnow


class StationError(RuntimeError):
    pass


class EnrollmentError(StationError):
    pass


@dataclass
class StationStatus:
    state: str  # available | occupied | offline | revoked
    lock: str  # locked | unlocked


@dataclass
class EnrollmentResult:
    station: Station
    token: str  # plaintext token — returned exactly once at enrollment


def _heartbeat_timeout_seconds() -> int:
    from app.core.config import get_settings

    return get_settings().station_heartbeat_timeout


def enroll_station(
    db: Session,
    *,
    station_code: str,
    enrollment_secret: str,
    provided_secret: str,
    display_name: Optional[str] = None,
    mac_address: Optional[str] = None,
    ip_address: Optional[str] = None,
    clock: Clock = utcnow,
) -> EnrollmentResult:
    """Enroll a new station. Fails if the enrollment secret does
    not match or the station code is already taken. Returns the
    station row and the plaintext token (shown once)."""
    if not secrets_equal(provided_secret, hash_verifier(enrollment_secret)):
        record(
            db,
            actor_type="system",
            event_type="station.enrollment_rejected",
            summary=f"Enrollment rejected for station_code={station_code!r}: invalid enrollment secret",
        )
        db.commit()
        raise EnrollmentError("Invalid enrollment secret")

    token = generate_token()
    station = Station(
        station_code=station_code,
        display_name=display_name,
        token_hash=hash_verifier(token),
        token_prefix=token[:8],
        enrolled_at=clock(),
        mac_address=mac_address,
        ip_address=ip_address,
    )
    try:
        db.add(station)
        db.flush()
        record(
            db,
            actor_type="system",
            event_type="station.enrolled",
            summary=f"Station {station_code} enrolled (id={station.id})",
            entity_type="station",
            entity_id=station.id,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise StationError(f"Station code {station_code!r} already exists")
    return EnrollmentResult(station=station, token=token)


def issue_new_token(db: Session, station: Station, actor_id: int, clock: Clock = utcnow) -> str:
    """Rotate a station's credential. The previous token is
    invalidated immediately."""
    token = generate_token()
    station.token_hash = hash_verifier(token)
    station.token_prefix = token[:8]
    record(
        db,
        actor_type="admin",
        actor_id=actor_id,
        event_type="station.token_rotated",
        summary=f"Credential rotated for station {station.station_code}",
        entity_type="station",
        entity_id=station.id,
        clock=clock,
    )
    db.commit()
    return token


def set_station_active(db: Session, station: Station, active: bool, actor_id: int, clock: Clock = utcnow) -> None:
    """Revoke or re-activate a station's credentials."""
    station.is_active = active
    record(
        db,
        actor_type="admin",
        actor_id=actor_id,
        event_type="station.revoked" if not active else "station.activated",
        summary=f"Station {station.station_code} {'revoked' if not active else 're-activated'}",
        entity_type="station",
        entity_id=station.id,
        clock=clock,
    )
    db.commit()


def authenticate_station(db: Session, station_code: str, token: str) -> Optional[Station]:
    """Authenticate a station request. Returns the station when the
    verifier matches and the station is not revoked."""
    station = (
        db.query(Station).filter(Station.station_code == station_code).first()
    )
    if station is None or not station.is_active:
        return None
    if not secrets_equal(token, station.token_hash):
        return None
    return station


def get_station(db: Session, station_code: str) -> Optional[Station]:
    return db.query(Station).filter(Station.station_code == station_code).first()


def station_is_stale(station: Station, now: int) -> bool:
    if station.last_seen_at is None:
        return True
    return (now - station.last_seen_at) > _heartbeat_timeout_seconds()


def compute_status(station: Station, active_session: Optional[Session], now: int) -> StationStatus:
    """Derive the station state shown to operators."""
    if not station.is_active:
        return StationStatus(state="revoked", lock="locked")
    if station_is_stale(station, now):
        return StationStatus(state="offline", lock="locked")
    if active_session is not None and active_session.remaining_seconds(now) > 0:
        return StationStatus(state="occupied", lock="unlocked")
    return StationStatus(state="available", lock="locked")


def touch_heartbeat(db: Session, station: Station, ip_address: Optional[str], clock: Clock = utcnow) -> None:
    """Record a heartbeat. Never creates sessions or awards time."""
    station.last_seen_at = clock()
    if ip_address:
        station.ip_address = ip_address
    db.commit()


def record_auth_failure(db: Session, station_code: str, ip_address: Optional[str], clock: Clock = utcnow) -> None:
    record(
        db,
        actor_type="station",
        event_type="station.auth_failure",
        summary=f"Station authentication failed for station_code={station_code!r} from {ip_address or 'unknown'}",
        clock=clock,
    )
    db.commit()


def list_stations(db: Session) -> list[Station]:
    return db.query(Station).order_by(Station.station_code).all()


def active_session_for(db: Session, station_id: int) -> Optional[Session]:
    return (
        db.query(Session)
        .filter(Session.station_id == station_id, Session.ended_at.is_(None))
        .first()
    )


# --- Pending command delivery (persistence, ownership, expiry, ack) ---


def queue_command(
    db: Session,
    station: Station,
    command_type: str,
    actor_id: int,
    payload: Optional[str] = None,
    clock: Clock = utcnow,
) -> StationCommand:
    """Queue a command for a station. Replaces any outstanding
    unacknowledged command of the same type (single pending slot
    per type keeps delivery deterministic)."""
    outstanding = (
        db.query(StationCommand)
        .filter(
            StationCommand.station_id == station.id,
            StationCommand.command_type == command_type,
            StationCommand.acknowledged_at.is_(None),
        )
        .all()
    )
    for cmd in outstanding:
        db.delete(cmd)
    now = clock()
    command = StationCommand(
        station_id=station.id,
        command_type=command_type,
        payload=payload,
        created_at=now,
        expires_at=now + COMMAND_TTL_SECONDS,
    )
    db.add(command)
    record(
        db,
        actor_type="admin",
        actor_id=actor_id,
        event_type="command.queued",
        summary=f"Command {command_type!r} queued for station {station.station_code}",
        entity_type="station",
        entity_id=station.id,
        clock=clock,
    )
    db.commit()
    return command


def pending_commands(db: Session, station: Station, clock: Clock = utcnow) -> list[StationCommand]:
    """Return unacknowledged, unexpired commands for the station.
    Expired commands are purged (delivery deadline passed)."""
    now = clock()
    expired = (
        db.query(StationCommand)
        .filter(
            StationCommand.station_id == station.id,
            StationCommand.acknowledged_at.is_(None),
            StationCommand.expires_at <= now,
        )
        .all()
    )
    for cmd in expired:
        db.delete(cmd)
    if expired:
        db.commit()
    return (
        db.query(StationCommand)
        .filter(
            StationCommand.station_id == station.id,
            StationCommand.acknowledged_at.is_(None),
            StationCommand.expires_at > now,
        )
        .order_by(StationCommand.created_at)
        .all()
    )


def acknowledge_command(db: Session, station: Station, command_id: int, clock: Clock = utcnow) -> bool:
    """Acknowledge delivery of a command. Only the owning station
    may acknowledge."""
    command = (
        db.query(StationCommand)
        .filter(StationCommand.id == command_id, StationCommand.station_id == station.id)
        .first()
    )
    if command is None or command.acknowledged_at is not None:
        return False
    command.acknowledged_at = clock()
    db.commit()
    return True
