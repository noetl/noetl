from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Protocol


class ProjectionConflict(RuntimeError):
    """Raised when an idempotent projection write regresses version."""


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def projection_checksum(state: dict[str, Any]) -> str:
    payload = json.dumps(
        state,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class ProjectionRecord:
    projection_id: str
    projection_type: str
    state: dict[str, Any]
    version: int
    tenant_id: str = "default"
    organization_id: str = "default"
    execution_id: Optional[int] = None
    source_event_id: Optional[int] = None
    checksum: Optional[str] = None
    meta: dict[str, Any] = field(default_factory=dict)

    def resolved_checksum(self) -> str:
        return self.checksum or projection_checksum(self.state)


@dataclass(frozen=True)
class ProjectionSnapshot:
    aggregate_id: str
    aggregate_type: str
    snapshot: dict[str, Any]
    version: int
    tenant_id: str = "default"
    organization_id: str = "default"
    checksum: Optional[str] = None
    meta: dict[str, Any] = field(default_factory=dict)

    def resolved_checksum(self) -> str:
        return self.checksum or projection_checksum(self.snapshot)


@dataclass(frozen=True)
class ProjectionQuery:
    tenant_id: Optional[str] = None
    organization_id: Optional[str] = None
    projection_type: Optional[str] = None
    execution_id: Optional[int] = None
    limit: int = 100


class ProjectionStore(Protocol):
    async def save_projection(self, record: ProjectionRecord) -> bool:
        """Save a projection. Return True when state changed."""

    async def load_projection(self, projection_id: str) -> Optional[ProjectionRecord]:
        """Load the current projection state."""

    async def query_projections(self, query: ProjectionQuery) -> list[ProjectionRecord]:
        """Query projections by tenant, type, execution, or backend-supported indexes."""

    async def save_snapshot(self, snapshot: ProjectionSnapshot) -> bool:
        """Save an aggregate snapshot. Return True when state changed."""

    async def load_snapshot(
        self,
        aggregate_id: str,
        *,
        aggregate_type: Optional[str] = None,
    ) -> Optional[ProjectionSnapshot]:
        """Load the latest aggregate snapshot."""
