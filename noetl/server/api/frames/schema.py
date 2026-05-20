from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

from noetl.core.resource_locator import ResourceLocatorError, parse_noetl_locator


_DURABLE_REF_KEYS = ("ref", "uri", "locator")


def _has_ipc_hint(value: Any) -> bool:
    if isinstance(value, dict):
        if isinstance(value.get("ipc"), dict):
            return True
        return any(_has_ipc_hint(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_ipc_hint(item) for item in value)
    return False


def _has_durable_reference(value: Any) -> bool:
    if isinstance(value, dict):
        for key in _DURABLE_REF_KEYS:
            if _is_valid_durable_locator(value.get(key)):
                return True
        return any(_has_durable_reference(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_durable_reference(item) for item in value)
    return False


def _is_valid_durable_locator(value: Any) -> bool:
    locator = str(value or "").strip()
    if not locator:
        return False
    if not locator.startswith("noetl://"):
        return True
    try:
        parse_noetl_locator(locator)
        return True
    except ResourceLocatorError:
        return False


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

    @model_validator(mode="after")
    def validate_output_ref_replay_authority(self) -> "FrameCommitRequest":
        # IPC is a same-node cache hint only. If a committed frame advertises
        # shared-memory metadata, the event must still contain a durable
        # reference so replay/projectors can reproduce state after cache GC.
        if self.output_ref and _has_ipc_hint(self.output_ref) and not _has_durable_reference(self.output_ref):
            raise ValueError("output_ref with ipc hint must include a durable ref, uri, or locator")
        return self
