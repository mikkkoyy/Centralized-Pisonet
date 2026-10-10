"""Ledger schemas."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class LedgerCreditRequest(BaseModel):
    station_code: str = Field(min_length=1, max_length=32)
    amount_cents: int = Field(ge=0, le=100_000_000)
    seconds: int = Field(ge=0, le=31_536_000)
    idempotency_key: str = Field(min_length=1, max_length=128)
    reference: Optional[str] = Field(default=None, max_length=128)


class LedgerCreditResponse(BaseModel):
    entry_id: int
    station_code: str
    session_id: Optional[int] = None
    session_state: str  # "active" | "none"
    granted_seconds: int
    remaining_seconds: int
    amount_cents: int
    seconds_credited: int
    idempotent: bool
    created_at: int


class LedgerEntryResponse(BaseModel):
    id: int
    idempotency_key: str
    station_code: str
    session_id: Optional[int]
    amount_cents: int
    seconds_credited: int
    reference: Optional[str] = None
    created_at: int
