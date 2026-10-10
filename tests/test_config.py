"""Configuration validation tests."""

from __future__ import annotations

import pytest

from app.core.config import Settings, get_settings, reset_settings_cache


def test_missing_secret_key_raises(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings().validate_or_generate_secrets()


def test_short_secret_key_raises(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "short")
    with pytest.raises(ValueError, match="at least 32"):
        Settings().validate_or_generate_secrets()


def test_enrollment_secret_auto_generated_once(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "k" * 64)
    monkeypatch.delenv("ENROLLMENT_SECRET", raising=False)
    settings = Settings()
    notices = settings.validate_or_generate_secrets()
    assert settings.enrollment_secret
    assert len(settings.enrollment_secret) >= 32
    assert len(notices) == 1
    assert "ENROLLMENT_SECRET" in notices[0]


def test_invalid_environment_rejected(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "staging")
    with pytest.raises(ValueError):
        Settings()


def test_nonpositive_values_rejected(monkeypatch):
    monkeypatch.setenv("SERVER_PORT", "0")
    with pytest.raises(ValueError):
        Settings()
    monkeypatch.delenv("SERVER_PORT", raising=False)
    monkeypatch.setenv("STATION_HEARTBEAT_TIMEOUT", "-1")
    with pytest.raises(ValueError):
        Settings()


def test_valid_configuration_accepted(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "k" * 64)
    monkeypatch.setenv("ENROLLMENT_SECRET", "e" * 40)
    settings = Settings()
    assert settings.validate_or_generate_secrets() == []
    assert settings.is_production is False


def test_settings_are_cached(monkeypatch):
    reset_settings_cache()
    monkeypatch.setenv("STATION_HEARTBEAT_TIMEOUT", "45")
    assert get_settings().station_heartbeat_timeout == 45
    monkeypatch.setenv("STATION_HEARTBEAT_TIMEOUT", "99")
    # Still the cached instance...
    assert get_settings().station_heartbeat_timeout == 45
    # ...until explicitly cleared.
    reset_settings_cache()
    assert get_settings().station_heartbeat_timeout == 99
