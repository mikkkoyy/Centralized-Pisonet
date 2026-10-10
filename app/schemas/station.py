"""Station registration and heartbeat schemas."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.core.protocol import PROTOCOL_VERSION
from app.schemas.common import require_protocol_version

STATION_CODE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$"


class StationRegisterRequest(BaseModel):
    station_code: str = Field(min_length=1, max_length=32)
    enrollment_secret: str = Field(min_length=16, max_length=256)
    display_name: Optional[str] = Field(default=None, max_length=64)
    mac_address: Optional[str] = Field(default=None, max_length=64)

    @field_validator("station_code")
    @classmethod
    def _check_code(cls, value: str) -> str:
        import re

        if not re.match(STATION_CODE_PATTERN, value):
            raise ValueError(
                "station_code must be 1-32 chars: letters, digits, dash, underscore"
            )
        return value


class StationRegisterResponse(BaseModel):
    station_id: int
    station_code: str
    token: str
    protocol_version: int
    enrolled_at: int


class HeartbeatRequest(BaseModel):
    protocol_version: int = Field(default=PROTOCOL_VERSION)

    @field_validator("protocol_version")
    @classmethod
    def _check_version(cls, value: int) -> int:
        return require_protocol_version(value)


class SessionState(BaseModel):
    session_id: int
    state: str  # "active"
    granted_seconds: int
    started_at: int
    remaining_seconds: int


class PendingCommand(BaseModel):
    id: int
    command_type: str
    payload: Optional[str] = None
    expires_at: int


class HeartbeatResponse(BaseModel):
    station_code: str
    protocol_version: int
    server_time: int
    station_state: str  # "available" | "occupied" | "offline" | "revoked"
    lock: str  # "locked" | "unlocked"
    session: Optional[SessionState] = None
    commands: list[PendingCommand] = []


class CommandAckResponse(BaseModel):
    acknowledged: bool
    command_id: int
