"""Dashboard overview page."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.ledger import LedgerEntry
from app.models.session import Session
from app.services import audit as audit_service
from app.services import session as session_service
from app.services import station as station_service
from app.services.timeutil import utcnow
from app.web.deps import get_csrf_token, get_current_admin, set_csrf_cookie


def _templates(request: Request):
    return request.app.state.templates


async def overview(
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    admin = get_current_admin(request, db)
    if admin is None:
        return RedirectResponse("/dashboard/login", status_code=302)

    now = utcnow()
    stations = station_service.list_stations(db)
    counts = {"available": 0, "occupied": 0, "offline": 0, "revoked": 0}
    for station in stations:
        active = station_service.active_session_for(db, station.id)
        status = station_service.compute_status(station, active, now)
        counts[status.state] += 1

    active_sessions = (
        db.query(Session).filter(Session.ended_at.is_(None)).count()
    )

    # Revenue today (UTC): sum of credited cents from the ledger.
    today_start = int(
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .timestamp()
    )
    today_cents = (
        db.query(func.coalesce(func.sum(LedgerEntry.amount_cents), 0))
        .filter(LedgerEntry.created_at >= today_start)
        .scalar()
    )

    recent_activity = audit_service.list_events(db, offset=0, limit=8)

    csrf = get_csrf_token(request)
    page = _templates(request).TemplateResponse(
        request,
        "overview.html",
        {
            "admin": admin,
            "csrf_token": csrf,
            "counts": counts,
            "total_stations": len(stations),
            "active_sessions": active_sessions,
            "today_cents": int(today_cents or 0),
            "recent_activity": recent_activity,
            "server_time": now,
        },
    )
    set_csrf_cookie(request, page, csrf)
    return page
