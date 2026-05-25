"""Replay API endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from noetl.core.logger import setup_logger
from noetl.core.sanitize import redact_keychain_values

from .service import ReplayCutoff, ReplayService

logger = setup_logger(__name__, include_location=True)
router = APIRouter(prefix="/replay", tags=["replay"])


@router.get("/state")
async def replay_state(
    execution_id: int = Query(..., description="Execution id to replay"),
    tenant_id: str = Query("default", description="Tenant boundary for replay"),
    organization_id: str = Query("default", description="Organization boundary for replay"),
    as_of_event_id: Optional[int] = Query(None, description="Replay through this event id"),
    as_of_position: Optional[int] = Query(None, description="Alias for event position cutoff"),
    as_of_time: Optional[datetime] = Query(None, description="Replay through this event_time"),
    projection: str = Query("all", description="Projection to fold: execution | frame | loop | business_object | all"),
    limit: int = Query(10000, ge=1, le=100000, description="Maximum events to fold in this Phase 0 endpoint"),
    resolve_payloads: bool = Query(False, description="Resolve payload refs and return bounded verification summaries"),
) -> dict:
    """Reconstruct lightweight state from canonical events.

    Phase 0 returns a deterministic fold and checksum. Later phases will add
    snapshot selection, payload resolution, and schema upcasters.
    """

    cutoffs = [as_of_event_id is not None, as_of_position is not None, as_of_time is not None]
    if sum(cutoffs) > 1:
        raise HTTPException(
            status_code=400,
            detail="Use only one replay cutoff: as_of_event_id, as_of_position, or as_of_time",
        )
    try:
        return redact_keychain_values(await ReplayService.replay_state(
            tenant_id=tenant_id,
            organization_id=organization_id,
            execution_id=execution_id,
            cutoff=ReplayCutoff(
                as_of_event_id=as_of_event_id,
                as_of_position=as_of_position,
                as_of_time=as_of_time,
            ),
            projection=projection,
            limit=limit,
            resolve_payloads=resolve_payloads,
        ))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Replay state failed: execution_id=%s error=%s", execution_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
