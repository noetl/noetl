"""Replay service for event-sourced runtime projections.

Phase 0 intentionally folds only lightweight state from canonical event
metadata. Payload refs are surfaced as lineage; durable payload resolution lands
in a later phase.
"""

from __future__ import annotations

import hashlib
import json
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional

from psycopg.rows import dict_row

from noetl.core.db.pool import get_pool_connection
from noetl.core.replay import default_upcaster_registry


@dataclass(frozen=True)
class ReplayCutoff:
    """Replay cutoff. Exactly one field is normally set."""

    as_of_event_id: Optional[int] = None
    as_of_position: Optional[int] = None
    as_of_time: Optional[datetime] = None


@dataclass(frozen=True)
class ReplaySnapshotSeed:
    """Snapshot state used as replay seed."""

    aggregate_id: str
    aggregate_type: str
    version: int
    checksum: str
    state: dict[str, Any]
    meta: dict[str, Any]


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


class ReplayService:
    """Read canonical events and fold replay state."""

    @staticmethod
    async def _event_columns(conn: Any) -> set[str]:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'noetl'
                  AND table_name = 'event'
                """
            )
            rows = await cur.fetchall()
        return {
            str(row["column_name"] if isinstance(row, Mapping) else row[0])
            for row in rows
        }

    @staticmethod
    async def load_events(
        *,
        tenant_id: str,
        organization_id: str,
        execution_id: int,
        cutoff: ReplayCutoff,
        limit: int,
        after_event_id: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        async with get_pool_connection() as conn:
            columns = await ReplayService._event_columns(conn)
            envelope_columns = (
                "tenant_id",
                "organization_id",
                "stream_id",
                "stream_version",
                "aggregate_id",
                "aggregate_type",
                "schema_name",
                "schema_version",
                "event_time",
                "ingest_time",
                "producer",
                "causation_id",
                "correlation_id",
                "idempotency_key",
                "payload_ref",
                "stage_id",
                "frame_id",
                "command_id",
                "envelope_checksum",
            )

            predicates = ["execution_id = %s"]
            params: list[Any] = [execution_id]
            if "tenant_id" in columns:
                predicates.append("tenant_id = %s")
                params.append(tenant_id)
            elif tenant_id != "default":
                return []
            if "organization_id" in columns:
                predicates.append("organization_id = %s")
                params.append(organization_id)
            elif organization_id != "default":
                return []

            cutoff_event_id = cutoff.as_of_event_id or cutoff.as_of_position
            if after_event_id is not None:
                predicates.append("event_id > %s")
                params.append(int(after_event_id))
            if cutoff_event_id is not None:
                predicates.append("event_id <= %s")
                params.append(int(cutoff_event_id))
            if cutoff.as_of_time is not None:
                time_column = "event_time" if "event_time" in columns else "created_at"
                predicates.append(f"{time_column} <= %s")
                params.append(cutoff.as_of_time)
            params.append(limit)

            select_columns = [
                "event_id",
                "event_type",
                "status",
                "node_name",
                "result",
                "meta",
            ]
            select_columns.extend(column for column in envelope_columns if column in columns)

            query = f"""
                SELECT {', '.join(select_columns)}
                FROM noetl.event
                WHERE {' AND '.join(predicates)}
                ORDER BY event_id ASC
                LIMIT %s
            """

            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(query, params)
                rows = await cur.fetchall()

        events = [dict(row) for row in rows]
        for event in events:
            event.setdefault("tenant_id", tenant_id)
            event.setdefault("organization_id", organization_id)
            for column in envelope_columns:
                event.setdefault(column, None)
        return events

    @staticmethod
    async def load_snapshot_seed(
        *,
        tenant_id: str,
        organization_id: str,
        execution_id: int,
        projection: str,
        cutoff: ReplayCutoff,
    ) -> Optional[ReplaySnapshotSeed]:
        # Event-id/position snapshots are safe because projection_snapshot.version
        # records an event position. Time-based snapshot selection needs a separate
        # event-time index and remains a later release gate.
        cutoff_event_id = cutoff.as_of_event_id or cutoff.as_of_position
        if cutoff.as_of_time is not None:
            return None

        aggregate_id = f"execution/{execution_id}/{projection}"
        aggregate_type = "replay_state"
        predicates = [
            "tenant_id = %s",
            "organization_id = %s",
            "aggregate_type = %s",
            "aggregate_id = %s",
        ]
        params: list[Any] = [tenant_id, organization_id, aggregate_type, aggregate_id]
        if cutoff_event_id is not None:
            predicates.append("version <= %s")
            params.append(int(cutoff_event_id))

        try:
            async with get_pool_connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        f"""
                        SELECT aggregate_id, aggregate_type, version, snapshot, checksum, meta
                        FROM noetl.projection_snapshot
                        WHERE {' AND '.join(predicates)}
                        ORDER BY version DESC
                        LIMIT 1
                        """,
                        params,
                    )
                    row = await cur.fetchone()
        except Exception:
            return None
        if not row:
            return None
        snapshot = row["snapshot"] if isinstance(row["snapshot"], dict) else {}
        meta = row["meta"] if isinstance(row["meta"], dict) else {}
        return ReplaySnapshotSeed(
            aggregate_id=str(row["aggregate_id"]),
            aggregate_type=str(row["aggregate_type"]),
            version=int(row["version"]),
            checksum=str(row["checksum"]),
            state=snapshot,
            meta=meta,
        )

    @staticmethod
    async def replay_state(
        *,
        tenant_id: str,
        organization_id: str,
        execution_id: int,
        cutoff: ReplayCutoff,
        projection: str,
        limit: int,
    ) -> dict[str, Any]:
        snapshot_seed = await ReplayService.load_snapshot_seed(
            tenant_id=tenant_id,
            organization_id=organization_id,
            execution_id=execution_id,
            projection=projection,
            cutoff=cutoff,
        )
        events = default_upcaster_registry.upcast_events(
            await ReplayService.load_events(
                tenant_id=tenant_id,
                organization_id=organization_id,
                execution_id=execution_id,
                cutoff=cutoff,
                limit=limit,
                after_event_id=snapshot_seed.version if snapshot_seed else None,
            )
        )
        return fold_replay_state(
            events,
            tenant_id=tenant_id,
            organization_id=organization_id,
            execution_id=execution_id,
            projection=projection,
            upcaster_registry_digest=default_upcaster_registry.digest(),
            base_state=snapshot_seed.state if snapshot_seed else None,
            snapshot_seed=snapshot_seed,
        )
