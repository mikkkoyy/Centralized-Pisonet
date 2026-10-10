"""Security primitives: password hashing, token hashing, JWT.

- Administrator passwords: Argon2id via argon2-cffi.
- Station tokens and enrollment secrets: SHA-256 verifiers only;
  raw values are never persisted.
- Admin sessions: HS256 JWT signed with SECRET_KEY.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Optional

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import Settings

_argon2 = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)


def hash_password(password: str) -> str:
    """Argon2id hash of an administrator password."""
    return _argon2.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time-ish Argon2id verification. Returns False on
    any mismatch or malformed hash (never raises)."""
    try:
        return _argon2.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        # Malformed stored hash must never crash the request.
        return False


def hash_verifier(secret: str) -> str:
    """SHA-256 hex verifier for a bearer-style secret (station token,
    enrollment secret). Only the verifier is stored."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def secrets_equal(provided: str, stored_verifier: str) -> bool:
    """Constant-time comparison of a provided secret against a
    stored SHA-256 verifier."""
    return hmac.compare_digest(hash_verifier(provided), stored_verifier)


def generate_token(length: int = 32) -> str:
    """Cryptographically random URL-safe token."""
    return secrets.token_urlsafe(length)


def create_admin_token(subject: str, settings: Settings, expires_in: int = 8 * 3600) -> str:
    """Signed admin session JWT. ``sub`` is the admin username."""
    now = int(time.time())
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + expires_in,
        "type": "admin_session",
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_admin_token(token: str, settings: Settings) -> Optional[str]:
    """Validate an admin session JWT. Returns the username or None."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if payload.get("type") != "admin_session":
        return None
    sub = payload.get("sub")
    return sub if isinstance(sub, str) else None
