"""Station model — identity, credential verifier, heartbeat state."""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Station(Base):
    __tablename__ = "stations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    station_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(64))
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_prefix: Mapped[str | None] = mapped_column(String(12))
    enrolled_at: Mapped[int] = mapped_column(Integer, nullable=False)
    last_seen_at: Mapped[int | None] = mapped_column(Integer)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    # Informational only — MAC addresses are NEVER used as proof of identity.
    mac_address: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    protocol_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
