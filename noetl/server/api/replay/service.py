"""Replay service for event-sourced runtime projections.

Phase 0 intentionally folds only lightweight state from canonical event
metadata. Payload refs are surfaced as lineage; durable payload resolution lands
in a later phase.
"""

from __future__ import annotations

import hashlib
import json
import copy
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional

from noetl.core.replay import EventUpcasterRegistry, default_upcaster_registry

from .event_reader import PostgresReplayEventReader, ReplayEventReader
from .payload_resolver import (
    ReplayPayloadResolver,
    TempStoreReplayPayloadResolver,
    replay_payload_ref_locator,
)
from .types import ReplayCutoff, ReplaySnapshotSeed

PROJECTION_CHECKSUM_SURFACES = (
    "execution",
    "stages",
    "frames",
    "commands",
    "business_objects",
    "loops",
)

DEFAULT_REPLAY_PAYLOAD_RESOLVER = TempStoreReplayPayloadResolver()


def replay_snapshot_upcaster_registry_digest(snapshot_seed: ReplaySnapshotSeed | None) -> Optional[str]:
    """Return the upcaster registry digest recorded by a replay snapshot seed."""
    if snapshot_seed is None:
        return None
    state_digest = snapshot_seed.state.get("upcaster_registry_digest")
    if state_digest is not None:
        return str(state_digest)
    meta_digest = snapshot_seed.meta.get("upcaster_registry_digest")
    if meta_digest is not None:
        return str(meta_digest)
    return None


