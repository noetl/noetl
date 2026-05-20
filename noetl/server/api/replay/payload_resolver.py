"""Replay payload-resolution ports and reference adapter."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol

from noetl.core.storage import default_store


@dataclass(frozen=True)
class ReplayPayloadResolution:
    """Bounded verification result for a replay payload reference."""

    ref: str
    resolved: bool
    checksum: str | None = None
    size_bytes: int | None = None
    row_count: int | None = None
    value_type: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ReplayPayloadResolver(Protocol):
    """Storage-neutral read port for immutable replay payload references."""

    async def resolve_payload_ref(self, reference: Any) -> ReplayPayloadResolution:
        """Resolve and summarize a payload reference without returning the payload body."""


class TempStoreReplayPayloadResolver:
    """Replay payload resolver backed by TempStore/ResultStore."""

    def __init__(self, store: Any = None) -> None:
        self.store = store or default_store

    async def resolve_payload_ref(self, reference: Any) -> ReplayPayloadResolution:
        ref = _reference_locator(reference)
        if ref is None:
            return ReplayPayloadResolution(
                ref="",
                resolved=False,
                error="payload reference has no resolvable locator",
            )
        try:
            resolved = await self.store.resolve(_resolve_input(reference, ref))
        except Exception as exc:
            return ReplayPayloadResolution(
                ref=ref,
                resolved=False,
                error=str(exc),
            )
        payload_bytes = _canonical_payload_bytes(resolved)
        return ReplayPayloadResolution(
            ref=ref,
            resolved=True,
            checksum=hashlib.sha256(payload_bytes).hexdigest(),
            size_bytes=len(payload_bytes),
            row_count=_row_count(resolved),
            value_type=type(resolved).__name__,
        )


def _resolve_input(reference: Any, ref: str) -> Any:
    if isinstance(reference, Mapping):
        if reference.get("kind") in {"temp_ref", "result_ref", "manifest"}:
            return dict(reference)
        rows_ref = reference.get("rows_ref")
        if isinstance(rows_ref, Mapping):
            return dict(rows_ref)
    return ref


def replay_payload_ref_locator(reference: Any) -> str | None:
    """Return the stable locator for a replay payload reference, when present."""
    if isinstance(reference, str):
        return reference
    if not isinstance(reference, Mapping):
        return None
    for key in ("ref", "uri", "locator"):
        value = reference.get(key)
        if value:
            return str(value)
    rows_ref = reference.get("rows_ref")
    if isinstance(rows_ref, Mapping):
        for key in ("ref", "uri", "locator"):
            value = rows_ref.get(key)
            if value:
                return str(value)
    return None


def _reference_locator(reference: Any) -> str | None:
    return replay_payload_ref_locator(reference)


def _canonical_payload_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")


def _json_default(value: Any) -> str:
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def _row_count(value: Any) -> int | None:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, Mapping):
        rows = value.get("rows")
        if isinstance(rows, list):
            return len(rows)
    return None
