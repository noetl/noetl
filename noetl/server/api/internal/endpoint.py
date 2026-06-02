"""
FastAPI routes for the internal API.

All routes are gated by ``require_internal_api_token`` — the system
worker pool's ServiceAccount-token bearer auth.  User playbooks
calling these routes get 403.

Routes:

- ``POST /api/internal/outbox/claim``
- ``POST /api/internal/outbox/mark-published``
- ``POST /api/internal/outbox/mark-failed``
- ``GET  /api/internal/outbox/pending-count``
- ``POST /api/internal/events/project``
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from noetl.core.logger import setup_logger

from .auth import require_internal_api_token
from .schema import (
    EventsProjectRequest,
    EventsProjectResponse,
    OutboxClaimRequest,
    OutboxClaimResponse,
    OutboxMarkFailedRequest,
    OutboxMarkFailedResponse,
    OutboxMarkPublishedRequest,
    OutboxMarkPublishedResponse,
    OutboxPendingCountResponse,
    OutboxRow,
)
from . import service

logger = setup_logger(__name__, include_location=True)


router = APIRouter(
    prefix="/api/internal",
    tags=["internal"],
    dependencies=[Depends(require_internal_api_token)],
)


# ---------------------------------------------------------------------------
# Outbox
# ---------------------------------------------------------------------------


@router.post(
    "/outbox/claim",
    response_model=OutboxClaimResponse,
    summary="Claim a batch of outbox rows for publishing.",
)
async def outbox_claim(request: OutboxClaimRequest) -> OutboxClaimResponse:
    """Claim a batch of PENDING/FAILED outbox rows and mark them IN_FLIGHT.

    Replaces the direct-DB call ``noetl.core.outbox.claim_outbox_batch``
    that today's Python publisher makes.  The system worker pool's
    ``system/outbox_publisher`` playbook calls this endpoint instead.

    The server runs the underlying ``SELECT ... FOR UPDATE SKIP LOCKED``
    inside a transaction; only this server has direct DB access (per
    data-access-boundary rule).
    """

    rows = await service.claim_batch(limit=request.limit)
    return OutboxClaimResponse(
        rows=[OutboxRow(**row) for row in rows],
        claimed=len(rows),
    )


@router.post(
    "/outbox/mark-published",
    response_model=OutboxMarkPublishedResponse,
    summary="Mark a batch of outbox rows PUBLISHED.",
)
async def outbox_mark_published(
    request: OutboxMarkPublishedRequest,
) -> OutboxMarkPublishedResponse:
    """Mark a batch of outbox rows PUBLISHED.

    Called after the system playbook successfully publishes the rows'
    payloads to NATS.  Idempotent — re-marking an already-published row
    is a no-op.
    """

    marked = await service.mark_published_batch(request.outbox_ids)
    return OutboxMarkPublishedResponse(marked=marked)


@router.post(
    "/outbox/mark-failed",
    response_model=OutboxMarkFailedResponse,
    summary="Mark an outbox row FAILED with exponential backoff.",
)
async def outbox_mark_failed(
    request: OutboxMarkFailedRequest,
) -> OutboxMarkFailedResponse:
    """Mark a single outbox row FAILED.

    Called when a per-row publish fails inside the system playbook
    iterator.  The server applies exponential backoff to ``available_at``
    so the row is re-claimable after the delay.
    """

    delay = await service.mark_failed_row(
        outbox_id=request.outbox_id,
        error=request.error,
        attempts=request.attempts,
        max_delay_seconds=request.max_delay_seconds,
    )
    return OutboxMarkFailedResponse(marked=True, available_at_in=delay)


@router.get(
    "/outbox/pending-count",
    response_model=OutboxPendingCountResponse,
    summary="Count rows in PENDING/FAILED status with available_at <= now().",
)
async def outbox_pending_count() -> OutboxPendingCountResponse:
    """Outbox-backlog gauge for the KEDA HTTP scaler.

    Returned shape stays minimal so the scaler config is just
    ``valueLocation: pending``.
    """

    pending = await service.pending_count()
    return OutboxPendingCountResponse(pending=pending)


# ---------------------------------------------------------------------------
# Events projector
# ---------------------------------------------------------------------------


@router.post(
    "/events/project",
    response_model=EventsProjectResponse,
    summary="Batch-INSERT events into noetl.event (the durable log).",
)
async def events_project(request: EventsProjectRequest) -> EventsProjectResponse:
    """Project a batch of events from NATS into ``noetl.event``.

    Idempotent via ``ON CONFLICT (event_id) DO NOTHING``.  The system
    playbook (``system/projector``) calls this after pulling a batch from
    NATS; on server 2xx the playbook acks the NATS batch.
    """

    # Serialize to plain dicts so the service layer can use jsonb_array_elements.
    events = [event.model_dump(exclude_none=False) for event in request.events]
    try:
        projected, duplicates = await service.project_events(events)
    except Exception as exc:
        logger.exception("events/project failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"events/project failed: {exc}",
        )
    return EventsProjectResponse(projected=projected, duplicates=duplicates)
