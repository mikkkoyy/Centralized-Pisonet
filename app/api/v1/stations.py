"""Station API — registration, heartbeat, command acknowledgement.

Protocol (v1):
- POST /api/v1/stations/register
    Enroll a station with the server enrollment secret. Returns
    a one-time station token.
- POST /api/v1/stations/{code}/heartbeat
    Authenticated poll (bearer token). Returns server-authoritative
    session state, remaining seconds, lock intent, and pending
    commands. Never creates sessions or awards time.
- POST /api/v1/stations/{code}/commands/{id}/ack
    Acknowledge delivery of a pending command.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_api_version, require_station
from app.core.config import get_settings
from app.models.station import Station
from app.schemas.station import (
    CommandAckResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    PendingCommand,
    SessionState,
    StationRegisterRequest,
    StationRegisterResponse,
)
from app.services import session as session_service
from app.services import station as station_service
from app.services.timeutil import utcnow

router = APIRouter(prefix="/api/v1/stations", tags=["stations"])


def _enrollment_secret(request: Request) -> str:
    return request.app.state.enrollment_secret


@router.post("/register", response_model=StationRegisterResponse, status_code=201)
def register_station(
    body: StationRegisterRequest,
    request: Request,
    protocol_version: int = Depends(require_api_version),
    db: Session = Depends(get_db),
) -> StationRegisterResponse:
    """Enroll a station. Requires the server enrollment secret,
    which is issued to the operator out of band."""
    secret = _enrollment_secret(request)
    try:
        result = station_service.enroll_station(
            db,
            station_code=body.station_code,
            enrollment_secret=secret,
            provided_secret=body.enrollment_secret,
            display_name=body.display_name,
            mac_address=body.mac_address,
            ip_address=request.client.host if request.client else None,
        )
    except station_service.EnrollmentError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except station_service.StationError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    station = result.station
    # The plaintext token is returned exactly once, at enrollment.
    return StationRegisterResponse(
        station_id=station.id,
        station_code=station.station_code,
        token=result.token,
        protocol_version=station.protocol_version,
        enrolled_at=station.enrolled_at,
    )


@router.post("/{station_code}/heartbeat", response_model=HeartbeatResponse)
def heartbeat(
    station_code: str,
    body: HeartbeatRequest,
    request: Request,
    protocol_version: int = Depends(require_api_version),
    station: Station = Depends(require_station),
    db: Session = Depends(get_db),
) -> HeartbeatResponse:
    """Authenticated station heartbeat. Server-authoritative state."""
    now = utcnow()
    station_service.touch_heartbeat(
        db, station, request.client.host if request.client else None, clock=lambda: now
    )
    # Expire sessions whose time ran out (idempotent sweep).
    session_service.expire_stale_sessions(db, now=now)

    active = station_service.active_session_for(db, station.id)
    session_state = None
    if active is not None:
        remaining = active.remaining_seconds(now)
        if remaining > 0:
            session_state = SessionState(
                session_id=active.id,
                state="active",
                granted_seconds=active.granted_seconds,
                started_at=active.started_at,
                remaining_seconds=remaining,
            )

    commands = [
        PendingCommand(
            id=cmd.id,
            command_type=cmd.command_type,
            payload=cmd.payload,
            expires_at=cmd.expires_at,
        )
        for cmd in station_service.pending_commands(db, station, clock=lambda: now)
    ]

    status = station_service.compute_status(station, active, now)
    return HeartbeatResponse(
        station_code=station.station_code,
        protocol_version=station.protocol_version,
        server_time=now,
        station_state=status.state,
        lock=status.lock,
        session=session_state,
        commands=commands,
    )


@router.post("/{station_code}/commands/{command_id}/ack", response_model=CommandAckResponse)
def acknowledge_command(
    station_code: str,
    command_id: int,
    request: Request,
    protocol_version: int = Depends(require_api_version),
    station: Station = Depends(require_station),
    db: Session = Depends(get_db),
) -> CommandAckResponse:
    ok = station_service.acknowledge_command(db, station, command_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Command not found or already acknowledged")
    return CommandAckResponse(acknowledged=True, command_id=command_id)
