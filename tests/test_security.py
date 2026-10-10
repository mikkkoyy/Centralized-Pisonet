"""Security primitives: Argon2id, SHA-256 verifiers, JWT."""

from __future__ import annotations

import hashlib
import time

import jwt as pyjwt
import pytest

from app.core.config import Settings
from app.core.security import (
    create_admin_token,
    decode_admin_token,
    generate_token,
    hash_password,
    hash_verifier,
    secrets_equal,
    verify_password,
)


def test_password_hash_roundtrip():
    password = "correct horse battery staple"
    password_hash = hash_password(password)
    assert password_hash != password
    assert "$argon2" in password_hash
    assert verify_password(password, password_hash) is True
    assert verify_password("wrong password", password_hash) is False


def test_verify_malformed_hash_never_raises():
    assert verify_password("anything", "not-an-argon2-hash") is False
    assert verify_password("anything", "") is False


def test_hash_verifier_is_sha256_hex():
    assert hash_verifier("token") == hashlib.sha256(b"token").hexdigest()


def test_secrets_equal_constant_time():
    verifier = hash_verifier("shared-secret")
    assert secrets_equal("shared-secret", verifier) is True
    assert secrets_equal("other-secret", verifier) is False


def test_generate_token_is_random_and_url_safe():
    tokens = {generate_token() for _ in range(32)}
    assert len(tokens) == 32
    token = generate_token()
    assert len(token) >= 32
    assert " " not in token


def test_admin_jwt_roundtrip(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "k" * 64)
    settings = Settings()
    token = create_admin_token("root", settings)
    assert decode_admin_token(token, settings) == "root"


def test_admin_jwt_rejected_with_wrong_key(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "a" * 64)
    settings = Settings()
    token = create_admin_token("root", settings)
    monkeypatch.setenv("SECRET_KEY", "b" * 64)
    other = Settings()
    assert decode_admin_token(token, other) is None


def test_admin_jwt_rejected_with_wrong_type(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "k" * 64)
    settings = Settings()
    now = int(time.time())
    forged = pyjwt.encode(
        {"sub": "root", "iat": now, "exp": now + 3600, "type": "other"},
        settings.secret_key,
        algorithm="HS256",
    )
    assert decode_admin_token(forged, settings) is None


def test_admin_jwt_rejects_garbage(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "k" * 64)
    settings = Settings()
    assert decode_admin_token("garbage", settings) is None
    assert decode_admin_token("", settings) is None
