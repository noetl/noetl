"""Frame lease endpoints for the event-sourced distributed runtime."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any

from fastapi import APIRouter, HTTPException
from psycopg.rows import dict_row
from psycopg.types.json import Json

from noetl.core.db.pool import get_pool_connection
from noetl.core.event_store.ports import canonical_event_checksum
from noetl.core.logger import setup_logger
from noetl.core.messaging import NATSEventPublisher

from noetl.server.api.core.db import _next_snowflake_id

from .schema import FrameClaimRequest, FrameCommitRequest, FrameHeartbeatRequest

logger = setup_logger(__name__, include_location=True)
router = APIRouter(tags=["frames"])
_event_mirror_publisher: NATSEventPublisher | None = None


def _event_meta(*, frame: dict[str, Any], worker_id: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    meta = {
        "frame_id": str(frame["frame_id"]),
        "stage_id": str(frame["stage_id"]),
        "worker_id": worker_id,
        "actionable": False,
        "informative": True,
    }
    if frame.get("parent_frame_id") is not None:
        meta["parent_frame_id"] = str(frame["parent_frame_id"])
    if frame.get("command_id") is not None:
        meta["command_id"] = str(frame["command_id"])
    if extra:
        meta.update(extra)
    return meta


async def _load_stage(cur: Any, stage_id: int) -> dict[str, Any]:
    await cur.execute(
        """
        SELECT s.stage_id, s.execution_id, e.catalog_id, s.kind, s.step_name,
               s.dsl_ref, s.status, s.frame_policy, s.tenant_id, s.organization_id
        FROM noetl.stage s
        JOIN noetl.execution e ON e.execution_id = s.execution_id
        WHERE s.stage_id = %s
        """,
        (stage_id,),
    )
    stage = await cur.fetchone()
    if not stage:
        raise HTTPException(status_code=404, detail=f"stage not found: {stage_id}")
    if stage.get("status") not in {"OPEN", "RUNNING"}:
        raise HTTPException(
            status_code=409,
            detail={"code": "stage_not_open", "status": stage.get("status")},
        )
    return dict(stage)


async def _resolve_claim_command_id(
    cur: Any,
    *,
    execution_id: int,
    stage_id: int,
    worker_id: str,
    requested_command_id: int | None,
) -> int | None:
    if requested_command_id is not None:
        return int(requested_command_id)
    await cur.execute(
        """
        SELECT command_id
        FROM noetl.command
        WHERE execution_id = %s
          AND stage_id = %s
          AND meta->>'worker_slot_id' = %s
        ORDER BY command_id DESC
        LIMIT 1
        """,
        (execution_id, stage_id, worker_id),
    )
    row = await cur.fetchone()
    if not row:
        return None
    command_id = row.get("command_id")
    return int(command_id) if command_id is not None else None


def _frame_stream_id(*, execution_id: int, stage_id: int) -> str:
    return f"execution/{execution_id}/stage/{stage_id}"


async def _lock_frame_stream(cur: Any, *, execution_id: int, stage_id: int) -> str:
    stream_id = _frame_stream_id(execution_id=execution_id, stage_id=stage_id)
    await cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s)::bigint)", (stream_id,))
    return stream_id


async def _lock_frame_stream_for_frame(cur: Any, *, frame_id: int) -> None:
    await cur.execute(
        """
        SELECT execution_id, stage_id
        FROM noetl.frame
        WHERE frame_id = %s
        """,
        (frame_id,),
    )
    frame = await cur.fetchone()
    if frame:
        await _lock_frame_stream(
            cur,
            execution_id=int(frame["execution_id"]),
            stage_id=int(frame["stage_id"]),
        )


async def _insert_frame_event(
    cur: Any,
    *,
    frame: dict[str, Any],
    event_type: str,
    status: str,
    worker_id: str,
    result: dict[str, Any] | None = None,
    meta_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event_id = await _next_snowflake_id(cur)
    stream_id = _frame_stream_id(execution_id=int(frame["execution_id"]), stage_id=int(frame["stage_id"]))
    now = datetime.now(timezone.utc)
    catalog_id = frame.get("catalog_id")
    if catalog_id is None:
        await cur.execute(
            "SELECT catalog_id FROM noetl.execution WHERE execution_id = %s",
            (frame["execution_id"],),
        )
        catalog_row = await cur.fetchone()
        if not catalog_row:
            raise RuntimeError(f"execution not found for frame event: {frame['execution_id']}")
        catalog_id = catalog_row.get("catalog_id")
    await cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s)::bigint)", (stream_id,))
    await cur.execute(
        """
        SELECT COALESCE(max(stream_version), 0) + 1 AS next_version
        FROM noetl.event
        WHERE stream_id = %s
        """,
        (stream_id,),
    )
    version_row = await cur.fetchone()
    stream_version = int((version_row or {}).get("next_version") or 1)
    payload_ref = (result or {}).get("reference")
    event_result = result or {"status": status}
    event_meta = _event_meta(frame=frame, worker_id=worker_id, extra=meta_extra)
    envelope_checksum = canonical_event_checksum(
        {
            "tenant_id": frame["tenant_id"],
            "organization_id": frame["organization_id"],
            "execution_id": frame["execution_id"],
            "stream_id": stream_id,
            "stream_version": stream_version,
            "aggregate_id": f"frame/{frame['frame_id']}",
            "aggregate_type": "frame",
            "event_type": event_type,
            "schema_name": f"noetl.{event_type}",
            "schema_version": 1,
            "event_time": now,
            "producer": worker_id,
            "causation_id": None,
            "correlation_id": None,
            "idempotency_key": (
                f"{frame['tenant_id']}/{frame['organization_id']}/"
                f"{frame['execution_id']}/frame/{frame['frame_id']}/{event_type}"
            ),
            "payload_ref": payload_ref,
            "result": event_result,
            "meta": event_meta,
            "status": status,
            "node_name": frame.get("step_name"),
        }
    )
    await cur.execute(
        """
        INSERT INTO noetl.event (
            event_id, execution_id, catalog_id, event_type, node_name, status, result, meta,
            worker_id, tenant_id, organization_id, stream_id, aggregate_id,
            aggregate_type, schema_name, schema_version, event_time, ingest_time,
            producer, idempotency_key, payload_ref, stream_version,
            envelope_checksum, stage_id, frame_id, created_at
        )
        VALUES (
            %(event_id)s, %(execution_id)s, %(catalog_id)s, %(event_type)s, %(node_name)s,
            %(status)s, %(result)s, %(meta)s, %(worker_id)s, %(tenant_id)s,
            %(organization_id)s, %(stream_id)s, %(aggregate_id)s, 'frame',
            %(schema_name)s, 1, %(now)s, %(now)s, %(producer)s,
            %(idempotency_key)s, %(payload_ref)s, %(stream_version)s,
            %(envelope_checksum)s, %(stage_id)s, %(frame_id)s, %(now)s
        )
        """,
        {
            "event_id": event_id,
            "execution_id": frame["execution_id"],
            "catalog_id": catalog_id,
            "event_type": event_type,
            "node_name": frame.get("step_name"),
            "status": status,
            "result": Json(event_result),
            "meta": Json(event_meta),
            "worker_id": worker_id,
            "tenant_id": frame["tenant_id"],
            "organization_id": frame["organization_id"],
            "stream_id": stream_id,
            "aggregate_id": f"frame/{frame['frame_id']}",
            "schema_name": f"noetl.{event_type}",
            "producer": worker_id,
            "idempotency_key": (
                f"{frame['tenant_id']}/{frame['organization_id']}/"
                f"{frame['execution_id']}/frame/{frame['frame_id']}/{event_type}"
            ),
            "payload_ref": Json(payload_ref) if payload_ref else None,
            "stream_version": stream_version,
            "envelope_checksum": envelope_checksum,
            "stage_id": frame["stage_id"],
            "frame_id": frame["frame_id"],
            "now": now,
        },
    )
    return {
        "event_id": int(event_id),
        "execution_id": frame["execution_id"],
        "catalog_id": catalog_id,
        "event_type": event_type,
        "node_name": frame.get("step_name"),
        "status": status,
        "result": event_result,
        "meta": event_meta,
        "worker_id": worker_id,
        "tenant_id": frame["tenant_id"],
        "organization_id": frame["organization_id"],
        "stream_id": stream_id,
        "stream_version": stream_version,
        "aggregate_id": f"frame/{frame['frame_id']}",
        "aggregate_type": "frame",
        "schema_name": f"noetl.{event_type}",
        "schema_version": 1,
        "event_time": now,
        "ingest_time": now,
        "producer": worker_id,
        "idempotency_key": (
            f"{frame['tenant_id']}/{frame['organization_id']}/"
            f"{frame['execution_id']}/frame/{frame['frame_id']}/{event_type}"
        ),
        "payload_ref": payload_ref,
        "envelope_checksum": envelope_checksum,
    }


def _frame_commit_result(
    *,
    status: str,
    output_ref: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"status": status}
    if output_ref:
        result["reference"] = output_ref
    if error:
        result["context"] = {"error": error}
    return result


def _frame_recovery_policy(frame_policy: dict[str, Any] | None) -> dict[str, Any]:
    policy = frame_policy if isinstance(frame_policy, dict) else {}
    raw_max_attempts = policy.get("max_attempts")
    try:
        max_attempts = int(raw_max_attempts if raw_max_attempts is not None else 3)
    except (TypeError, ValueError):
        max_attempts = 3
    return {
        "retry_mode": "whole_frame",
        "row_split_retry": False,
        "max_attempts": max(1, max_attempts),
    }


async def _frame_conflict_detail(cur: Any, *, frame_id: int, worker_id: str) -> dict[str, Any] | None:
    await cur.execute(
        """
        SELECT frame_id, status, owner_worker, terminal_event_id
        FROM noetl.frame
        WHERE frame_id = %s
        """,
        (frame_id,),
    )
    frame = await cur.fetchone()
    if not frame:
        return None
    status = frame.get("status")
    owner_worker = frame.get("owner_worker")
    if status in {"COMPLETED", "FAILED"}:
        return {
            "code": "frame_already_terminal",
            "frame_id": frame_id,
            "status": status,
            "terminal_event_id": frame.get("terminal_event_id"),
        }
    if owner_worker and owner_worker != worker_id:
        return {
            "code": "frame_owner_mismatch",
            "frame_id": frame_id,
            "status": status,
            "owner_worker": owner_worker,
        }
    return {
        "code": "frame_not_active",
        "frame_id": frame_id,
        "status": status,
        "owner_worker": owner_worker,
    }


def _event_mirror_enabled() -> bool:
    return os.getenv("NOETL_EVENT_MIRROR_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


async def _mirror_frame_events(events: list[dict[str, Any]]) -> None:
    if not events or not _event_mirror_enabled():
        return
    global _event_mirror_publisher
    if _event_mirror_publisher is None:
        _event_mirror_publisher = NATSEventPublisher()
    for event in events:
        try:
            await _event_mirror_publisher.publish_event(event)
        except Exception as exc:
            logger.warning(
                "Frame event mirror failed event_id=%s event_type=%s: %s",
                event.get("event_id"),
                event.get("event_type"),
                exc,
            )


def _frame_response(frame: dict[str, Any], event_id: int | None = None) -> dict[str, Any]:
    response = {
        "frame_id": frame["frame_id"],
        "stage_id": frame["stage_id"],
        "execution_id": frame["execution_id"],
        "status": frame["status"],
        "cursor": frame.get("cursor") or {},
        "lease_until": frame.get("lease_until"),
        "owner_worker": frame.get("owner_worker"),
        "parent_frame_id": frame.get("parent_frame_id"),
        "command_id": frame.get("command_id"),
        "claimed_event_id": frame.get("claimed_event_id"),
        "terminal_event_id": frame.get("terminal_event_id"),
        "row_count": frame.get("row_count") or 0,
        "output_ref": frame.get("output_ref"),
        "events_emitted": frame.get("events_emitted") or 0,
    }
    if event_id is not None:
        response["event_id"] = event_id
    return response


@router.post("/stages/{stage_id}/frames/claim")
async def claim_frames(stage_id: int, req: FrameClaimRequest) -> dict[str, Any]:
    """Claim existing pending/expired frames or lazily mint frame leases."""

    try:
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                stage = await _load_stage(cur, stage_id)
                command_id = await _resolve_claim_command_id(
                    cur,
                    execution_id=stage["execution_id"],
                    stage_id=stage_id,
                    worker_id=req.worker_id,
                    requested_command_id=req.command_id,
                )
                await _lock_frame_stream(cur, execution_id=int(stage["execution_id"]), stage_id=stage_id)
                claimed: list[dict[str, Any]] = []
                events_to_mirror: list[dict[str, Any]] = []
                for _ in range(req.requested_count):
                    await cur.execute(
                        """
                        SELECT f.*,
                               (
                                   f.status IN ('CLAIMED','RUNNING')
                                   AND (f.lease_until IS NULL OR f.lease_until < now())
                               ) AS expired_lease
                        FROM noetl.frame f
                        WHERE f.stage_id = %s
                          AND (
                            f.status = 'PENDING'
                            OR (f.status IN ('CLAIMED','RUNNING')
                                AND (f.lease_until IS NULL OR f.lease_until < now()))
                          )
                        ORDER BY f.frame_id
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                        """,
                        (stage_id,),
                    )
                    frame = await cur.fetchone()
                    if not frame:
                        # Frame rows are minted lazily after the cursor driver has
                        # claimed external work. Serialize this tiny section so
                        # parent_frame_id forms a deterministic per-stage chain.
                        await cur.execute(
                            """
                            SELECT frame_id
                            FROM noetl.frame
                            WHERE stage_id = %s
                            ORDER BY frame_id DESC
                            LIMIT 1
                            """,
                            (stage_id,),
                        )
                        parent_frame_row = await cur.fetchone()
                        parent_frame_id = (parent_frame_row or {}).get("frame_id")
                        frame_id = await _next_snowflake_id(cur)
                        await cur.execute(
                            """
                            INSERT INTO noetl.frame (
                                frame_id, stage_id, execution_id, parent_frame_id,
                                cursor, row_count, status, command_id,
                                tenant_id, organization_id
                            )
                            VALUES (%s, %s, %s, %s, %s, 0, 'PENDING', %s, %s, %s)
                            RETURNING *
                            """,
                            (
                                frame_id,
                                stage_id,
                                stage["execution_id"],
                                parent_frame_id,
                                Json(req.cursor or {}),
                                command_id,
                                stage["tenant_id"],
                                stage["organization_id"],
                            ),
                        )
                        frame = await cur.fetchone()
                        frame = dict(frame)
                        frame["step_name"] = stage["step_name"]
                    else:
                        frame = dict(frame)
                        frame["step_name"] = stage["step_name"]

                    if frame.get("expired_lease"):
                        abandoned = await _insert_frame_event(
                            cur,
                            frame={**frame, "catalog_id": stage["catalog_id"]},
                            event_type="frame.abandoned",
                            status="ABANDONED",
                            worker_id=str(frame.get("owner_worker") or req.worker_id),
                            meta_extra={
                                "previous_owner_worker": frame.get("owner_worker"),
                                "reclaimer_worker": req.worker_id,
                                "lease_until": str(frame.get("lease_until")),
                                "reason": "lease_expired",
                                "previous_attempt": frame.get("attempts"),
                                "recovery": _frame_recovery_policy(
                                    req.frame_policy or stage.get("frame_policy") or {}
                                ),
                            },
                        )
                        events_to_mirror.append(abandoned)

                    await cur.execute(
                        """
                        UPDATE noetl.frame
                        SET status = 'CLAIMED',
                            owner_worker = %s,
                            command_id = COALESCE(command_id, %s),
                            lease_until = now() + (%s || ' seconds')::interval,
                            attempts = attempts + 1,
                            updated_at = now()
                        WHERE frame_id = %s
                        RETURNING *
                        """,
                        (req.worker_id, command_id, req.lease_seconds, frame["frame_id"]),
                    )
                    updated = dict(await cur.fetchone())
                    updated["step_name"] = stage["step_name"]
                    updated["catalog_id"] = stage["catalog_id"]
                    event = await _insert_frame_event(
                        cur,
                        frame=updated,
                        event_type="frame.dispatched",
                        status="CLAIMED",
                        worker_id=req.worker_id,
                        meta_extra={
                            "attempt": updated.get("attempts"),
                            "frame_policy": req.frame_policy or stage.get("frame_policy") or {},
                            "recovery": _frame_recovery_policy(
                                req.frame_policy or stage.get("frame_policy") or {}
                            ),
                        },
                    )
                    await cur.execute(
                        """
                        UPDATE noetl.frame
                        SET claimed_event_id = %s,
                            updated_at = now()
                        WHERE frame_id = %s
                        """,
                        (event["event_id"], updated["frame_id"]),
                    )
                    updated["claimed_event_id"] = event["event_id"]
                    events_to_mirror.append(event)
                    claimed.append(_frame_response(updated, event["event_id"]))

                await conn.commit()
                await _mirror_frame_events(events_to_mirror)
                return {"status": "ok", "frames": claimed}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("claim_frames failed: stage_id=%s error=%s", stage_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/frames/{frame_id}/heartbeat")
async def heartbeat_frame(frame_id: int, req: FrameHeartbeatRequest) -> dict[str, Any]:
    """Extend a frame lease and emit a replayable heartbeat event."""

    try:
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await _lock_frame_stream_for_frame(cur, frame_id=frame_id)
                await cur.execute(
                    """
                    WITH active AS (
                        SELECT f.frame_id, f.status AS previous_status
                        FROM noetl.frame f
                        WHERE f.frame_id = %s
                          AND f.owner_worker = %s
                          AND f.status IN ('CLAIMED','RUNNING')
                    )
                    UPDATE noetl.frame f
                    SET status = %s,
                        lease_until = now() + (%s || ' seconds')::interval,
                        updated_at = now()
                    FROM active
                    WHERE f.frame_id = active.frame_id
                    RETURNING f.*,
                              (SELECT step_name FROM noetl.stage WHERE stage_id = f.stage_id) AS step_name,
                              active.previous_status
                    """,
                    (frame_id, req.worker_id, req.status, req.lease_seconds),
                )
                frame = await cur.fetchone()
                if not frame:
                    detail = await _frame_conflict_detail(cur, frame_id=frame_id, worker_id=req.worker_id)
                    if detail:
                        raise HTTPException(status_code=409, detail=detail)
                    raise HTTPException(status_code=404, detail=f"active frame not found: {frame_id}")
                frame = dict(frame)
                event_type = (
                    "frame.started"
                    if frame.get("previous_status") != "RUNNING" and req.status.upper() == "RUNNING"
                    else "frame.heartbeat"
                )
                event = await _insert_frame_event(
                    cur,
                    frame=frame,
                    event_type=event_type,
                    status=req.status,
                    worker_id=req.worker_id,
                    meta_extra={"lease_until": str(frame.get("lease_until"))},
                )
                await conn.commit()
                await _mirror_frame_events([event])
                return {"status": "ok", "frame": _frame_response(frame, event["event_id"])}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("heartbeat_frame failed: frame_id=%s error=%s", frame_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/frames/{frame_id}/commit")
async def commit_frame(frame_id: int, req: FrameCommitRequest) -> dict[str, Any]:
    """Commit frame output and emit a canonical terminal frame event."""

    terminal_status = "FAILED" if req.status.upper() == "FAILED" else "COMPLETED"
    event_type = "frame.failed" if terminal_status == "FAILED" else "frame.committed"
    try:
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await _lock_frame_stream_for_frame(cur, frame_id=frame_id)
                await cur.execute(
                    """
                    UPDATE noetl.frame f
                    SET status = %s,
                        cursor = %s,
                        row_count = %s,
                        output_ref = %s,
                        events_emitted = %s,
                        completed_at = now(),
                        updated_at = now()
                    WHERE f.frame_id = %s
                      AND f.owner_worker = %s
                      AND f.status IN ('CLAIMED','RUNNING')
                    RETURNING f.*,
                              (SELECT step_name FROM noetl.stage WHERE stage_id = f.stage_id) AS step_name
                    """,
                    (
                        terminal_status,
                        Json(req.cursor or {}),
                        req.row_count,
                        Json(req.output_ref) if req.output_ref else None,
                        req.events_emitted,
                        frame_id,
                        req.worker_id,
                    ),
                )
                frame = await cur.fetchone()
                if not frame:
                    detail = await _frame_conflict_detail(cur, frame_id=frame_id, worker_id=req.worker_id)
                    if detail:
                        raise HTTPException(status_code=409, detail=detail)
                    raise HTTPException(status_code=404, detail=f"active frame not found: {frame_id}")
                frame = dict(frame)
                result = _frame_commit_result(
                    status=terminal_status,
                    output_ref=req.output_ref,
                    error=req.error,
                )
                event = await _insert_frame_event(
                    cur,
                    frame=frame,
                    event_type=event_type,
                    status=terminal_status,
                    worker_id=req.worker_id,
                    result=result,
                    meta_extra={
                        "row_count": req.row_count,
                        "events_emitted": req.events_emitted,
                        "cursor": req.cursor or {},
                        "recovery": _frame_recovery_policy(
                            (frame.get("cursor") or {}).get("frame_policy") or {}
                        ),
                    },
                )
                await cur.execute(
                    """
                    UPDATE noetl.frame
                    SET terminal_event_id = %s,
                        updated_at = now()
                    WHERE frame_id = %s
                    """,
                    (event["event_id"], frame_id),
                )
                frame["terminal_event_id"] = event["event_id"]
                await conn.commit()
                await _mirror_frame_events([event])
                return {"status": "ok", "frame": _frame_response(frame, event["event_id"])}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("commit_frame failed: frame_id=%s error=%s", frame_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