def replay_snapshot_is_compatible(
    snapshot_seed: ReplaySnapshotSeed | None,
    *,
    upcaster_registry_digest: str,
) -> bool:
    """Snapshots are accelerators; ignore seeds produced by a different registry."""
    if snapshot_seed is None:
        return False
    snapshot_digest = replay_snapshot_upcaster_registry_digest(snapshot_seed)
    return snapshot_digest == upcaster_registry_digest


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def _canonical_checksum(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _meta(event: Mapping[str, Any]) -> dict[str, Any]:
    meta = event.get("meta")
    return meta if isinstance(meta, dict) else {}


def _payload_ref(event: Mapping[str, Any]) -> Any:
    if event.get("payload_ref") is not None:
        return event.get("payload_ref")
    result = event.get("result")
    if isinstance(result, dict):
        return result.get("reference")
    return None


def _payload_summary(reference: Any) -> dict[str, Any]:
    if not isinstance(reference, Mapping):
        return {
            "sha256": None,
            "schema_digest": None,
            "row_count": None,
            "media_type": None,
            "ref": None,
        }
    rows_ref = reference.get("rows_ref")
    rows_ref = rows_ref if isinstance(rows_ref, Mapping) else {}
    rows_meta = rows_ref.get("meta")
    rows_meta = rows_meta if isinstance(rows_meta, Mapping) else {}
    rows_ipc = rows_ref.get("ipc")
    rows_ipc = rows_ipc if isinstance(rows_ipc, Mapping) else {}
    return {
        "sha256": (
            reference.get("sha256")
            or rows_meta.get("sha256")
            or rows_ipc.get("sha256")
            or reference.get("digest")
        ),
        "schema_digest": (
            reference.get("schema_digest")
            or rows_meta.get("schema_digest")
            or rows_ipc.get("schema_digest")
        ),
        "row_count": (
            reference.get("row_count")
            or rows_meta.get("row_count")
            or rows_ipc.get("row_count")
        ),
        "media_type": (
            reference.get("media_type")
            or rows_meta.get("media_type")
            or rows_ipc.get("media_type")
        ),
        "ref": reference.get("ref") or rows_ref.get("ref") or reference.get("uri"),
    }


def _event_id(event: Mapping[str, Any]) -> Optional[int]:
    value = event.get("event_id")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _frame_id(event: Mapping[str, Any]) -> Optional[str]:
    column_value = event.get("frame_id")
    if column_value is not None:
        return str(column_value)
    aggregate_type = event.get("aggregate_type")
    aggregate_id = event.get("aggregate_id")
    if aggregate_type == "frame" and aggregate_id:
        return str(aggregate_id).removeprefix("frame/")
    meta = _meta(event)
    value = meta.get("frame_id")
    return str(value) if value is not None else None


def _stage_id(event: Mapping[str, Any]) -> Optional[str]:
    column_value = event.get("stage_id")
    if column_value is not None:
        return str(column_value)
    aggregate_type = event.get("aggregate_type")
    aggregate_id = event.get("aggregate_id")
    if aggregate_type == "stage" and aggregate_id:
        return str(aggregate_id).removeprefix("stage/")
    meta = _meta(event)
    value = meta.get("stage_id")
    return str(value) if value is not None else None


def _loop_id(event: Mapping[str, Any]) -> Optional[str]:
    meta = _meta(event)
    for key in ("loop_id", "loop_event_id", "__loop_epoch_id"):
        value = meta.get(key)
        if value is not None:
            return str(value)
    return None


def _command_id(event: Mapping[str, Any]) -> Optional[str]:
    value = event.get("command_id")
    if value is not None:
        return str(value)
    meta = _meta(event)
    value = meta.get("command_id")
    return str(value) if value is not None else None


def _business_object_identity(event: Mapping[str, Any]) -> tuple[str, str, str] | None:
    """Return (object_key, object_type, object_id) for explicitly identified domain objects."""
    meta = _meta(event)
    business = meta.get("business_object")
    business = business if isinstance(business, Mapping) else {}

    object_type = (
        business.get("object_type")
        or business.get("type")
        or meta.get("business_object_type")
        or meta.get("object_type")
    )
    object_id = (
        business.get("object_id")
        or business.get("id")
        or meta.get("business_object_id")
        or meta.get("object_id")
    )

    aggregate_type = str(event.get("aggregate_type") or "")
    aggregate_id = event.get("aggregate_id")
    if aggregate_type == "business_object" and aggregate_id is not None:
        parts = [part for part in str(aggregate_id).split("/") if part]
        if parts[:1] == ["business_object"]:
            parts = parts[1:]
        if len(parts) >= 2:
            object_type = object_type or parts[0]
            object_id = object_id or "/".join(parts[1:])
        else:
            object_type = object_type or "business_object"
            object_id = object_id or str(aggregate_id)

    if object_type is None or object_id is None:
        return None
    object_type = str(object_type)
    object_id = str(object_id)
    return f"{object_type}/{object_id}", object_type, object_id


def _business_object_status(event_type: str, status: Any) -> str | None:
    if status is not None:
        return str(status)
    lowered = event_type.lower()
    if lowered.endswith(".deleted") or lowered.endswith(".removed"):
        return "DELETED"
    if lowered.endswith(".created") or lowered.endswith(".updated") or lowered.endswith(".upserted"):
        return "ACTIVE"
    return None


def fold_replay_state(
    events: Iterable[Mapping[str, Any]],
    *,
    tenant_id: str,
    organization_id: str,
    execution_id: int,
    projection: str = "all",
    upcaster_registry_digest: Optional[str] = None,
    base_state: Optional[Mapping[str, Any]] = None,
    snapshot_seed: Optional[ReplaySnapshotSeed] = None,
) -> dict[str, Any]:
    """Fold canonical events into a deterministic lightweight state snapshot."""

    ordered_events = sorted(events, key=lambda event: (_event_id(event) or 0))
    if base_state:
        state = copy.deepcopy(dict(base_state))
        state.pop("checksum", None)
        state.pop("checksum_algorithm", None)
        state.pop("projection_checksums", None)
        state["tenant_id"] = tenant_id
        state["organization_id"] = organization_id
        state["execution_id"] = execution_id
        state["projection"] = projection
        state["upcaster_registry_digest"] = upcaster_registry_digest
        state.setdefault("event_count", 0)
        state.setdefault("last_event_id", None)
        state.setdefault("last_event_type", None)
        state.setdefault("execution", {"status": "UNKNOWN", "last_node_name": None, "payload_refs": []})
        state.setdefault("stages", {})
        state.setdefault("frames", {})
        state.setdefault("commands", {})
        state.setdefault("business_objects", {})
        state.setdefault("loops", {})
    else:
        state = {
            "tenant_id": tenant_id,
            "organization_id": organization_id,
            "execution_id": execution_id,
            "projection": projection,
            "upcaster_registry_digest": upcaster_registry_digest,
            "event_count": 0,
            "last_event_id": None,
            "last_event_type": None,
            "execution": {
                "status": "UNKNOWN",
                "last_node_name": None,
                "payload_refs": [],
            },
            "stages": {},
            "frames": {},
            "commands": {},
            "business_objects": {},
            "loops": {},
        }
    if snapshot_seed is not None:
        state["replay_snapshot"] = {
            "aggregate_id": snapshot_seed.aggregate_id,
            "aggregate_type": snapshot_seed.aggregate_type,
            "version": snapshot_seed.version,
            "checksum": snapshot_seed.checksum,
            "meta": snapshot_seed.meta,
        }

    for event in ordered_events:
        event_id = _event_id(event)
        event_type = str(event.get("event_type") or "")
        status = event.get("status")
        meta = _meta(event)

        state["event_count"] += 1
        state["last_event_id"] = event_id
        state["last_event_type"] = event_type
        state["execution"]["last_node_name"] = event.get("node_name")
        if event_type in {"playbook.completed", "workflow.completed", "execution.completed"}:
            state["execution"]["status"] = "COMPLETED"
        elif event_type in {"playbook.failed", "workflow.failed", "execution.failed", "command.failed"}:
            state["execution"]["status"] = "FAILED"
        elif event_type in {"playbook.initialized", "execution.started", "stage.opened", "frame.dispatched"}:
            state["execution"]["status"] = "RUNNING"

        payload_ref = _payload_ref(event)
        if payload_ref is not None:
            state["execution"]["payload_refs"].append(
                {"event_id": event_id, "reference": payload_ref}
            )

        stage_id = _stage_id(event)
        if stage_id:
            stage = state["stages"].setdefault(
                stage_id,
                {
                    "stage_id": stage_id,
                    "status": "UNKNOWN",
                    "kind": meta.get("kind"),
                    "step_name": event.get("node_name") or meta.get("step_name"),
                    "parent_stage_id": meta.get("parent_stage_id"),
                    "loop_event_id": None,
                    "opened_event_id": None,
                    "closed_event_id": None,
                    "frame_count": 0,
                    "row_count": 0,
                    "events_emitted": 0,
                    "failed_count": 0,
                    "last_event_id": None,
                },
            )
            stage["last_event_id"] = event_id
            if meta.get("parent_stage_id") is not None:
                stage["parent_stage_id"] = str(meta.get("parent_stage_id"))
            loop_event_id = _loop_id(event)
            if loop_event_id:
                stage["loop_event_id"] = loop_event_id
            if event_type == "stage.opened":
                stage["status"] = "OPEN"
                stage["opened_event_id"] = event_id
            elif event_type == "stage.closed":
                stage["status"] = status or "CLOSED"
                stage["closed_event_id"] = event_id
                stage["frame_count"] = int(meta.get("frame_count") or stage.get("frame_count") or 0)
                stage["row_count"] = int(meta.get("row_count") or stage.get("row_count") or 0)
                stage["events_emitted"] = int(meta.get("events_emitted") or stage.get("events_emitted") or 0)
                stage["failed_count"] = int(meta.get("failed_count") or stage.get("failed_count") or 0)
            elif status:
                stage["status"] = str(status)

        frame_id = _frame_id(event)
        if frame_id:
            frame_stage_id = _stage_id(event)
            frame = state["frames"].setdefault(
                frame_id,
                {
                    "frame_id": frame_id,
                    "stage_id": frame_stage_id,
                    "parent_frame_id": meta.get("parent_frame_id"),
                    "command_id": None,
                    "claimed_event_id": None,
                    "terminal_event_id": None,
                    "status": "UNKNOWN",
                    "row_count": 0,
                    "attempts": 0,
                    "last_event_id": None,
                    "output_ref": None,
                    "output_ref_summary": _payload_summary(None),
                    "cursor": {},
                    "events_emitted": 0,
                },
            )
            frame["last_event_id"] = event_id
            if frame_stage_id is not None:
                frame["stage_id"] = str(frame_stage_id)
            if meta.get("parent_frame_id") is not None:
                frame["parent_frame_id"] = str(meta.get("parent_frame_id"))
            command_id = _command_id(event)
            if command_id:
                frame["command_id"] = command_id
            if event_type == "frame.dispatched":
                frame["status"] = "CLAIMED"
                frame["claimed_event_id"] = event_id
                frame["attempts"] = max(int(frame.get("attempts") or 0), int(meta.get("attempt", 1)))
            elif event_type == "frame.started":
                frame["status"] = "RUNNING"
            elif event_type == "frame.abandoned":
                frame["status"] = status or "ABANDONED"
            elif event_type == "frame.committed":
                frame["status"] = status or "COMPLETED"
                frame["row_count"] = int(meta.get("row_count") or frame.get("row_count") or 0)
                frame["output_ref"] = payload_ref
                frame["output_ref_summary"] = _payload_summary(payload_ref)
                frame["cursor"] = meta.get("cursor") or frame.get("cursor") or {}
                frame["events_emitted"] = int(meta.get("events_emitted") or frame.get("events_emitted") or 0)
                frame["terminal_event_id"] = event_id
            elif event_type == "frame.failed":
                frame["status"] = status or "FAILED"
                frame["output_ref"] = payload_ref
                frame["output_ref_summary"] = _payload_summary(payload_ref)
                frame["cursor"] = meta.get("cursor") or frame.get("cursor") or {}
                frame["events_emitted"] = int(meta.get("events_emitted") or frame.get("events_emitted") or 0)
                frame["terminal_event_id"] = event_id
            elif status:
                frame["status"] = str(status)

        command_id = _command_id(event)
        if command_id:
            command = state["commands"].setdefault(
                command_id,
                {
                    "command_id": command_id,
                    "stage_id": str(_stage_id(event)) if _stage_id(event) is not None else None,
                    "frame_id": _frame_id(event),
                    "parent_command_id": None,
                    "worker_id": None,
                    "worker_locator": None,
                    "locality": {},
                    "source_locality": {},
                    "placement": {},
                    "status": "UNKNOWN",
                    "issued_event_id": None,
                    "claimed_event_id": None,
                    "started_event_id": None,
                    "terminal_event_id": None,
                    "last_event_id": None,
                },
            )
            command["last_event_id"] = event_id
            command_stage_id = _stage_id(event)
            if command_stage_id is not None:
                command["stage_id"] = str(command_stage_id)
            command_frame_id = _frame_id(event)
            if command_frame_id:
                command["frame_id"] = command_frame_id
            if meta.get("parent_command_id") is not None:
                command["parent_command_id"] = str(meta.get("parent_command_id"))
            worker_id = event.get("worker_id") or meta.get("worker_id")
            if worker_id is not None:
                command["worker_id"] = str(worker_id)
            if meta.get("worker_locator") is not None:
                command["worker_locator"] = str(meta.get("worker_locator"))
            if isinstance(meta.get("locality"), Mapping):
                command["locality"] = dict(meta["locality"])
            if isinstance(meta.get("source_locality"), Mapping):
                command["source_locality"] = dict(meta["source_locality"])
            if isinstance(meta.get("placement"), Mapping):
                command["placement"] = dict(meta["placement"])

            if event_type == "command.issued":
                command["status"] = status or "PENDING"
                command["issued_event_id"] = event_id
            elif event_type == "command.claimed":
                command["status"] = status or "CLAIMED"
                command["claimed_event_id"] = event_id
            elif event_type == "command.started":
                command["status"] = status or "RUNNING"
                command["started_event_id"] = event_id
            elif event_type in {"command.completed", "command.failed", "command.cancelled"}:
                command["status"] = status or event_type.removeprefix("command.").upper()
                command["terminal_event_id"] = event_id
            elif event_type.startswith("command.") and status:
                command["status"] = str(status)

        business_identity = _business_object_identity(event)
        if business_identity:
            object_key, object_type, object_id = business_identity
            business_meta = meta.get("business_object")
            business_meta = business_meta if isinstance(business_meta, Mapping) else {}
            business_object = state["business_objects"].setdefault(
                object_key,
                {
                    "object_key": object_key,
                    "object_type": object_type,
                    "object_id": object_id,
                    "status": "UNKNOWN",
                    "version": 0,
                    "event_count": 0,
                    "first_event_id": event_id,
                    "last_event_id": None,
                    "deleted_event_id": None,
                    "last_event_type": None,
                    "last_payload_ref": None,
                    "payload_refs": [],
                    "attributes": {},
                },
            )
            business_object["last_event_id"] = event_id
            business_object["last_event_type"] = event_type
            business_object["event_count"] = int(business_object.get("event_count") or 0) + 1
            business_object["version"] = int(
                business_meta.get("version")
                or meta.get("business_object_version")
                or business_object["event_count"]
            )

            object_status = _business_object_status(event_type, status)
            if object_status:
                business_object["status"] = object_status
                if object_status == "DELETED":
                    business_object["deleted_event_id"] = event_id

            state_value = business_meta.get("state")
            if isinstance(state_value, Mapping):
                business_object["attributes"] = dict(state_value)
            patch_value = business_meta.get("patch") or business_meta.get("attributes")
            if isinstance(patch_value, Mapping):
                business_object["attributes"].update(dict(patch_value))

            if payload_ref is not None:
                payload_entry = {
                    "event_id": event_id,
                    "reference": payload_ref,
                    "summary": _payload_summary(payload_ref),
                }
                business_object["payload_refs"].append(payload_entry)
                business_object["last_payload_ref"] = payload_entry

        loop_id = _loop_id(event)
        if loop_id:
            loop = state["loops"].setdefault(
                loop_id,
                {
                    "loop_id": loop_id,
                    "step_name": event.get("node_name"),
                    "total": meta.get("collection_size") or meta.get("total"),
                    "done": 0,
                    "failed": 0,
                    "completed": False,
                    "last_event_id": None,
                },
            )
            loop["last_event_id"] = event_id
            if event_type in {"command.completed", "loop.shard.done"}:
                loop["done"] = int(loop.get("done") or 0) + 1
            elif event_type in {"command.failed", "loop.shard.failed"}:
                loop["failed"] = int(loop.get("failed") or 0) + 1
            elif event_type in {"loop.done", "loop.fanin.completed"}:
                loop["completed"] = True

    checksum_input = {
        key: value
        for key, value in state.items()
        if key not in {"checksum", "checksum_algorithm"}
    }
    state["checksum_algorithm"] = "sha256"
    state["checksum"] = _canonical_checksum(checksum_input)
    state["projection_checksums"] = replay_projection_checksum_bundle(state)
    return state


def _normalized_frame_projection_row(row: Mapping[str, Any]) -> dict[str, Any]:
    output_ref = row.get("output_ref")
    return {
        "frame_id": str(row.get("frame_id")),
        "stage_id": str(row.get("stage_id")) if row.get("stage_id") is not None else None,
        "parent_frame_id": (
            str(row.get("parent_frame_id")) if row.get("parent_frame_id") is not None else None
        ),
        "command_id": str(row.get("command_id")) if row.get("command_id") is not None else None,
        "claimed_event_id": (
            int(row.get("claimed_event_id")) if row.get("claimed_event_id") is not None else None
        ),
        "terminal_event_id": (
            int(row.get("terminal_event_id")) if row.get("terminal_event_id") is not None else None
        ),
        "status": row.get("status"),
        "row_count": int(row.get("row_count") or 0),
        "cursor": row.get("cursor") or {},
        "events_emitted": int(row.get("events_emitted") or 0),
        "output_ref_summary": _payload_summary(output_ref),
    }


def normalize_live_frame_projection(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (_normalized_frame_projection_row(row) for row in rows),
        key=lambda row: int(row["frame_id"]),
    )


def normalize_replayed_frame_projection(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    frames = state.get("frames")
    if not isinstance(frames, Mapping):
        return []
    return sorted(
        (
            {
                "frame_id": str(frame.get("frame_id") or frame_id),
                "stage_id": str(frame.get("stage_id")) if frame.get("stage_id") is not None else None,
                "parent_frame_id": (
                    str(frame.get("parent_frame_id")) if frame.get("parent_frame_id") is not None else None
                ),
                "command_id": str(frame.get("command_id")) if frame.get("command_id") is not None else None,
                "claimed_event_id": (
                    int(frame.get("claimed_event_id")) if frame.get("claimed_event_id") is not None else None
                ),
                "terminal_event_id": (
                    int(frame.get("terminal_event_id")) if frame.get("terminal_event_id") is not None else None
                ),
                "status": frame.get("status"),
                "row_count": int(frame.get("row_count") or 0),
                "cursor": frame.get("cursor") or {},
                "events_emitted": int(frame.get("events_emitted") or 0),
                "output_ref_summary": frame.get("output_ref_summary") or _payload_summary(frame.get("output_ref")),
            }
            for frame_id, frame in frames.items()
            if isinstance(frame, Mapping)
        ),
        key=lambda row: int(row["frame_id"]),
    )


def frame_projection_checksum(rows: Iterable[Mapping[str, Any]]) -> str:
    return _canonical_checksum({"frames": list(rows)})


def _normalized_stage_projection_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "stage_id": str(row.get("stage_id")),
        "status": row.get("status"),
        "kind": row.get("kind"),
        "step_name": row.get("step_name"),
        "parent_stage_id": (
            str(row.get("parent_stage_id")) if row.get("parent_stage_id") is not None else None
        ),
        "loop_event_id": (
            str(row.get("loop_event_id")) if row.get("loop_event_id") is not None else None
        ),
        "opened_event_id": (
            int(row.get("opened_event_id")) if row.get("opened_event_id") is not None else None
        ),
        "closed_event_id": (
            int(row.get("closed_event_id")) if row.get("closed_event_id") is not None else None
        ),
        "frame_count": int(row.get("frame_count") or 0),
        "row_count": int(row.get("row_count") or 0),
        "events_emitted": int(row.get("events_emitted") or 0),
        "failed_count": int(row.get("failed_count") or 0),
        "last_event_id": (
            int(row.get("last_event_id")) if row.get("last_event_id") is not None else None
        ),
    }


def normalize_live_stage_projection(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (_normalized_stage_projection_row(row) for row in rows),
        key=lambda row: int(row["stage_id"]),
    )


def normalize_replayed_stage_projection(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    stages = state.get("stages")
    if not isinstance(stages, Mapping):
        return []
    return sorted(
        (
            _normalized_stage_projection_row(
                {
                    "stage_id": stage.get("stage_id") or stage_id,
                    **stage,
                }
            )
            for stage_id, stage in stages.items()
            if isinstance(stage, Mapping)
        ),
        key=lambda row: int(row["stage_id"]),
    )


def stage_projection_checksum(rows: Iterable[Mapping[str, Any]]) -> str:
    return _canonical_checksum({"stages": list(rows)})


def _normalized_command_projection_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "command_id": str(row.get("command_id")),
        "stage_id": str(row.get("stage_id")) if row.get("stage_id") is not None else None,
        "frame_id": str(row.get("frame_id")) if row.get("frame_id") is not None else None,
        "parent_command_id": (
            str(row.get("parent_command_id")) if row.get("parent_command_id") is not None else None
        ),
        "worker_id": str(row.get("worker_id")) if row.get("worker_id") is not None else None,
        "worker_locator": (
            str(row.get("worker_locator")) if row.get("worker_locator") is not None else None
        ),
        "locality": row.get("locality") or {},
        "source_locality": row.get("source_locality") or {},
        "placement": row.get("placement") or {},
        "status": row.get("status"),
        "issued_event_id": (
            int(row.get("issued_event_id")) if row.get("issued_event_id") is not None else None
        ),
        "claimed_event_id": (
            int(row.get("claimed_event_id")) if row.get("claimed_event_id") is not None else None
        ),
        "started_event_id": (
            int(row.get("started_event_id")) if row.get("started_event_id") is not None else None
        ),
        "terminal_event_id": (
            int(row.get("terminal_event_id")) if row.get("terminal_event_id") is not None else None
        ),
    }


def normalize_live_command_projection(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (_normalized_command_projection_row(row) for row in rows),
        key=lambda row: int(row["command_id"]),
    )


def normalize_replayed_command_projection(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    commands = state.get("commands")
    if not isinstance(commands, Mapping):
        return []
    return sorted(
        (
            _normalized_command_projection_row(
                {
                    "command_id": command.get("command_id") or command_id,
                    **command,
                }
            )
            for command_id, command in commands.items()
            if isinstance(command, Mapping)
        ),
        key=lambda row: int(row["command_id"]),
    )


def command_projection_checksum(rows: Iterable[Mapping[str, Any]]) -> str:
    return _canonical_checksum({"commands": list(rows)})


def _normalized_business_object_projection_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "object_key": str(row.get("object_key")),
        "object_type": str(row.get("object_type")),
        "object_id": str(row.get("object_id")),
        "status": row.get("status"),
        "version": int(row.get("version") or 0),
        "event_count": int(row.get("event_count") or 0),
        "first_event_id": (
            int(row.get("first_event_id")) if row.get("first_event_id") is not None else None
        ),
        "last_event_id": (
            int(row.get("last_event_id")) if row.get("last_event_id") is not None else None
        ),
        "deleted_event_id": (
            int(row.get("deleted_event_id")) if row.get("deleted_event_id") is not None else None
        ),
        "last_event_type": row.get("last_event_type"),
        "last_payload_ref_summary": _payload_summary(
            (row.get("last_payload_ref") or {}).get("reference")
            if isinstance(row.get("last_payload_ref"), Mapping)
            else row.get("last_payload_ref")
        ),
        "payload_ref_count": len(row.get("payload_refs") or []),
        "attributes": row.get("attributes") or {},
    }


def normalize_live_business_object_projection(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (_normalized_business_object_projection_row(row) for row in rows),
        key=lambda row: row["object_key"],
    )


def normalize_replayed_business_object_projection(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    business_objects = state.get("business_objects")
    if not isinstance(business_objects, Mapping):
        return []
    return sorted(
        (
            _normalized_business_object_projection_row(
                {
                    "object_key": business_object.get("object_key") or object_key,
                    **business_object,
                }
            )
            for object_key, business_object in business_objects.items()
            if isinstance(business_object, Mapping)
        ),
        key=lambda row: row["object_key"],
    )


def business_object_projection_checksum(rows: Iterable[Mapping[str, Any]]) -> str:
    return _canonical_checksum({"business_objects": list(rows)})


def _normalized_loop_projection_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "loop_id": str(row.get("loop_id")),
        "step_name": row.get("step_name"),
        "total": int(row.get("total")) if row.get("total") is not None else None,
        "done": int(row.get("done") or 0),
        "failed": int(row.get("failed") or 0),
        "completed": bool(row.get("completed")),
        "last_event_id": (
            int(row.get("last_event_id")) if row.get("last_event_id") is not None else None
        ),
    }


def normalize_live_loop_projection(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (_normalized_loop_projection_row(row) for row in rows),
        key=lambda row: row["loop_id"],
    )


def normalize_replayed_loop_projection(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    loops = state.get("loops")
    if not isinstance(loops, Mapping):
        return []
    return sorted(
        (
            _normalized_loop_projection_row(
                {
                    "loop_id": loop.get("loop_id") or loop_id,
                    **loop,
                }
            )
            for loop_id, loop in loops.items()
            if isinstance(loop, Mapping)
        ),
        key=lambda row: row["loop_id"],
    )


def loop_projection_checksum(rows: Iterable[Mapping[str, Any]]) -> str:
    return _canonical_checksum({"loops": list(rows)})


def _normalized_execution_projection_row(row: Mapping[str, Any]) -> dict[str, Any]:
    payload_refs = row.get("payload_refs")
    if payload_refs is None:
        execution = row.get("execution")
        if isinstance(execution, Mapping):
            payload_refs = execution.get("payload_refs")
    payload_refs = payload_refs if isinstance(payload_refs, list) else []
    last_payload_ref = row.get("last_payload_ref")
    if last_payload_ref is None and payload_refs:
        last_payload_ref = payload_refs[-1]
    last_reference = (
        (last_payload_ref or {}).get("reference")
        if isinstance(last_payload_ref, Mapping)
        else last_payload_ref
    )
    execution = row.get("execution")
    execution = execution if isinstance(execution, Mapping) else {}
    return {
        "execution_id": int(row.get("execution_id")),
        "tenant_id": str(row.get("tenant_id") or "default"),
        "organization_id": str(row.get("organization_id") or "default"),
        "projection": str(row.get("projection") or "all"),
        "status": row.get("status") or execution.get("status"),
        "last_node_name": row.get("last_node_name") or execution.get("last_node_name"),
        "event_count": int(row.get("event_count") or 0),
        "last_event_id": (
            int(row.get("last_event_id")) if row.get("last_event_id") is not None else None
        ),
        "last_event_type": row.get("last_event_type"),
        "payload_ref_count": len(payload_refs),
        "last_payload_ref_summary": _payload_summary(last_reference),
        "upcaster_registry_digest": row.get("upcaster_registry_digest"),
    }


def normalize_live_execution_projection(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (_normalized_execution_projection_row(row) for row in rows),
        key=lambda row: row["execution_id"],
    )


def normalize_replayed_execution_projection(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [_normalized_execution_projection_row(state)]


def execution_projection_checksum(rows: Iterable[Mapping[str, Any]]) -> str:
    return _canonical_checksum({"executions": list(rows)})


def replay_projection_checksum_bundle(state: Mapping[str, Any]) -> dict[str, str]:
    """Return deterministic checksums for every replay parity surface."""
    return {
        "execution": execution_projection_checksum(
            normalize_replayed_execution_projection(state)
        ),
        "stages": stage_projection_checksum(
            normalize_replayed_stage_projection(state)
        ),
        "frames": frame_projection_checksum(
            normalize_replayed_frame_projection(state)
        ),
        "commands": command_projection_checksum(
            normalize_replayed_command_projection(state)
        ),
        "business_objects": business_object_projection_checksum(
            normalize_replayed_business_object_projection(state)
        ),
        "loops": loop_projection_checksum(
            normalize_replayed_loop_projection(state)
        ),
    }


def live_projection_checksum_bundle(
    *,
    execution_rows: Iterable[Mapping[str, Any]] | None = None,
    stage_rows: Iterable[Mapping[str, Any]] | None = None,
    frame_rows: Iterable[Mapping[str, Any]] | None = None,
    command_rows: Iterable[Mapping[str, Any]] | None = None,
    business_object_rows: Iterable[Mapping[str, Any]] | None = None,
    loop_rows: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, str]:
    """Return deterministic checksums for live projection rows from any storage adapter."""
    return {
        "execution": execution_projection_checksum(
            normalize_live_execution_projection(execution_rows or [])
        ),
        "stages": stage_projection_checksum(
            normalize_live_stage_projection(stage_rows or [])
        ),
        "frames": frame_projection_checksum(
            normalize_live_frame_projection(frame_rows or [])
        ),
        "commands": command_projection_checksum(
            normalize_live_command_projection(command_rows or [])
        ),
        "business_objects": business_object_projection_checksum(
            normalize_live_business_object_projection(business_object_rows or [])
        ),
        "loops": loop_projection_checksum(
            normalize_live_loop_projection(loop_rows or [])
        ),
    }


def projection_checksum_parity_report(
    *,
    replayed: Mapping[str, str],
    live: Mapping[str, str],
) -> dict[str, Any]:
    """Compare replayed and live projection checksum bundles without storage assumptions."""
    surfaces: dict[str, dict[str, Any]] = {}
    for surface in PROJECTION_CHECKSUM_SURFACES:
        replayed_checksum = replayed.get(surface)
        live_checksum = live.get(surface)
        surfaces[surface] = {
            "replayed": replayed_checksum,
            "live": live_checksum,
            "matched": (
                replayed_checksum is not None
                and live_checksum is not None
                and replayed_checksum == live_checksum
            ),
        }
    return {
        "matched": all(surface["matched"] for surface in surfaces.values()),
        "surfaces": surfaces,
    }


def replay_payload_references(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return payload references carried by the replay state with lineage labels."""
    references: list[dict[str, Any]] = []
    execution = state.get("execution")
    if isinstance(execution, Mapping):
        for payload_ref in execution.get("payload_refs") or []:
            if isinstance(payload_ref, Mapping) and payload_ref.get("reference") is not None:
                references.append(
                    {
                        "scope": "execution",
                        "event_id": payload_ref.get("event_id"),
                        "reference": payload_ref["reference"],
                    }
                )
    frames = state.get("frames")
    if isinstance(frames, Mapping):
        for frame_id, frame in frames.items():
            if isinstance(frame, Mapping) and frame.get("output_ref") is not None:
                references.append(
                    {
                        "scope": "frame",
                        "frame_id": str(frame.get("frame_id") or frame_id),
                        "event_id": frame.get("terminal_event_id"),
                        "reference": frame["output_ref"],
                    }
                )
    business_objects = state.get("business_objects")
    if isinstance(business_objects, Mapping):
        for object_key, business_object in business_objects.items():
            if not isinstance(business_object, Mapping):
                continue
            for payload_ref in business_object.get("payload_refs") or []:
                if isinstance(payload_ref, Mapping) and payload_ref.get("reference") is not None:
                    references.append(
                        {
                            "scope": "business_object",
                            "object_key": str(business_object.get("object_key") or object_key),
                            "event_id": payload_ref.get("event_id"),
                            "reference": payload_ref["reference"],
                        }
                    )
    return references


async def resolve_replay_payload_references(
    state: Mapping[str, Any],
    *,
    payload_resolver: ReplayPayloadResolver,
) -> list[dict[str, Any]]:
    """Resolve replay payload refs through a storage adapter and return bounded summaries."""
    resolved: list[dict[str, Any]] = []
    resolution_cache: dict[str, dict[str, Any]] = {}
    for payload_ref in replay_payload_references(state):
        locator = replay_payload_ref_locator(payload_ref["reference"]) or json.dumps(
            payload_ref["reference"],
            sort_keys=True,
            default=_json_default,
        )
        if locator not in resolution_cache:
            resolution = await payload_resolver.resolve_payload_ref(payload_ref["reference"])
            resolution_cache[locator] = resolution.as_dict()
        resolved.append(
            {
                **{key: value for key, value in payload_ref.items() if key != "reference"},
                "reference_summary": _payload_summary(payload_ref["reference"]),
                "resolution": resolution_cache[locator],
            }
        )
    return resolved


def replay_payload_resolution_summary(resolutions: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Return deterministic aggregate status for resolved replay payload references."""
    resolution_rows = list(resolutions)
    resolved_count = sum(
        1
        for row in resolution_rows
        if isinstance(row.get("resolution"), Mapping)
        and row["resolution"].get("resolved") is True
    )
    unresolved_count = len(resolution_rows) - resolved_count
    unique_refs = sorted(
        {
            str(row["resolution"]["ref"])
            for row in resolution_rows
            if isinstance(row.get("resolution"), Mapping)
            and row["resolution"].get("ref")
        }
    )
    summary = {
        "total": len(resolution_rows),
        "resolved": resolved_count,
        "unresolved": unresolved_count,
        "unique_refs": len(unique_refs),
        "all_resolved": unresolved_count == 0,
    }
    return {
        **summary,
        "checksum": _canonical_checksum(
            {
                **summary,
                "unique_refs": unique_refs,
                "rows": resolution_rows,
            }
        ),
    }


class ReplayService:
    """Read canonical events and fold replay state."""

    event_reader: ReplayEventReader = PostgresReplayEventReader()
    payload_resolver: ReplayPayloadResolver = DEFAULT_REPLAY_PAYLOAD_RESOLVER
    upcaster_registry: EventUpcasterRegistry = default_upcaster_registry

    @classmethod
    def configure_event_reader(cls, event_reader: ReplayEventReader) -> None:
        cls.event_reader = event_reader

    @classmethod
    def configure_payload_resolver(cls, payload_resolver: ReplayPayloadResolver) -> None:
        cls.payload_resolver = payload_resolver

    @classmethod
    def configure_upcaster_registry(cls, upcaster_registry: EventUpcasterRegistry) -> None:
        cls.upcaster_registry = upcaster_registry

    @classmethod
    async def load_events(
        cls,
        *,
        tenant_id: str,
        organization_id: str,
        execution_id: int,
        cutoff: ReplayCutoff,
        limit: int,
        after_event_id: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        return await cls.event_reader.load_events(
            tenant_id=tenant_id,
            organization_id=organization_id,
            execution_id=execution_id,
            cutoff=cutoff,
            limit=limit,
            after_event_id=after_event_id,
        )

    @classmethod
    async def load_snapshot_seed(
        cls,
        *,
        tenant_id: str,
        organization_id: str,
        execution_id: int,
        projection: str,
        cutoff: ReplayCutoff,
    ) -> Optional[ReplaySnapshotSeed]:
        return await cls.event_reader.load_snapshot_seed(
            tenant_id=tenant_id,
            organization_id=organization_id,
            execution_id=execution_id,
            projection=projection,
            cutoff=cutoff,
        )

    @classmethod
    async def replay_state(
        cls,
        *,
        tenant_id: str,
        organization_id: str,
        execution_id: int,
        cutoff: ReplayCutoff,
        projection: str,
        limit: int,
        event_reader: ReplayEventReader | None = None,
        resolve_payloads: bool = False,
        payload_resolver: ReplayPayloadResolver | None = None,
        upcaster_registry: EventUpcasterRegistry | None = None,
    ) -> dict[str, Any]:
        reader = event_reader or cls.event_reader
        registry = upcaster_registry or cls.upcaster_registry
        snapshot_seed = await reader.load_snapshot_seed(
            tenant_id=tenant_id,
            organization_id=organization_id,
            execution_id=execution_id,
            projection=projection,
            cutoff=cutoff,
        )
        registry_digest = registry.digest()
        if not replay_snapshot_is_compatible(
            snapshot_seed,
            upcaster_registry_digest=registry_digest,
        ):
            snapshot_seed = None
        events = registry.upcast_events(
            await reader.load_events(
                tenant_id=tenant_id,
                organization_id=organization_id,
                execution_id=execution_id,
                cutoff=cutoff,
                limit=limit,
                after_event_id=snapshot_seed.version if snapshot_seed else None,
            )
        )
        state = fold_replay_state(
            events,
            tenant_id=tenant_id,
            organization_id=organization_id,
            execution_id=execution_id,
            projection=projection,
            upcaster_registry_digest=registry_digest,
            base_state=snapshot_seed.state if snapshot_seed else None,
            snapshot_seed=snapshot_seed,
        )
        if resolve_payloads:
            state["payload_resolution"] = await resolve_replay_payload_references(
                state,
                payload_resolver=payload_resolver or cls.payload_resolver,
            )
            state["payload_resolution_summary"] = replay_payload_resolution_summary(
                state["payload_resolution"]
            )
        return state
