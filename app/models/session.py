"""Session model — server-authoritative billing record."""

from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Explicit session end reasons (stored in sessions.end_reason).
END_EXPIRED = "expired"
END_ADMIN = "admin_terminated"
END_COMPLETED = "completed"


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    station_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    granted_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[int] = mapped_column(Integer, nullable=False)
    ended_at: Mapped[int | None] = mapped_column(Integer)
    end_reason: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)

    @property
    def is_active(self) -> bool:
        return self.ended_at is None

    def remaining_seconds(self, now: int) -> int:
        """Server-authoritative remaining time in seconds."""
        if self.ended_at is not None:
            return 0
        return max(0, self.granted_seconds - (now - self.started_at))
