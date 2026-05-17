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
                frame["terminal_event_id"] = event_id
            elif event_type == "frame.failed":
                frame["status"] = status or "FAILED"
                frame["terminal_event_id"] = event_id
            elif status:
                frame["status"] = str(status)

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
