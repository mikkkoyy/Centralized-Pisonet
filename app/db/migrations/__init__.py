"""Migration package: numbered schema migrations."""

from app.db.migrations import _0001_initial  # noqa: F401

__all__ = ["_0001_initial"]
