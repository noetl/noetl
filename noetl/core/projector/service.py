"""Projector primitives shared by server and future projector workers."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from noetl.core.projection_store import ProjectionRecord, ProjectionStore
from noetl.server.api.replay.service import fold_replay_state


class ReplayStateProjector:
    """Fold event batches into replayable execution-state projections.

    This is intentionally transport-neutral: a NATS/Kafka/Pub/Sub consumer can
    feed the same projector, and tests can call it directly.  The event log and
    immutable payload references remain authoritative; projection rows are
    rebuildable serving state.

    Writes two record families:

    - Per-execution records keyed ``execution/<id>/<projection>`` — the
      original behaviour.
    - Per-frame records keyed ``frame/<frame_id>/<projection>`` — written
      additively whenever the folded state's ``frames`` surface is
      non-empty. Lets dashboards and replay tooling read individual frame
      state without fanning out from the execution record.
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
                    "projection_checksums": state.get("projection_checksums"),
                    "source_event_id": source_event_id,
                    "upcaster_registry_digest": state.get("upcaster_registry_digest"),
                },
            )
            if await self.projection_store.save_projection(record):
                written.append(record)

            frame_records = self._build_frame_records(
                state=state,
                events=ordered,
                tenant_id=tenant_id,
                organization_id=organization_id,
                execution_id=execution_id,
                projected_at=projected_at,
            )
            for frame_record in frame_records:
                if await self.projection_store.save_projection(frame_record):
                    written.append(frame_record)
        return written

    def _build_frame_records(
        self,
        *,
        state: Mapping[str, Any],
        events: list[dict[str, Any]],
        tenant_id: str,
        organization_id: str,
        execution_id: int,
        projected_at: datetime,
    ) -> list[ProjectionRecord]:
        """Materialize per-frame projection records from a folded state.

        Each entry in ``state['frames']`` becomes one
        ``frame/<frame_id>/<projection>`` row. Versions and source event
        ids are computed against the subset of input events touching the
        same frame so the monotonic upsert in the projection store stays
        coherent even when batches arrive out of order.
        """
        frames = state.get("frames") if isinstance(state, Mapping) else None
        if not isinstance(frames, Mapping) or not frames:
            return []

        events_by_frame: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in events:
            frame_id = _extract_frame_id(event)
            if frame_id:
                events_by_frame[frame_id].append(event)

        records: list[ProjectionRecord] = []
        for frame_id, frame_state in frames.items():
            if not isinstance(frame_state, Mapping):
                continue
            frame_events = events_by_frame.get(str(frame_id), [])
            version = _projection_version(frame_events)
            source_event_id = _last_event_id(frame_events)
            event_watermark = _event_time_watermark(frame_events)
            frame_payload = dict(frame_state)
            frame_payload.setdefault("frame_id", str(frame_id))
            record_state = {
                "tenant_id": tenant_id,
                "organization_id": organization_id,
                "execution_id": execution_id,
                "frame_id": str(frame_id),
                "stage_id": frame_payload.get("stage_id"),
                "parent_frame_id": frame_payload.get("parent_frame_id"),
                "projection": self.projection,
                "frame": frame_payload,
                "projection_checksums": state.get("projection_checksums"),
                "upcaster_registry_digest": state.get("upcaster_registry_digest"),
            }
            meta = {
                "event_count": len(frame_events),
                "event_time_watermark": _format_dt(event_watermark),
                "projected_at": _format_dt(projected_at),
                "projection_lag_ms": _projection_lag_ms(event_watermark, projected_at),
                "projector": "replay_state",
                "projection": self.projection,
                "projection_checksums": state.get("projection_checksums"),
                "source_event_id": source_event_id,
                "frame_id": str(frame_id),
                "stage_id": frame_payload.get("stage_id"),
                "command_id": frame_payload.get("command_id"),
                "parent_frame_id": frame_payload.get("parent_frame_id"),
                "frame_status": frame_payload.get("status"),
                "upcaster_registry_digest": state.get("upcaster_registry_digest"),
            }
            records.append(
                ProjectionRecord(
                    projection_id=f"frame/{frame_id}/{self.projection}",
                    projection_type=f"replay_state:frame:{self.projection}",
                    tenant_id=tenant_id,
                    organization_id=organization_id,
                    execution_id=execution_id,
                    version=version,
                    source_event_id=source_event_id,
                    state=record_state,
                    meta=meta,
                )
            )
        return records


def _extract_frame_id(event: Mapping[str, Any]) -> str | None:
    """Return the frame_id an event belongs to, or ``None``.

    Mirrors the resolution order used by
    :func:`noetl.server.api.replay.service._frame_id` so projector and
    replay agree on which events fold into which frame.
    """
    if not isinstance(event, Mapping):
        return None
    column_value = event.get("frame_id")
    if column_value is not None:
        return str(column_value)
    aggregate_type = event.get("aggregate_type")
    aggregate_id = event.get("aggregate_id")
    if aggregate_type == "frame" and aggregate_id:
        return str(aggregate_id).removeprefix("frame/")
    meta = event.get("meta")
    if isinstance(meta, Mapping):
        value = meta.get("frame_id")
        if value is not None:
            return str(value)
    return None


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
