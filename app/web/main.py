"""Dashboard web routes — Jinja2 + HTMX, modern dark UI.

All dashboard routes require administrator authentication
(HttpOnly session cookie). State-changing forms require a
matching double-submit CSRF token.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.web.deps import (
    CSRF_FORM_FIELD,
    ensure_csrf_token,
    get_current_admin,
    require_admin,
    validate_csrf,
)
from app.web.routes import auth as auth_routes
from app.web.routes import history as history_routes
from app.web.routes import overview as overview_routes
from app.web.routes import stations as stations_routes

web_router = APIRouter()


def _templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


# Login / logout (unauthenticated routes)
web_router.add_api_route(
    "/dashboard/login",
    auth_routes.login_page,
    methods=["GET"],
    response_class=HTMLResponse,
)
web_router.add_api_route(
    "/dashboard/login",
    auth_routes.login_post,
    methods=["POST"],
    response_class=HTMLResponse,
)
web_router.add_api_route(
    "/dashboard/logout",
    auth_routes.logout,
    methods=["POST"],
)

# Protected dashboard pages
web_router.add_api_route(
    "/dashboard/overview",
    overview_routes.overview,
    methods=["GET"],
    response_class=HTMLResponse,
)
web_router.add_api_route(
    "/dashboard/stations",
    stations_routes.station_list,
    methods=["GET"],
    response_class=HTMLResponse,
)
web_router.add_api_route(
    "/dashboard/stations/{station_code}",
    stations_routes.station_detail,
    methods=["GET"],
    response_class=HTMLResponse,
)
web_router.add_api_route(
    "/dashboard/stations/{station_code}/fragment",
    stations_routes.station_detail_fragment,
    methods=["GET"],
    response_class=HTMLResponse,
)
web_router.add_api_route(
    "/dashboard/stations/{station_code}/lock",
    stations_routes.lock_station,
    methods=["POST"],
)
web_router.add_api_route(
    "/dashboard/stations/{station_code}/rotate-token",
    stations_routes.rotate_token,
    methods=["POST"],
)
web_router.add_api_route(
    "/dashboard/stations/{station_code}/revoke",
    stations_routes.revoke_station,
    methods=["POST"],
)
web_router.add_api_route(
    "/dashboard/stations/{station_code}/activate",
    stations_routes.activate_station,
    methods=["POST"],
)
web_router.add_api_route(
    "/dashboard/sessions",
    history_routes.sessions_page,
    methods=["GET"],
    response_class=HTMLResponse,
)
web_router.add_api_route(
    "/dashboard/ledger",
    history_routes.ledger_page,
    methods=["GET"],
    response_class=HTMLResponse,
)
web_router.add_api_route(
    "/dashboard/audit",
    history_routes.audit_page,
    methods=["GET"],
    response_class=HTMLResponse,
)

# Root redirects to the dashboard
@web_router.get("/", include_in_schema=False)
def root(request: Request):
    return RedirectResponse("/dashboard/overview", status_code=302)
