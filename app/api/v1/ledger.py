"""Ledger API — idempotent credit operations (administrators only).

POST /api/v1/admin/ledger/credits
    Credit a station. Requires an idempotency key. Repeating the
    same key with the same payload returns the original record
    (HTTP 200, idempotent=true). Repeating the key with a
    different payload is rejected with HTTP 409 and audited.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin
from app.models.admin import Admin
from app.schemas.ledger import LedgerCreditRequest, LedgerCreditResponse
from app.services.ledger import (
    IdempotencyConflictError,
    LedgerError,
    UnknownStationError,
    credit,
)

router = APIRouter(prefix="/api/v1/admin", tags=["ledger"])


@router.post("/ledger/credits", response_model=LedgerCreditResponse)
def create_credit(
    body: LedgerCreditRequest,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_admin),
) -> LedgerCreditResponse:
    try:
        result = credit(
            db,
            station_code=body.station_code,
            amount_cents=body.amount_cents,
            seconds=body.seconds,
            idempotency_key=body.idempotency_key,
            reference=body.reference,
            actor_id=admin.id,
        )
    except UnknownStationError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except LedgerError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    now = int(time.time())
    response = LedgerCreditResponse(
        entry_id=result.entry.id,
        station_code=body.station_code,
        session_id=result.entry.session_id,
        session_state=result.session_state,
        granted_seconds=result.session.granted_seconds if result.session else 0,
        remaining_seconds=(
            result.session.remaining_seconds(now) if result.session else 0
        ),
        amount_cents=result.entry.amount_cents,
        seconds_credited=result.entry.seconds_credited,
        idempotent=result.idempotent,
        created_at=result.entry.created_at,
    )
    # 201 for a new credit, 200 for an idempotent replay.
    return JSONResponse(status_code=(200 if result.idempotent else 201), content=response.model_dump())
