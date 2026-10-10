"""Administrator API — login/logout, station management,
and read-only history endpoints with bounded pagination."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin
from app.core.security import create_admin_token
from app.models.admin import Admin
from app.models.session import END_ADMIN
from app.models.station import Station
from app.schemas.admin import (
    AdminLoginRequest,
    AdminLoginResponse,
    AdminSessionResponse,
    StationManagementResponse,
    StationPreRegisterRequest,
)
from app.schemas.ledger import LedgerEntryResponse
from app.schemas.station import SessionState
from app.services import admin as admin_service
from app.services import ledger as ledger_service
from app.services import session as session_service
from app.services import station as station_service
from app.services.timeutil import utcnow

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _set_admin_cookie(response: Response, settings, username: str) -> None:
    token = create_admin_token(username, settings)
    response.set_cookie(
        key="pisonet_admin",
        value=token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=8 * 3600,
        path="/",
    )


def _clear_admin_cookie(response: Response) -> None:
    response.delete_cookie(key="pisonet_admin", path="/")


@router.post("/login", response_model=AdminLoginResponse)
def admin_login(
    body: AdminLoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        admin = admin_service.login(
            db,
            username=body.username,
            password=body.password,
            ip_address=request.client.host if request.client else None,
        )
    except admin_service.ThrottledError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except admin_service.AdminAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    _set_admin_cookie(response, request.app.state.settings, admin.username)
    return AdminLoginResponse(username=admin.username, role=admin.role)


@router.post("/logout")
def admin_logout(response: Response) -> dict:
    _clear_admin_cookie(response)
    return {"status": "logged_out"}


@router.get("/me", response_model=AdminSessionResponse)
def admin_me(admin: Admin = Depends(require_admin)) -> AdminSessionResponse:
    return AdminSessionResponse(username=admin.username, role=admin.role)


@router.post("/stations", response_model=StationManagementResponse, status_code=201)
def preregister_station(
    body: StationPreRegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_admin),
) -> StationManagementResponse:
    """Administrator-issued enrollment: the server generates the
    station credential without the shared enrollment secret."""
    from app.core.security import generate_token, hash_verifier
    from app.services.timeutil import utcnow as _now

    token = generate_token()
    now = _now()

    station = Station(
        station_code=body.station_code,
        display_name=body.display_name,
        token_hash=hash_verifier(token),
        token_prefix=token[:8],
        enrolled_at=now,
    )
    try:
        db.add(station)
        db.flush()
        station_service.record(
            db,
            actor_type="admin",
            actor_id=admin.id,
            event_type="station.enrolled",
            summary=f"Station {body.station_code} enrolled by administrator",
            entity_type="station",
            entity_id=station.id,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Station code already exists")
    return StationManagementResponse(
        station_id=station.id,
        station_code=station.station_code,
        token=token,
    )


@router.post("/stations/{station_code}/rotate-token", response_model=StationManagementResponse)
def rotate_token(
    station_code: str,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_admin),
) -> StationManagementResponse:
    station = station_service.get_station(db, station_code)
    if station is None:
        raise HTTPException(status_code=404, detail="Station not found")
    token = station_service.issue_new_token(db, station, actor_id=admin.id)
    return StationManagementResponse(
        station_id=station.id,
        station_code=station.station_code,
        token=token,
    )


@router.post("/stations/{station_code}/revoke")
def revoke_station(
    station_code: str,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_admin),
) -> dict:
    station = station_service.get_station(db, station_code)
    if station is None:
        raise HTTPException(status_code=404, detail="Station not found")
    station_service.set_station_active(db, station, False, actor_id=admin.id)
    return {"status": "revoked", "station_code": station_code}


@router.post("/stations/{station_code}/activate")
def activate_station(
    station_code: str,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_admin),
) -> dict:
    station = station_service.get_station(db, station_code)
    if station is None:
        raise HTTPException(status_code=404, detail="Station not found")
    station_service.set_station_active(db, station, True, actor_id=admin.id)
    return {"status": "activated", "station_code": station_code}


@router.post("/stations/{station_code}/lock")
def lock_station(
    station_code: str,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_admin),
) -> dict:
    """Administratively terminate the active session and queue a
    lock command for the station client."""
    station = station_service.get_station(db, station_code)
    if station is None:
        raise HTTPException(status_code=404, detail="Station not found")
    session = session_service.get_active_session(db, station.id)
    if session is not None:
        session_service.end_session(db, session, END_ADMIN)
        db.commit()
        station_service.record(
            db,
            actor_type="admin",
            actor_id=admin.id,
            event_type="session.terminated",
            summary=f"Session {session.id} on station {station_code} terminated by administrator",
            entity_type="session",
            entity_id=session.id,
        )
        db.commit()
    station_service.queue_command(db, station, "lock", actor_id=admin.id)
    return {"status": "locked", "station_code": station_code}


@router.get("/stations")
def list_stations(
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_admin),
) -> list[dict]:
    """All stations with server-computed status."""
    now = utcnow()
    result = []
    for station in station_service.list_stations(db):
        active = station_service.active_session_for(db, station.id)
        status = station_service.compute_status(station, active, now)
        result.append(
            {
                "station_id": station.id,
                "station_code": station.station_code,
                "display_name": station.display_name,
                "state": status.state,
                "lock": status.lock,
                "last_seen_at": station.last_seen_at,
                "ip_address": station.ip_address,
                "is_active": station.is_active,
                "remaining_seconds": (
                    active.remaining_seconds(now) if active else 0
                ),
            }
        )
    return result


@router.get("/sessions")
def list_sessions(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=25, ge=1, le=100),
    station_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_admin),
) -> dict:
    offset = (page - 1) * limit
    sessions = session_service.list_sessions(
        db, offset=offset, limit=limit, station_id=station_id
    )
    now = utcnow()
    items = [
        {
            "id": s.id,
            "station_id": s.station_id,
            "granted_seconds": s.granted_seconds,
            "started_at": s.started_at,
            "ended_at": s.ended_at,
            "end_reason": s.end_reason,
            "is_active": s.ended_at is None,
            "remaining_seconds": s.remaining_seconds(now),
        }
        for s in sessions
    ]
    return {
        "page": page,
        "limit": limit,
        "total": session_service.count_sessions(db, station_id=station_id),
        "items": items,
    }


@router.get("/ledger")
def list_ledger(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=25, ge=1, le=100),
    station_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_admin),
) -> dict:
    offset = (page - 1) * limit
    entries = ledger_service.list_entries(db, offset=offset, limit=limit, station_id=station_id)
    return {
        "page": page,
        "limit": limit,
        "total": ledger_service.count_entries(db, station_id=station_id),
        "items": [LedgerEntryResponse(
            id=e.id,
            idempotency_key=e.idempotency_key,
            station_code=_station_code(db, e.station_id),
            session_id=e.session_id,
            amount_cents=e.amount_cents,
            seconds_credited=e.seconds_credited,
            created_at=e.created_at,
        ).model_dump() for e in entries],
    }


def _station_code(db: Session, station_id: int) -> str:
    station = db.query(Station).get(station_id)
    return station.station_code if station else "?"


@router.get("/audit")
def list_audit(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_admin),
) -> dict:
    from app.services.audit import count_events, list_events

    offset = (page - 1) * limit
    events = list_events(db, offset=offset, limit=limit)
    return {
        "page": page,
        "limit": limit,
        "total": count_events(db),
        "items": [
            {
                "id": e.id,
                "actor_type": e.actor_type,
                "actor_id": e.actor_id,
                "event_type": e.event_type,
                "entity_type": e.entity_type,
                "entity_id": e.entity_id,
                "summary": e.summary,
                "created_at": e.created_at,
            }
            for e in events
        ],
    }
