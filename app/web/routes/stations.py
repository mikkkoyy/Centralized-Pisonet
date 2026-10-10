"""Dashboard station list, station detail, and
station management actions."""

from __future__ import annotations

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.session import END_ADMIN
from app.services import ledger as ledger_service
from app.services import session as session_service
from app.services import station as station_service
from app.services.timeutil import utcnow
from app.web.deps import (
    CSRF_FORM_FIELD,
    get_csrf_token,
    get_current_admin,
    set_csrf_cookie,
    validate_csrf,
)


def _templates(request: Request):
    return request.app.state.templates


def _redirect_if_anonymous(request: Request, db: Session):
    admin = get_current_admin(request, db)
    if admin is None:
        return admin, RedirectResponse("/dashboard/login", status_code=302)
    return admin, None


async def station_list(
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    admin, redirect = _redirect_if_anonymous(request, db)
    if redirect:
        return redirect

    now = utcnow()
    rows = []
    for station in station_service.list_stations(db):
        active = station_service.active_session_for(db, station.id)
        status = station_service.compute_status(station, active, now)
        rows.append(
            {
                "station": station,
                "state": status.state,
                "lock": status.lock,
                "remaining": active.remaining_seconds(now) if active else 0,
            }
        )

    csrf = get_csrf_token(request)
    page = _templates(request).TemplateResponse(
        request,
        "stations.html",
        {"admin": admin, "csrf_token": csrf, "rows": rows},
    )
    set_csrf_cookie(request, page, csrf)
    return page


async def station_detail_fragment(
    request: Request,
    station_code: str,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """HTMX fragment: current session card for a station.
    Refreshed periodically by the station detail page."""
    admin, redirect = _redirect_if_anonymous(request, db)
    if redirect:
        return redirect

    station = station_service.get_station(db, station_code)
    if station is None:
        return HTMLResponse("<p>Station not found.</p>", status_code=404)

    now = utcnow()
    active = station_service.active_session_for(db, station.id)
    status = station_service.compute_status(station, active, now)
    csrf = get_csrf_token(request)
    page = _templates(request).TemplateResponse(
        request,
        "partials/station_session.html",
        {
            "admin": admin,
            "csrf_token": csrf,
            "station": station,
            "state": status.state,
            "lock": status.lock,
            "session": active,
            "remaining": active.remaining_seconds(now) if active else 0,
            "server_time": now,
        },
    )
    set_csrf_cookie(request, page, csrf)
    return page


async def station_detail(
    request: Request,
    station_code: str,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    admin, redirect = _redirect_if_anonymous(request, db)
    if redirect:
        return redirect

    station = station_service.get_station(db, station_code)
    if station is None:
        csrf = get_csrf_token(request)
        page = _templates(request).TemplateResponse(
            request,
            "station_detail.html",
            {"admin": admin, "csrf_token": csrf, "station": None},
            status_code=404,
        )
        set_csrf_cookie(request, page, csrf)
        return page

    now = utcnow()
    active = station_service.active_session_for(db, station.id)
    status = station_service.compute_status(station, active, now)
    recent_ledger = ledger_service.list_entries(
        db, offset=0, limit=10, station_id=station.id
    )
    commands = station_service.pending_commands(db, station, clock=lambda: now)

    csrf = get_csrf_token(request)
    page = _templates(request).TemplateResponse(
        request,
        "station_detail.html",
        {
            "admin": admin,
            "csrf_token": csrf,
            "station": station,
            "state": status.state,
            "lock": status.lock,
            "session": active,
            "remaining": active.remaining_seconds(now) if active else 0,
            "recent_ledger": recent_ledger,
            "commands": commands,
            "server_time": now,
            "flash": request.query_params.get("flash"),
        },
    )
    set_csrf_cookie(request, page, csrf)
    return page


async def lock_station(
    request: Request,
    station_code: str,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    admin, redirect = _redirect_if_anonymous(request, db)
    if redirect:
        return redirect
    form = await request.form()
    validate_csrf(request, form_token=str(form.get(CSRF_FORM_FIELD, "")))

    station = station_service.get_station(db, station_code)
    if station is None:
        return RedirectResponse(
            f"/dashboard/stations/{station_code}", status_code=302
        )
    session = session_service.get_active_session(db, station.id)
    if session is not None:
        session_service.end_session(db, session, END_ADMIN)
        db.commit()
    station_service.queue_command(db, station, "lock", actor_id=admin.id)
    return RedirectResponse(
        f"/dashboard/stations/{station_code}?flash=locked", status_code=302
    )


async def rotate_token(
    request: Request,
    station_code: str,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    admin, redirect = _redirect_if_anonymous(request, db)
    if redirect:
        return redirect
    form = await request.form()
    validate_csrf(request, form_token=str(form.get(CSRF_FORM_FIELD, "")))

    station = station_service.get_station(db, station_code)
    if station is None:
        return RedirectResponse(
            f"/dashboard/stations/{station_code}", status_code=302
        )
    token = station_service.issue_new_token(db, station, actor_id=admin.id)
    csrf = get_csrf_token(request)
    page = _templates(request).TemplateResponse(
        request,
        "station_detail.html",
        {
            "admin": admin,
            "csrf_token": csrf,
            "station": station,
            "new_token": token,  # shown exactly once
            "state": station_service.compute_status(
                station,
                station_service.active_session_for(db, station.id),
                utcnow(),
            ).state,
            "lock": "locked",
            "session": None,
            "remaining": 0,
            "recent_ledger": [],
            "commands": [],
            "server_time": utcnow(),
        },
    )
    set_csrf_cookie(request, page, csrf)
    return page


async def revoke_station(
    request: Request,
    station_code: str,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    admin, redirect = _redirect_if_anonymous(request, db)
    if redirect:
        return redirect
    form = await request.form()
    validate_csrf(request, form_token=str(form.get(CSRF_FORM_FIELD, "")))

    station = station_service.get_station(db, station_code)
    if station is not None:
        station_service.set_station_active(db, station, False, actor_id=admin.id)
    return RedirectResponse(
        f"/dashboard/stations/{station_code}?flash=revoked", status_code=302
    )


async def activate_station(
    request: Request,
    station_code: str,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    admin, redirect = _redirect_if_anonymous(request, db)
    if redirect:
        return redirect
    form = await request.form()
    validate_csrf(request, form_token=str(form.get(CSRF_FORM_FIELD, "")))

    station = station_service.get_station(db, station_code)
    if station is not None:
        station_service.set_station_active(db, station, True, actor_id=admin.id)
    return RedirectResponse(
        f"/dashboard/stations/{station_code}?flash=activated", status_code=302
    )
