"""
Pydantic request/response models for the internal API.

These shapes are the **contract** the system worker pool's playbooks
depend on.  Treat changes as breaking — coordinate with
``system/outbox_publisher`` and ``system/projector`` playbooks before
modifying.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Outbox claim
# ---------------------------------------------------------------------------


class OutboxClaimRequest(BaseModel):
    """Request body for ``POST /api/internal/outbox/claim``."""

    limit: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Maximum rows to claim in this batch.",
    )


class OutboxRow(BaseModel):
    """One outbox row returned by the claim endpoint.

    Mirrors the column subset ``claim_outbox_batch`` returns today
    in ``noetl.core.outbox``.  The system playbook iterates over
    ``rows`` and publishes each ``payload`` to NATS.
    """

    outbox_id: int
    event_id: int
    execution_id: Optional[int] = None
    subject: Optional[str] = None
    payload: dict[str, Any]
    payload_codec: str = "arrow-feather"
    attempts: int = 0


class OutboxClaimResponse(BaseModel):
    """Response body for ``POST /api/internal/outbox/claim``."""

    rows: list[OutboxRow] = Field(default_factory=list)
    claimed: int = Field(
        default=0,
        description="Number of rows claimed and marked IN_FLIGHT.",
    )


# ---------------------------------------------------------------------------
# Outbox mark published
# ---------------------------------------------------------------------------


class OutboxMarkPublishedRequest(BaseModel):
    """Request body for ``POST /api/internal/outbox/mark-published``."""

    outbox_ids: list[int] = Field(
        ...,
        min_length=1,
        description="Outbox row IDs to mark PUBLISHED.",
    )


class OutboxMarkPublishedResponse(BaseModel):
    """Response body for ``POST /api/internal/outbox/mark-published``."""

    marked: int = Field(
        default=0,
        description="Number of rows successfully marked PUBLISHED.",
    )


# ---------------------------------------------------------------------------
# Outbox mark failed
# ---------------------------------------------------------------------------


class OutboxMarkFailedRequest(BaseModel):
    """Request body for ``POST /api/internal/outbox/mark-failed``."""

    outbox_id: int = Field(..., description="Outbox row ID to mark FAILED.")
    error: str = Field(..., description="Error message (truncated to 2000 chars).")
    attempts: int = Field(
        default=1,
        ge=1,
        description="Current attempt count; used for backoff calculation.",
    )
    max_delay_seconds: int = Field(
        default=300,
        ge=1,
        description="Cap on the exponential backoff delay.",
    )


class OutboxMarkFailedResponse(BaseModel):
    """Response body for ``POST /api/internal/outbox/mark-failed``."""

    marked: bool = Field(
        default=False,
        description="True if the row was updated to FAILED.",
    )
    available_at_in: int = Field(
        default=0,
        description="Seconds until the row is eligible for re-claim.",
    )


# ---------------------------------------------------------------------------
# Outbox pending count (KEDA scaler trigger source)
# ---------------------------------------------------------------------------


class OutboxPendingCountResponse(BaseModel):
    """Response body for ``GET /api/internal/outbox/pending-count``.

    KEDA's HTTP scaler reads this; the body is intentionally minimal so
    the scaler config stays simple.
    """

    pending: int = Field(
        default=0,
        description="Rows in PENDING/FAILED status with available_at <= now().",
    )


# ---------------------------------------------------------------------------
# Events projector
# ---------------------------------------------------------------------------


class EventEnvelope(BaseModel):
    """One event envelope as the projector receives it.

    Tolerates extra fields to keep the projector loose-coupled with
    the event-emitter side (worker, executor, server).  Required fields
    mirror what the Python projector's batch INSERT needs.
    """

    model_config = {"extra": "allow"}

    event_id: int
    execution_id: Optional[int] = None
    parent_event_id: Optional[int] = None
    event_type: Optional[str] = None
    node_id: Optional[str] = None
    node_name: Optional[str] = None
    node_type: Optional[str] = None
    status: Optional[str] = None
    duration: Optional[float] = None
    timestamp: Optional[str] = None
    payload: Optional[dict[str, Any]] = None
    context: Optional[dict[str, Any]] = None
    result: Optional[dict[str, Any]] = None
    meta: Optional[dict[str, Any]] = None
    stack_trace: Optional[str] = None
    error: Optional[str] = None
    trace_component: Optional[str] = None


class EventsProjectRequest(BaseModel):
    """Request body for ``POST /api/internal/events/project``."""

    events: list[EventEnvelope] = Field(
        ...,
        min_length=1,
        description="Batch of event envelopes to project into noetl.event.",
    )


class EventsProjectResponse(BaseModel):
    """Response body for ``POST /api/internal/events/project``."""

    projected: int = Field(
        default=0,
        description="Rows actually INSERTed (excludes ON CONFLICT skips).",
    )
    duplicates: int = Field(
        default=0,
        description="Rows skipped due to ON CONFLICT (event_id) DO NOTHING.",
    )
