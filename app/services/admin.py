"""Administrator service — provisioning, login, throttling.

Security properties:
- No default administrator account or password exists. The
  first administrator is provisioned explicitly (CLI) when
  no administrator is present.
- Passwords are hashed with Argon2id; only the hash is stored.
- Login failures are recorded; 5 failures within 15 minutes
  from one username/IP block further attempts for the window.
- Authentication failures return generic messages and never
  reveal whether the username exists.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.models.admin import Admin, AdminLoginAttempt
from app.services.audit import record
from app.services.timeutil import Clock, utcnow


class AdminError(RuntimeError):
    pass


class AdminProvisionError(AdminError):
    pass


class AdminAuthError(AdminError):
    pass


class ThrottledError(AdminError):
    pass


# Login throttling policy.
THROTTLE_LIMIT = 5
THROTTLE_WINDOW_SECONDS = 15 * 60


def has_any_admin(db: Session) -> bool:
    return db.query(Admin).limit(1).count() > 0


def provision_admin(
    db: Session,
    *,
    username: str,
    password: str,
    clock: Clock = utcnow,
) -> Admin:
    """Provision the initial administrator. Only succeeds when
    no administrator exists yet (prevents silent account
    creation on a running system)."""
    if has_any_admin(db):
        raise AdminProvisionError(
            "An administrator already exists; create additional "
            "accounts through an authenticated administrator session."
        )
    from app.core.security import hash_password

    admin = Admin(
        username=username,
        password_hash=hash_password(password),
        created_at=clock(),
    )
    db.add(admin)
    record(
        db,
        actor_type="system",
        event_type="admin.provisioned",
        summary=f"Initial administrator {username!r} provisioned",
        entity_type="admin",
        entity_id=admin.id,
        clock=clock,
    )
    db.commit()
    return admin


def get_admin(db: Session, username: str) -> Optional[Admin]:
    return db.query(Admin).filter(Admin.username == username).first()


def _recent_failures(
    db: Session,
    username: str,
    ip_address: Optional[str],
    now: int,
) -> int:
    cutoff = now - THROTTLE_WINDOW_SECONDS
    return (
        db.query(AdminLoginAttempt)
        .filter(
            AdminLoginAttempt.username == username,
            AdminLoginAttempt.succeeded.is_(False),
            AdminLoginAttempt.attempted_at >= cutoff,
        )
        .count()
    )


def login(
    db: Session,
    *,
    username: str,
    password: str,
    ip_address: Optional[str] = None,
    clock: Clock = utcnow,
) -> Admin:
    """Authenticate an administrator. Applies throttling and
    records every attempt. Raises ThrottledError when the
    attempt limit is exceeded."""
    now = clock()
    failures = _recent_failures(db, username, ip_address, now)
    if failures >= THROTTLE_LIMIT:
        record(
            db,
            actor_type="system",
            event_type="admin.login_throttled",
            summary=f"Login throttled for username={username!r} from {ip_address or 'unknown'}",
            clock=clock,
        )
        db.commit()
        raise ThrottledError("Too many failed login attempts; try again later")

    admin = get_admin(db, username)
    # Verify against a dummy hash when the user is unknown so the
    # response time does not reveal username existence.
    from app.core.security import hash_password, verify_password

    verifier = admin.password_hash if admin is not None else hash_password(secrets.token_urlsafe(16))
    ok = verify_password(password, verifier) and admin is not None and admin.is_active

    attempt = AdminLoginAttempt(
        username=username,
        ip_address=ip_address,
        succeeded=ok,
        attempted_at=now,
    )
    db.add(attempt)

    if not ok:
        record(
            db,
            actor_type="system",
            event_type="admin.login_failed",
            summary=f"Failed admin login for username={username!r} from {ip_address or 'unknown'}",
            clock=clock,
        )
        db.commit()
        raise AdminAuthError("Invalid username or password")

    admin.last_login_at = now
    record(
        db,
        actor_type="admin",
        actor_id=admin.id,
        event_type="admin.login_succeeded",
        summary=f"Administrator {username!r} logged in",
        entity_type="admin",
        entity_id=admin.id,
        clock=clock,
    )
    db.commit()
    return admin


def list_admins(db: Session) -> list[Admin]:
    return db.query(Admin).order_by(Admin.id).all()
