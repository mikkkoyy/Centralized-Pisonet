"""Shared schema helpers."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.core.protocol import SUPPORTED_PROTOCOL_VERSIONS


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1, le=100000)
    limit: int = Field(default=25, ge=1, le=100)


def require_protocol_version(version: Optional[int]) -> int:
    """Validate a requested protocol version."""
    if version is None:
        raise ValueError("protocol_version is required")
    if version not in SUPPORTED_PROTOCOL_VERSIONS:
        raise ValueError(f"unsupported protocol_version {version}")
    return version


class ErrorResponse(BaseModel):
    detail: str
    code: str
