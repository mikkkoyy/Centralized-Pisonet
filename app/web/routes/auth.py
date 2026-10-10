"""Dashboard login and logout handlers."""

from __future__ import annotations

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.security import create_admin_token
from app.services import admin as admin_service
from app.web.deps import (
    ADMIN_COOKIE,
    CSRF_FORM_FIELD,
    get_csrf_token,
    get_current_admin,
    set_csrf_cookie,
    validate_csrf,
)


def _templates(request: Request):
    return request.app.state.templates


async def login_page(
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    admin = get_current_admin(request, db)
    if admin is not None:
        return RedirectResponse("/dashboard/overview", status_code=302)
    csrf = get_csrf_token(request)
    page = _templates(request).TemplateResponse(
        request,
        "login.html",
        {
            "csrf_token": csrf,
            "error": request.query_params.get("error"),
            "has_admin": admin_service.has_any_admin(db),
        },
    )
    set_csrf_cookie(request, page, csrf)
    return page


async def login_post(
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    form = await request.form()
    validate_csrf(request, form_token=str(form.get(CSRF_FORM_FIELD, "")))
    username = str(form.get("username", ""))
    password = str(form.get("password", ""))

    try:
        admin = admin_service.login(
            db,
            username=username,
            password=password,
            ip_address=request.client.host if request.client else None,
        )
    except admin_service.ThrottledError:
        return RedirectResponse(
            "/dashboard/login?error=throttled", status_code=302
        )
    except admin_service.AdminAuthError:
        return RedirectResponse(
            "/dashboard/login?error=invalid", status_code=302
        )

    redirect = RedirectResponse("/dashboard/overview", status_code=302)
    token = create_admin_token(admin.username, request.app.state.settings)
    redirect.set_cookie(
        key=ADMIN_COOKIE,
        value=token,
        httponly=True,
        secure=request.app.state.settings.is_production,
        samesite="lax",
        max_age=8 * 3600,
        path="/",
    )
    return redirect


async def logout(
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    form = await request.form()
    validate_csrf(request, form_token=str(form.get(CSRF_FORM_FIELD, "")))
    redirect = RedirectResponse("/dashboard/login", status_code=302)
    redirect.delete_cookie(key=ADMIN_COOKIE, path="/")
    return redirect
