"""Administrator auth tests: provisioning, Argon2id login, throttling."""

from __future__ import annotations

import pytest

from app.services.admin import (
    AdminAuthError,
    AdminProvisionError,
    ThrottledError,
    has_any_admin,
    login,
    provision_admin,
)


def test_no_default_admin_exists(db_session):
    assert has_any_admin(db_session) is False


def test_first_admin_provisioned_exactly_once(db_session, clock):
    admin = provision_admin(
        db_session, username="root", password="sup3rsecret!", clock=clock
    )
    assert admin.username == "root"
    assert admin.role == "admin"
    assert admin.password_hash != "sup3rsecret!"
    assert "$argon2" in admin.password_hash
    assert has_any_admin(db_session) is True
    with pytest.raises(AdminProvisionError):
        provision_admin(
            db_session, username="second", password="whatever123", clock=clock
        )


def test_login_success_updates_last_login(db_session, clock):
    provision_admin(db_session, username="root", password="sup3rsecret!", clock=clock)
    admin = login(
        db_session,
        username="root",
        password="sup3rsecret!",
        ip_address="127.0.0.1",
        clock=clock,
    )
    assert admin.username == "root"
    assert admin.last_login_at == clock.now


def test_login_wrong_password_rejected(db_session, clock):
    provision_admin(db_session, username="root", password="sup3rsecret!", clock=clock)
    with pytest.raises(AdminAuthError):
        login(
            db_session,
            username="root",
            password="wrong",
            ip_address="127.0.0.1",
            clock=clock,
        )


def test_login_unknown_user_returns_generic_error(db_session, clock):
    with pytest.raises(AdminAuthError):
        login(db_session, username="ghost", password="whatever", clock=clock)


def test_inactive_admin_cannot_login(db_session, clock):
    admin = provision_admin(db_session, username="root", password="sup3rsecret!", clock=clock)
    admin.is_active = False
    db_session.commit()
    with pytest.raises(AdminAuthError):
        login(db_session, username="root", password="sup3rsecret!", clock=clock)


def test_throttling_after_five_failures(db_session, clock):
    provision_admin(db_session, username="root", password="sup3rsecret!", clock=clock)
    for _ in range(5):
        with pytest.raises(AdminAuthError):
            login(
                db_session,
                username="root",
                password="wrong",
                ip_address="10.0.0.5",
                clock=clock,
            )
    # Even the correct password is blocked while throttled.
    with pytest.raises(ThrottledError):
        login(
            db_session,
            username="root",
            password="sup3rsecret!",
            ip_address="10.0.0.5",
            clock=clock,
        )


def test_throttle_window_expires(db_session, clock):
    provision_admin(db_session, username="root", password="sup3rsecret!", clock=clock)
    for _ in range(5):
        with pytest.raises(AdminAuthError):
            login(
                db_session,
                username="root",
                password="wrong",
                ip_address="10.0.0.5",
                clock=clock,
            )
    clock.advance(15 * 60 + 1)
    admin = login(
        db_session,
        username="root",
        password="sup3rsecret!",
        ip_address="10.0.0.5",
        clock=clock,
    )
    assert admin.username == "root"


def test_throttling_is_scoped_per_username(db_session, clock):
    from app.core.security import hash_password
    from app.models.admin import Admin

    provision_admin(db_session, username="root", password="sup3rsecret!", clock=clock)
    # Additional accounts are created through an authenticated
    # administrator session in production; insert directly here.
    db_session.add(
        Admin(
            username="ops",
            password_hash=hash_password("opssecret!"),
            created_at=clock(),
        )
    )
    db_session.commit()
    for _ in range(5):
        with pytest.raises(AdminAuthError):
            login(db_session, username="root", password="wrong", clock=clock)
    with pytest.raises(ThrottledError):
        login(db_session, username="root", password="sup3rsecret!", clock=clock)
    # A different username is unaffected by root's failures.
    admin = login(db_session, username="ops", password="opssecret!", clock=clock)
    assert admin.username == "ops"
