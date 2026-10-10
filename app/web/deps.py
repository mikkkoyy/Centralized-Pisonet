"""Dashboard authentication and CSRF protection.

- Administrator sessions use an HttpOnly JWT cookie
  (separate from station bearer tokens).
- State-changing dashboard actions use double-submit
  CSRF: a random token in a readable cookie must match
  the form field or X-CSRF-Token header.

Cookie note: FastAPI does NOT merge cookies set on the injected
``Response`` parameter when the endpoint returns a Response object
directly (TemplateResponse/RedirectResponse). Every route therefore
sets cookies on the response object it returns.
"""

from __future__ import annotations

import secrets
from typing import Optional

from fastapi import HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.core.security import decode_admin_token
from app.models.admin import Admin

ADMIN_COOKIE = "pisonet_admin"
CSRF_COOKIE = "pisonet_csrf"
CSRF_FORM_FIELD = "_csrf"


def get_current_admin(
    request: Request,
    db: Session,
) -> Optional[Admin]:
    """Return the authenticated administrator or None."""
    token = request.cookies.get(ADMIN_COOKIE)
    if not token:
        return None
    settings = request.app.state.settings
    username = decode_admin_token(token, settings)
    if username is None:
        return None
    admin = db.query(Admin).filter(Admin.username == username).first()
    if admin is None or not admin.is_active:
        return None
    return admin


def require_admin(request: Request, db: Session) -> Admin:
    """Dashboard dependency: redirect target is handled by
    the route; raises 401 for HTMX requests."""
    admin = get_current_admin(request, db)
    if admin is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return admin


def get_csrf_token(request: Request) -> str:
    """Return the current CSRF token, generating a new one when
    the cookie is absent (the caller must set it via
    ``set_csrf_cookie`` on the returned response)."""
    token = request.cookies.get(CSRF_COOKIE)
    if not token:
        token = secrets.token_urlsafe(32)
    return token


def set_csrf_cookie(request: Request, response: Response, token: str) -> None:
    """Set the double-submit CSRF cookie on ``response`` when absent.
    The cookie is readable by JS (no HttpOnly) so forms can echo it."""
    if request.cookies.get(CSRF_COOKIE):
        return
    response.set_cookie(
        key=CSRF_COOKIE,
        value=token,
        httponly=False,  # double-submit: the form must read it
        secure=request.app.state.settings.is_production,
        samesite="strict",
        max_age=8 * 3600,
        path="/",
    )


def ensure_csrf_token(request: Request, response: Response) -> str:
    """Return the CSRF token, setting the cookie on ``response``
    when absent. ``response`` MUST be the response object the route
    returns."""
    token = get_csrf_token(request)
    set_csrf_cookie(request, response, token)
    return token


def validate_csrf(request: Request, form_token: str | None = None) -> None:
    """Validate a double-submit CSRF token on a state-changing
    request. The token may arrive as a form field (``_csrf``)
    or as the ``X-CSRF-Token`` header (HTMX). Raises 403 on
    missing or mismatched tokens."""
    cookie_token = request.cookies.get(CSRF_COOKIE)
    provided = form_token if form_token else request.headers.get("X-CSRF-Token")
    if not cookie_token or not provided:
        raise HTTPException(status_code=403, detail="CSRF token missing")
    if not secrets.compare_digest(cookie_token, provided):
        raise HTTPException(status_code=403, detail="CSRF token mismatch")
