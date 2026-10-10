"""Ledger model — immutable idempotent credit records."""

from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    station_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    session_id: Mapped[int | None] = mapped_column(Integer)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    seconds_credited: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
