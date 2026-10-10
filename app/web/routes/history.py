"""Dashboard history pages: sessions, ledger, audit log.

All lists are paginated with bounded page sizes."""

from __future__ import annotations

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services import audit as audit_service
from app.services import ledger as ledger_service
from app.services import session as session_service
from app.services import station as station_service
from app.services.timeutil import utcnow
from app.web.deps import get_csrf_token, get_current_admin, set_csrf_cookie

PAGE_LIMIT = 25


def _templates(request: Request):
    return request.app.state.templates


def _redirect_if_anonymous(request: Request, db: Session):
    admin = get_current_admin(request, db)
    if admin is None:
        return admin, RedirectResponse("/dashboard/login", status_code=302)
    return admin, None


def _page(request: Request) -> int:
    try:
        page = int(request.query_params.get("page", "1"))
    except ValueError:
        return 1
    return max(1, page)


async def sessions_page(
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    admin, redirect = _redirect_if_anonymous(request, db)
    if redirect:
        return redirect

    page = _page(request)
    offset = (page - 1) * PAGE_LIMIT
    sessions = session_service.list_sessions(db, offset=offset, limit=PAGE_LIMIT)
    total = session_service.count_sessions(db)
    now = utcnow()

    station_names = {
        s.id: s.station_code for s in station_service.list_stations(db)
    }
    items = [
        {
            "session": s,
            "station_code": station_names.get(s.station_id, f"#{s.station_id}"),
            "remaining": s.remaining_seconds(now),
        }
        for s in sessions
    ]

    csrf = get_csrf_token(request)
    page_response = _templates(request).TemplateResponse(
        request,
        "sessions.html",
        {
            "admin": admin,
            "csrf_token": csrf,
            "items": items,
            "page": page,
            "limit": PAGE_LIMIT,
            "total": total,
        },
    )
    set_csrf_cookie(request, page_response, csrf)
    return page_response


async def ledger_page(
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    admin, redirect = _redirect_if_anonymous(request, db)
    if redirect:
        return redirect

    page = _page(request)
    offset = (page - 1) * PAGE_LIMIT
    entries = ledger_service.list_entries(db, offset=offset, limit=PAGE_LIMIT)
    total = ledger_service.count_entries(db)

    station_names = {
        s.id: s.station_code for s in station_service.list_stations(db)
    }
    items = [
        {
            "entry": e,
            "station_code": station_names.get(e.station_id, f"#{e.station_id}"),
        }
        for e in entries
    ]

    csrf = get_csrf_token(request)
    page_response = _templates(request).TemplateResponse(
        request,
        "ledger.html",
        {
            "admin": admin,
            "csrf_token": csrf,
            "items": items,
            "page": page,
            "limit": PAGE_LIMIT,
            "total": total,
        },
    )
    set_csrf_cookie(request, page_response, csrf)
    return page_response


async def audit_page(
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    admin, redirect = _redirect_if_anonymous(request, db)
    if redirect:
        return redirect

    page = _page(request)
    offset = (page - 1) * PAGE_LIMIT
    events = audit_service.list_events(db, offset=offset, limit=PAGE_LIMIT)
    total = audit_service.count_events(db)

    csrf = get_csrf_token(request)
    page_response = _templates(request).TemplateResponse(
        request,
        "audit.html",
        {
            "admin": admin,
            "csrf_token": csrf,
            "events": events,
            "page": page,
            "limit": PAGE_LIMIT,
            "total": total,
        },
    )
    set_csrf_cookie(request, page_response, csrf)
    return page_response
