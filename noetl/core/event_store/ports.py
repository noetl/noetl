from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Protocol


class ExpectedVersionConflict(RuntimeError):
    """Raised when append expected_version does not match stream state."""

    def __init__(self, *, stream_id: str, expected_version: int, actual_version: int):
        super().__init__(
            f"stream {stream_id!r} expected version {expected_version}, actual {actual_version}"
        )
        self.stream_id = stream_id
        self.expected_version = expected_version
        self.actual_version = actual_version


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def canonical_event_checksum(value: dict[str, Any]) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class EventRecord:
    """Backend-neutral event-store record.

    Payloads must already be serialization-safe JSON-compatible values or
    references to immutable payload objects.
    """

    event_type: str
    stream_id: str
    tenant_id: str = "default"
    organization_id: str = "default"
    execution_id: Optional[int] = None
    aggregate_id: Optional[str] = None
    aggregate_type: Optional[str] = None
    schema_name: Optional[str] = None
    schema_version: int = 1
    producer: Optional[str] = None
    causation_id: Optional[str] = None
    correlation_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    payload_ref: Optional[dict[str, Any]] = None
    result: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    status: Optional[str] = None
    node_name: Optional[str] = None
    event_time: Optional[datetime] = None

    def envelope(self, *, stream_version: int, event_id: Optional[int] = None) -> dict[str, Any]:
        event_time = self.event_time or datetime.now(timezone.utc)
        envelope = {
            "event_id": event_id,
            "tenant_id": self.tenant_id,
            "organization_id": self.organization_id,
            "execution_id": self.execution_id,
            "stream_id": self.stream_id,
            "stream_version": stream_version,
            "aggregate_id": self.aggregate_id,
            "aggregate_type": self.aggregate_type,
            "event_type": self.event_type,
            "schema_name": self.schema_name or f"noetl.{self.event_type}",
            "schema_version": self.schema_version,
            "event_time": event_time,
            "producer": self.producer,
            "causation_id": self.causation_id,
            "correlation_id": self.correlation_id,
            "idempotency_key": self.idempotency_key,
            "payload_ref": self.payload_ref,
            "result": self.result,
            "meta": self.meta,
            "status": self.status,
            "node_name": self.node_name,
        }
        checksum_input = {k: v for k, v in envelope.items() if k != "event_id"}
        envelope["envelope_checksum"] = canonical_event_checksum(checksum_input)
        return envelope


class EventStore(Protocol):
    async def append(
        self,
        stream_id: str,
        events: list[EventRecord],
        *,
        expected_version: Optional[int] = None,
    ) -> int:
        """Append events and return the last written stream version."""

    async def read(
        self,
        stream_id: str,
        *,
        from_version: int = 1,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Read events from a stream in stream-version order."""
