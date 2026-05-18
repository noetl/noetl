"""Projector primitives shared by server and future projector workers."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

from noetl.core.projection_store import ProjectionRecord, ProjectionStore
from noetl.server.api.replay.service import fold_replay_state


class ReplayStateProjector:
    """Fold event batches into replayable execution-state projections.

    This is intentionally transport-neutral: a NATS/Kafka/Pub/Sub consumer can
    feed the same projector, and tests can call it directly.  The event log and
    immutable payload references remain authoritative; projection rows are
    rebuildable serving state.
    """

    def __init__(self, projection_store: ProjectionStore, *, projection: str = "all") -> None:
        self.projection_store = projection_store
        self.projection = projection

    async def project(self, events: Iterable[dict[str, Any]]) -> list[ProjectionRecord]:
        grouped: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
        for event in events:
            execution_id = event.get("execution_id")
            if execution_id is None:
                continue
            tenant_id = str(event.get("tenant_id") or "default")
            organization_id = str(event.get("organization_id") or "default")
            grouped[(tenant_id, organization_id, int(execution_id))].append(event)

        written: list[ProjectionRecord] = []
        for (tenant_id, organization_id, execution_id), group in grouped.items():
            projected_at = datetime.now(timezone.utc)
            ordered = sorted(
                group,
                key=lambda item: (
                    item.get("stream_version") is None,
                    item.get("stream_version") or 0,
                    item.get("event_id") or 0,
                ),
            )
            state = fold_replay_state(
                ordered,
                tenant_id=tenant_id,
                organization_id=organization_id,
                execution_id=execution_id,
                projection=self.projection,
            )
            version = _projection_version(ordered)
            source_event_id = _last_event_id(ordered)
            event_watermark = _event_time_watermark(ordered)
            record = ProjectionRecord(
                projection_id=f"execution/{execution_id}/{self.projection}",
                projection_type=f"replay_state:{self.projection}",
                tenant_id=tenant_id,
                organization_id=organization_id,
                execution_id=execution_id,
                version=version,
                source_event_id=source_event_id,
                state=state,
                checksum=state.get("checksum"),
                meta={
                    "event_count": len(ordered),
                    "event_time_watermark": _format_dt(event_watermark),
                    "projected_at": _format_dt(projected_at),
                    "projection_lag_ms": _projection_lag_ms(event_watermark, projected_at),
                    "projector": "replay_state",
                    "projection": self.projection,
                    "source_event_id": source_event_id,
                    "upcaster_registry_digest": state.get("upcaster_registry_digest"),
                },
            )
            if await self.projection_store.save_projection(record):
                written.append(record)
        return written


def _projection_version(events: list[dict[str, Any]]) -> int:
    if not events:
        return 0
    last = events[-1]
    return int(last.get("stream_version") or last.get("event_id") or len(events))


def _last_event_id(events: list[dict[str, Any]]) -> int | None:
    for event in reversed(events):
        event_id = event.get("event_id")
        if event_id is not None:
            return int(event_id)
    return None


def _event_time_watermark(events: list[dict[str, Any]]) -> datetime | None:
    watermarks = [
        parsed
        for event in events
        for parsed in [_parse_event_time(event)]
        if parsed is not None
    ]
    return max(watermarks) if watermarks else None


def _parse_event_time(event: dict[str, Any]) -> datetime | None:
    for key in ("event_time", "ingest_time", "created_at"):
        value = event.get(key)
        if value is None:
            continue
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, str):
            raw = value.strip()
            if not raw:
                continue
            if raw.endswith("Z"):
                raw = f"{raw[:-1]}+00:00"
            try:
                dt = datetime.fromisoformat(raw)
            except ValueError:
                continue
        else:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return None


def _projection_lag_ms(event_watermark: datetime | None, projected_at: datetime) -> int | None:
    if event_watermark is None:
        return None
    lag = projected_at - event_watermark
    return max(0, int(lag.total_seconds() * 1000))


def _format_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
