from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Protocol, Union

from noetl.core.payload_store.ports import PayloadReference


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


#: Marker on serialized payload_ref dicts that originated from a
#: :class:`noetl.core.payload_store.PayloadReference`. Consumers
#: (replay locator, future PayloadStore-aware resolver) use this
#: discriminator to recognize payload-store-backed references
#: without inspecting field shapes.
PAYLOAD_REF_KIND_PAYLOAD_STORE = "payload_store"


def payload_ref_to_dict(
    value: Optional[Union[PayloadReference, dict[str, Any]]],
) -> Optional[dict[str, Any]]:
    """Normalize an event ``payload_ref`` to a JSON-column-compatible dict.

    Accepts three shapes:

    - ``None`` — returned unchanged.
    - :class:`PayloadReference` — serialized to a canonical dict with the
      ``kind`` discriminator set to
      :data:`PAYLOAD_REF_KIND_PAYLOAD_STORE` plus every reference field
      (``sha256``, ``byte_length``, ``content_type``, ``uri``,
      ``metadata``).
    - ``dict`` — returned unchanged. Used both for legacy
      TempStore-shaped references (``{"ref": ..., "kind": "result_ref"}``)
      and for already-serialized PayloadReference dicts coming back off
      the postgres ``payload_ref`` JSON column.

    Any other input raises :class:`TypeError` with a clear message —
    the envelope must never carry a non-serializable ``payload_ref``.
    """
    if value is None:
        return None
    if isinstance(value, PayloadReference):
        return {
            "kind": PAYLOAD_REF_KIND_PAYLOAD_STORE,
            "sha256": value.sha256,
            "byte_length": value.byte_length,
            "content_type": value.content_type,
            "uri": value.uri,
            "metadata": dict(value.metadata),
        }
    if isinstance(value, dict):
        return value
    raise TypeError(
        "EventRecord.payload_ref must be None, a PayloadReference, or a "
        f"dict; got {type(value).__name__}"
    )


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
    payload_ref: Optional[Union[PayloadReference, dict[str, Any]]] = None
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
            "payload_ref": payload_ref_to_dict(self.payload_ref),
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
