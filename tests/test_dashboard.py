"""Dashboard tests: cookie auth, CSRF protection, templates,
static assets."""

from __future__ import annotations

import pytest

from app.services.admin import provision_admin
from app.services.station import enroll_station


def _provision_admin(test_app):
    with test_app.db() as db:
        provision_admin(db, username="root", password="sup3rsecret!")


def _enroll_station(test_app, code="ST01"):
    with test_app.db() as db:
        enroll_station(
            db,
            station_code=code,
            enrollment_secret="enroll-secret",
            provided_secret="enroll-secret",
        )


def _login(test_app):
    """Perform the dashboard login flow; returns the CSRF token."""
    test_app.client.get("/dashboard/login")
    csrf = test_app.client.cookies.get("pisonet_csrf")
    response = test_app.client.post(
        "/dashboard/login",
        data={"username": "root", "password": "sup3rsecret!", "_csrf": csrf},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "pisonet_admin" in test_app.client.cookies
    return csrf


def test_login_page_renders_with_csrf(test_app):
    response = test_app.client.get("/dashboard/login")
    assert response.status_code == 200
    assert "pisonet_csrf" in test_app.client.cookies
    assert "_csrf" in response.text


def test_protected_pages_redirect_anonymous_users(test_app):
    for path in (
        "/dashboard/overview",
        "/dashboard/stations",
        "/dashboard/stations/ST01",
        "/dashboard/sessions",
        "/dashboard/ledger",
        "/dashboard/audit",
    ):
        response = test_app.client.get(path, follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/dashboard/login"


def test_login_flow_grants_dashboard_access(test_app):
    _provision_admin(test_app)
    _login(test_app)
    response = test_app.client.get("/dashboard/overview", follow_redirects=False)
    assert response.status_code == 200
    assert "MKY PisoNet Central" in response.text
    assert "root" in response.text


def test_login_post_without_csrf_is_rejected(test_app):
    _provision_admin(test_app)
    response = test_app.client.post(
        "/dashboard/login",
        data={"username": "root", "password": "sup3rsecret!"},
        follow_redirects=False,
    )
    assert response.status_code == 403


def test_login_post_with_wrong_csrf_is_rejected(test_app):
    _provision_admin(test_app)
    test_app.client.get("/dashboard/login")
    response = test_app.client.post(
        "/dashboard/login",
        data={"username": "root", "password": "sup3rsecret!", "_csrf": "forged"},
        follow_redirects=False,
    )
    assert response.status_code == 403


def test_login_with_bad_credentials_redirects_with_error(test_app):
    _provision_admin(test_app)
    test_app.client.get("/dashboard/login")
    csrf = test_app.client.cookies.get("pisonet_csrf")
    response = test_app.client.post(
        "/dashboard/login",
        data={"username": "root", "password": "wrong", "_csrf": csrf},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/dashboard/login?error=invalid"


def test_station_pages_render_for_authenticated_admin(test_app):
    _provision_admin(test_app)
    _enroll_station(test_app)
    _login(test_app)
    response = test_app.client.get("/dashboard/stations")
    assert response.status_code == 200
    assert "ST01" in response.text
    detail = test_app.client.get("/dashboard/stations/ST01")
    assert detail.status_code == 200
    assert "ST01" in detail.text
    fragment = test_app.client.get("/dashboard/stations/ST01/fragment")
    assert fragment.status_code == 200


def test_station_detail_404_for_unknown_station(test_app):
    _provision_admin(test_app)
    _login(test_app)
    response = test_app.client.get("/dashboard/stations/NOPE")
    assert response.status_code == 404


def test_web_lock_requires_csrf_then_succeeds(test_app):
    _provision_admin(test_app)
    _enroll_station(test_app)
    csrf = _login(test_app)
    # Missing CSRF -> rejected.
    response = test_app.client.post(
        "/dashboard/stations/ST01/lock", follow_redirects=False
    )
    assert response.status_code == 403
    # Double-submit via header -> accepted.
    response = test_app.client.post(
        "/dashboard/stations/ST01/lock",
        headers={"X-CSRF-Token": csrf},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "flash=locked" in response.headers["location"]


def test_history_pages_render_for_authenticated_admin(test_app):
    _provision_admin(test_app)
    _enroll_station(test_app)
    _login(test_app)
    for path in ("/dashboard/sessions", "/dashboard/ledger", "/dashboard/audit"):
        response = test_app.client.get(path)
        assert response.status_code == 200


def test_root_redirects_to_dashboard(test_app):
    response = test_app.client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/dashboard/overview"


def test_static_htmx_asset_is_served(test_app):
    response = test_app.client.get("/static/js/htmx.min.js")
    assert response.status_code == 200
    assert "htmx" in response.text
    assert len(response.text) > 10000


def test_static_css_is_served(test_app):
    response = test_app.client.get("/static/css/site.css")
    assert response.status_code == 200
    assert len(response.text) > 1000
