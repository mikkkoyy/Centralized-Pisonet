"""Administrator schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class AdminLoginResponse(BaseModel):
    username: str
    role: str


class AdminProvisionRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=256)


class AdminSessionResponse(BaseModel):
    username: str
    role: str


class StationPreRegisterRequest(BaseModel):
    station_code: str = Field(min_length=1, max_length=32)
    display_name: str | None = Field(default=None, max_length=64)


class StationManagementResponse(BaseModel):
    station_id: int
    station_code: str
    token: str | None = None  # present only on issue/rotation
