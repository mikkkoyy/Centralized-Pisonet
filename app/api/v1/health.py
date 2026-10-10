"""Health endpoint — availability only, no internals or secrets."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app import __version__
from app.core.protocol import PROTOCOL_VERSION

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request) -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "protocol_version": PROTOCOL_VERSION,
        "environment": request.app.state.settings.environment,
    }
