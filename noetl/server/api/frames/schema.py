from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class FrameClaimRequest(BaseModel):
    """Request to claim or lazily mint frame leases for a stage."""

    worker_id: str = Field(..., min_length=1)
    command_id: Optional[int] = None
    requested_count: int = Field(1, ge=1, le=100)
    lease_seconds: int = Field(60, ge=5, le=3600)
    cursor: dict[str, Any] = Field(default_factory=dict)
    frame_policy: dict[str, Any] = Field(default_factory=dict)


class FrameHeartbeatRequest(BaseModel):
    """Request to extend a claimed/running frame lease."""

    worker_id: str = Field(..., min_length=1)
    lease_seconds: int = Field(60, ge=5, le=3600)
    status: str = Field("RUNNING")


class FrameCommitRequest(BaseModel):
    """Request to commit terminal frame output."""

    worker_id: str = Field(..., min_length=1)
    status: str = Field("COMPLETED")
    cursor: dict[str, Any] = Field(default_factory=dict)
    row_count: int = Field(0, ge=0)
    output_ref: Optional[dict[str, Any]] = None
    events_emitted: int = Field(0, ge=0)
    error: Optional[str] = None
