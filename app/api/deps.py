"""FastAPI dependencies: DB sessions, protocol versioning,
station authentication, and administrator authentication."""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.protocol import SUPPORTED_PROTOCOL_VERSIONS
from app.core.security import decode_admin_token
from app.db.database import get_session_factory
from app.models.station import Station
from app.services import station as station_service
from app.services.admin import AdminAuthError

# Engine/session factory are created during application startup and
# stored on app.state (see app.main).


def get_db(request: Request) -> Session:
    """Yield a database session scoped to the request."""
    factory = request.app.state.session_factory
    db = factory()
    try:
        yield db
    finally:
        db.close()


def require_api_version(
    x_api_version: Optional[str] = Header(default=None, alias="X-Api-Version"),
) -> int:
    """Every station API request must declare its protocol version."""
    if x_api_version is None:
        raise HTTPException(
            status_code=400,
            detail="Missing required header X-Api-Version",
        )
    try:
        version = int(x_api_version)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid X-Api-Version")
    if version not in SUPPORTED_PROTOCOL_VERSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported protocol version {version}; "
            f"supported: {sorted(SUPPORTED_PROTOCOL_VERSIONS)}",
        )
    return version


def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization[len("Bearer "):].strip()


def require_station(
    request: Request,
    station_code: str,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> Station:
    """Authenticate a station request with its bearer token."""
    token = _extract_bearer(authorization)
    station = None
    if token is not None:
        station = station_service.authenticate_station(db, station_code, token)
    if station is None:
        station_service.record_auth_failure(
            db, station_code, request.client.host if request.client else None
        )
        raise HTTPException(status_code=401, detail="Invalid or revoked station credentials")
    return station


def require_admin(
    request: Request,
    db: Session = Depends(get_db),
) -> object:
    """Authenticate an administrator via Bearer JWT or the
    dashboard session cookie. Returns the Admin row."""
    from app.models.admin import Admin

    settings = request.app.state.settings
    token = _extract_bearer(
        request.headers.get("authorization")
    )
    username: Optional[str] = None
    if token is not None:
        username = decode_admin_token(token, settings)
    if username is None:
        cookie_token = request.cookies.get("pisonet_admin")
        if cookie_token:
            username = decode_admin_token(cookie_token, settings)
    if username is None:
        raise HTTPException(status_code=401, detail="Administrator authentication required")
    admin = (
        db.query(Admin).filter(Admin.username == username).first()
    )
    if admin is None or not admin.is_active:
        raise HTTPException(status_code=401, detail="Administrator authentication required")
    return admin
