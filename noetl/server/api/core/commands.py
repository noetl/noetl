import os
from typing import Any, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from psycopg.rows import dict_row
from psycopg_pool import PoolTimeout
from noetl.core.db.pool import get_pool_connection
from noetl.core.storage import Scope, default_store, estimate_size
from noetl.claim_policy import decide_reclaim_for_existing_claim
from .core import (
    logger,
    _COMMAND_CONTEXT_INLINE_MAX_BYTES,
    _COMMAND_TERMINAL_EVENT_TYPES,
    _EXECUTION_TERMINAL_EVENT_TYPES,
    _CLAIM_LEASE_SECONDS,
    _CLAIM_DB_ACQUIRE_TIMEOUT_SECONDS,
    _CLAIM_ACTIVE_RETRY_AFTER_SECONDS,
    _CLAIM_WORKER_HEARTBEAT_STALE_SECONDS,
    _CLAIM_HEALTHY_WORKER_HARD_TIMEOUT_SECONDS,
    _STRICT_PAYLOAD_FORBIDDEN_KEYS,
    _STRICT_RESULT_ALLOWED_KEYS,
)
from .models import ClaimRequest, ClaimResponse
from .utils import (
    _estimate_json_size,
    _compute_retry_after,
    _contains_forbidden_payload_keys,
    _contains_legacy_command_keys,
    _normalize_result_status,
)
from .db import (
    _next_snowflake_id,
    _record_db_operation_success,
    _record_db_unavailable_failure,
    _raise_if_db_short_circuit_enabled,
)
from .cache import (
    _active_claim_cache_get,
    _active_claim_cache_set,
    _active_claim_cache_invalidate,
)

router = APIRouter()
_COMMAND_CONTEXT_FIELD_INLINE_MAX_BYTES = int(
    os.getenv("NOETL_COMMAND_CONTEXT_FIELD_INLINE_MAX_BYTES", "8192")
)

def _command_input_from_model(cmd: Any) -> dict[str, Any]:
    cmd_input = getattr(cmd, "input", None)
    return cmd_input if isinstance(cmd_input, dict) else {}

def _build_command_context(cmd: Any) -> dict[str, Any]:
    return {
        "tool_config": cmd.tool.config,
        "input": _command_input_from_model(cmd),
        "render_context": cmd.render_context,
        "spec": cmd.spec.model_dump() if cmd.spec else None,
    }


async def _externalize_command_context_field_if_needed(
    *,
    execution_id: int,
    step: str,
    command_id: str,
    field_name: str,
    value: Any,
) -> Any:
    if value in (None, "", {}, []):
        return value

    try:
        size_bytes = estimate_size(value)
    except Exception:
        size_bytes = _estimate_json_size(value)

    if size_bytes <= _COMMAND_CONTEXT_FIELD_INLINE_MAX_BYTES:
        return value

    ref = await default_store.put(
        execution_id=str(execution_id),
        name=f"{step}_{field_name}",
        data=value,
        scope=Scope.EXECUTION,
        source_step=step,
        correlation={
            "command_id": command_id,
            "kind": "command_context_field",
            "field": field_name,
            "step": step,
        },
    )
    logger.debug(
        "[COMMAND-CONTEXT] Externalized field execution_id=%s step=%s command_id=%s field=%s bytes=%s store=%s",
        execution_id,
        step,
        command_id,
        field_name,
        size_bytes,
        ref.store.value,
    )
    return {
        "kind": ref.kind,
        "ref": ref.ref,
        "store": ref.store.value,
        "scope": ref.scope.value,
        "meta": ref.meta.model_dump(mode="json"),
        "correlation": ref.correlation,
    }

def _validate_postgres_command_context(*, step: str, tool_kind: str, context: dict[str, Any]) -> None:
    if str(tool_kind).lower() != "postgres": return
    tool_config = context.get("tool_config") if isinstance(context, dict) else {}
    command_input = context.get("input") if isinstance(context, dict) else {}
    auth_cfg = tool_config.get("auth") if isinstance(tool_config, dict) else None
    if auth_cfg in (None, "", {}):
        auth_cfg = command_input.get("auth") if isinstance(command_input, dict) else None
    if auth_cfg in (None, "", {}):
        raise ValueError(f"Postgres command for step '{step}' is missing auth in command context.")
    forbidden_fields = {"db_host", "db_port", "db_user", "db_password", "db_name", "db_conn_string"}
    direct_fields = {key for key in forbidden_fields if (tool_config.get(key) not in (None, "")) or (command_input.get(key) not in (None, ""))}
    if direct_fields:
        raise ValueError(f"Postgres command for step '{step}' includes forbidden direct connection fields: {', '.join(sorted(direct_fields))}")

def _validate_postgres_command_context_or_422(*, step: str, tool_kind: str, context: dict[str, Any]) -> None:
    try:
        _validate_postgres_command_context(step=step, tool_kind=tool_kind, context=context)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid command context for step '{step}' and tool '{tool_kind}': {exc}")


async def _store_command_context_if_needed(*, execution_id: int, step: str, command_id: str, context: dict[str, Any]) -> dict[str, Any]:
    compact_context = dict(context)
    for field_name in ("tool_config", "render_context", "spec", "input"):
        if field_name not in compact_context:
            continue
        val = compact_context[field_name]
        compact_context[field_name] = await _externalize_command_context_field_if_needed(
            execution_id=execution_id,
            step=step,
            command_id=command_id,
            field_name=field_name,
            value=val,
        )

    try: size_bytes = estimate_size(context)
    except Exception: size_bytes = _estimate_json_size(context)
    try:
        compact_size_bytes = estimate_size(compact_context)
    except Exception:
        compact_size_bytes = _estimate_json_size(compact_context)
    if compact_size_bytes <= _COMMAND_CONTEXT_INLINE_MAX_BYTES:
        return compact_context
    try:
        ref = await default_store.put(
            execution_id=str(execution_id), name=f"{step}_command_context", data=compact_context,
            scope=Scope.EXECUTION, source_step=step,
            correlation={"command_id": command_id, "kind": "command_context", "step": step},
        )
        logger.debug("[COMMAND-CONTEXT] Externalized command context execution_id=%s step=%s command_id=%s bytes=%s compact_bytes=%s store=%s",
                    execution_id, step, command_id, size_bytes, compact_size_bytes, ref.store.value)
        return {
            "kind": ref.kind, "ref": ref.ref, "store": ref.store.value, "scope": ref.scope.value,
            "meta": ref.meta.model_dump(mode="json"), "correlation": ref.correlation,
        }
    except Exception as exc:
        logger.warning("[COMMAND-CONTEXT] Failed to externalize context execution_id=%s step=%s command_id=%s error=%s",
                       execution_id, step, command_id, exc)
        return compact_context

_EVENT_RESULT_INLINE_ROWS_MAX = 16
_EVENT_RESULT_INLINE_ROWS_MAX_BYTES = 64 * 1024


def _build_reference_only_result(*, payload: dict[str, Any], status: str) -> dict[str, Any]:
    from .utils import _normalize_result_status, _estimate_json_size
    from .core import _EVENT_RESULT_CONTEXT_MAX_BYTES
    from .events import _collect_compact_context, _bounded_context
    result_obj: dict[str, Any] = {"status": _normalize_result_status(status)}
    payload_result = payload.get("result") or payload.get("response")
    if isinstance(payload_result, dict):
        payload_status = payload_result.get("status")
        if isinstance(payload_status, str) and payload_status.strip():
            result_obj["status"] = _normalize_result_status(payload_status)
        if isinstance(payload_result.get("reference"), dict):
            result_obj["reference"] = payload_result.get("reference")
        context = _bounded_context(payload_result.get('context') or payload_result)
        if isinstance(context, dict): result_obj["context"] = context
        # Preserve small inline row sets so step-level set: and arc when: expressions
        # that reference output.data.rows[N].<col> can be re-rendered during state
        # replay (when the state cache is invalidated).  Without this, Jinja
        # StrictUndefined on the missing 'rows' key causes render_template to fall
        # back to the literal template string, which then gets coerced to 0 by
        # downstream `| int` filters and produces wrong SQL (e.g.
        # `WHERE facility_mapping_id = 0`).  Only embed when small — both in row
        # count and serialized bytes — to keep the event table bounded.
        inline_rows = payload_result.get("rows")
        if (
            isinstance(inline_rows, list)
            and 0 < len(inline_rows) <= _EVENT_RESULT_INLINE_ROWS_MAX
            and result_obj.get("reference") is None
        ):
            rows_bytes = _estimate_json_size(inline_rows)
            if rows_bytes <= _EVENT_RESULT_INLINE_ROWS_MAX_BYTES:
                result_obj["rows"] = inline_rows
                if "row_count" not in (result_obj.get("context") or {}):
                    result_obj.setdefault("context", {})["row_count"] = len(inline_rows)
    else:
        if isinstance(payload.get("reference"), dict):
            result_obj["reference"] = payload.get("reference")
        direct_context = _bounded_context(payload.get('context') or payload.get('response') or payload)
        if isinstance(direct_context, dict): result_obj["context"] = direct_context
    compact = _collect_compact_context(payload)
    if compact:
        existing_context = result_obj.get("context")
        if isinstance(existing_context, dict):
            merged = {**compact, **existing_context}
            if _estimate_json_size(merged) <= _EVENT_RESULT_CONTEXT_MAX_BYTES:
                result_obj["context"] = merged
        else:
            if _estimate_json_size(compact) <= _EVENT_RESULT_CONTEXT_MAX_BYTES:
                result_obj["context"] = compact
    return result_obj

async def _fetch_execution_terminal_event(cur, execution_id: int) -> Optional[dict[str, Any]]:
    await cur.execute(
        "SELECT event_type, created_at FROM noetl.event WHERE execution_id = %s AND event_type = ANY(%s) ORDER BY event_id DESC LIMIT 1",
        (execution_id, _EXECUTION_TERMINAL_EVENT_TYPES),
    )
    row = await cur.fetchone()
    return row if isinstance(row, dict) else None

@router.get("/commands/{event_id}")
async def get_command(event_id: int):
    try:
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                # Primary: query the command projection table (O(1) by event_id)
                await cur.execute("""
                    SELECT execution_id, step_name, tool_kind, context, meta
                    FROM noetl.command
                    WHERE event_id = %s
                """, (event_id,))
                row = await cur.fetchone()
                if not row:
                    # Fallback: query event table for backward compat (pre-command-table commands)
                    await cur.execute("""
                        SELECT execution_id, node_name as step_name, node_type as tool_kind, context, meta
                        FROM noetl.event
                        WHERE event_id = %s AND event_type = 'command.issued'
                    """, (event_id,))
                    row = await cur.fetchone()
                if not row: raise HTTPException(404, f"command not found: {event_id}")
                return {
                    "execution_id": row['execution_id'], "node_id": row['step_name'], "node_name": row['step_name'],
                    "action": row['tool_kind'], "context": row['context'] or {}, "meta": row['meta']
                }
    except HTTPException: raise
    except Exception as e:
        logger.error(f"get_command failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))

@router.post("/commands/{event_id}/claim", response_model=ClaimResponse)
async def claim_command(event_id: int, req: ClaimRequest):
    try:
        _raise_if_db_short_circuit_enabled(operation="claim_command")
        cached_claim = _active_claim_cache_get(event_id)
        if cached_claim and cached_claim.worker_id != req.worker_id:
            raise HTTPException(409, detail={
                "code": "active_claim", "message": f"Command already claimed by {cached_claim.worker_id}",
                "worker_id": cached_claim.worker_id, "claim_policy": "cache_fast_path",
            }, headers={"Retry-After": str(max(1, _CLAIM_ACTIVE_RETRY_AFTER_SECONDS))})

        async with get_pool_connection(timeout=_CLAIM_DB_ACQUIRE_TIMEOUT_SECONDS) as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                # Primary: query the command projection table (single-row PK lookup)
                await cur.execute("""
                    SELECT command_id, execution_id, catalog_id, step_name, tool_kind, context, meta, status, worker_id, updated_at
                    FROM noetl.command
                    WHERE event_id = %s
                """, (event_id,))
                cmd_row = await cur.fetchone()
                if not cmd_row:
                    # Fallback: query event table for pre-command-table commands
                    await cur.execute("""
                        SELECT execution_id, catalog_id, node_name as step_name, node_type as tool_kind, context, meta
                        FROM noetl.event WHERE event_id = %s AND event_type = 'command.issued'
                    """, (event_id,))
                    cmd_row = await cur.fetchone()
                _record_db_operation_success()
                if not cmd_row: raise HTTPException(404, f"command not found: {event_id}")

                execution_id = cmd_row['execution_id']
                catalog_id = cmd_row['catalog_id']
                step = cmd_row['step_name']
                tool_kind = cmd_row['tool_kind']
                context, meta = cmd_row['context'] or {}, cmd_row['meta'] or {}
                # command_id is BIGINT snowflake. Fall back to event_id when neither
                # cmd_row nor meta has a usable id (last-resort, same numeric domain).
                _raw_cid = cmd_row.get('command_id') or meta.get('command_id')
                if _raw_cid is None:
                    command_id = int(event_id)
                elif isinstance(_raw_cid, int):
                    command_id = _raw_cid
                elif isinstance(_raw_cid, str) and _raw_cid.strip().isdigit():
                    command_id = int(_raw_cid.strip())
                else:
                    command_id = int(event_id)

                # Check terminal status from command table (O(1) instead of event scan)
                cmd_status = cmd_row.get('status', 'PENDING')
                if cmd_status in ('COMPLETED', 'FAILED', 'CANCELLED'):
                    _active_claim_cache_invalidate(command_id=command_id, event_id=event_id)
                    raise HTTPException(409, detail={"code": "already_terminal", "message": f"Command status: {cmd_status}"})

                # Fallback: check event table for terminal status (pre-command-table)
                if not cmd_row.get('command_id'):
                    # meta->>'command_id' returns TEXT; cast %s to text to compare safely
                    await cur.execute(
                        f"SELECT event_type FROM noetl.event WHERE execution_id = %s AND event_type = ANY(%s) AND meta->>'command_id' = %s::text ORDER BY event_id DESC LIMIT 1",
                        (execution_id, _COMMAND_TERMINAL_EVENT_TYPES, command_id),
                    )
                if await cur.fetchone():
                    _active_claim_cache_invalidate(command_id=command_id, event_id=event_id)
                    raise HTTPException(409, detail={"code": "already_terminal", "message": "Command already reached terminal state"})

                if await _fetch_execution_terminal_event(cur, execution_id):
                    _active_claim_cache_invalidate(command_id=command_id, event_id=event_id)
                    raise HTTPException(409, detail={"code": "already_terminal", "message": "Execution already reached terminal state"})

                # command_id is BIGINT snowflake; pass directly as advisory lock key
                await cur.execute("SELECT pg_try_advisory_xact_lock(%s) as lock_acquired", (command_id,))
                if not (row := await cur.fetchone()) or not row.get('lock_acquired'):
                    raise HTTPException(409, detail={"code": "active_claim", "message": "Command is being claimed"},
                                        headers={"Retry-After": str(max(1, _CLAIM_ACTIVE_RETRY_AFTER_SECONDS))})

                await cur.execute(
                    "SELECT event_id, worker_id, meta, created_at FROM noetl.event WHERE execution_id = %s AND event_type IN ('command.claimed', 'command.heartbeat') AND meta->>'command_id' = %s::text ORDER BY event_id DESC LIMIT 1",
                    (execution_id, command_id),
                )
                existing = await cur.fetchone()
                stale_reclaim = False
                if existing:
                    existing_worker = existing.get('worker_id') or (existing.get('meta') or {}).get('worker_id')
                    if existing_worker and existing_worker != req.worker_id:
                        created_at = existing.get("created_at")
                        if created_at.tzinfo is None: created_at = created_at.replace(tzinfo=timezone.utc)
                        claim_age = (datetime.now(timezone.utc) - created_at).total_seconds()
                        
                        worker_status, heartbeat_age = None, None
                        await cur.execute("SELECT status, heartbeat FROM noetl.runtime WHERE kind = 'worker_pool' AND name = %s ORDER BY updated_at DESC LIMIT 1", (existing_worker,))
                        if r_row := await cur.fetchone():
                            worker_status = (r_row.get("status") or "").lower()
                            if hb := r_row.get("heartbeat"):
                                if hb.tzinfo is None: hb = hb.replace(tzinfo=timezone.utc)
                                heartbeat_age = (datetime.now(timezone.utc) - hb).total_seconds()

                        decision = decide_reclaim_for_existing_claim(
                            existing_worker=existing_worker, requesting_worker=req.worker_id,
                            claim_age_seconds=claim_age, lease_seconds=_CLAIM_LEASE_SECONDS,
                            worker_runtime_status=worker_status, worker_heartbeat_age_seconds=heartbeat_age,
                            heartbeat_stale_seconds=_CLAIM_WORKER_HEARTBEAT_STALE_SECONDS,
                            healthy_worker_hard_timeout_seconds=_CLAIM_HEALTHY_WORKER_HARD_TIMEOUT_SECONDS,
                        )
                        if decision.reclaim:
                            stale_reclaim = True
                            reclaimed_from = existing_worker
                            reclaimed_reason = decision.reason or "lease_expired"
                        else:
                            _active_claim_cache_set(event_id, command_id, existing_worker)
                            raise HTTPException(409, detail={"code": "active_claim", "worker_id": existing_worker},
                                                headers={"Retry-After": str(_CLAIM_ACTIVE_RETRY_AFTER_SECONDS)})
                    elif existing_worker == req.worker_id:
                        await cur.execute("SELECT event_type FROM noetl.event WHERE execution_id = %s AND event_type IN ('command.started', 'command.heartbeat', 'command.completed', 'command.failed') AND meta->>'command_id' = %s ORDER BY event_id DESC LIMIT 1", (execution_id, command_id))
                        if (r := await cur.fetchone()) and r.get("event_type") == "command.started":
                            _active_claim_cache_set(event_id, command_id, existing_worker)
                            raise HTTPException(409, detail={"code": "active_claim", "worker_status": "running"},
                                                headers={"Retry-After": str(_CLAIM_ACTIVE_RETRY_AFTER_SECONDS)})
                    if not stale_reclaim:
                        _active_claim_cache_set(event_id, command_id, req.worker_id)
                        return ClaimResponse(status="ok", event_id=event_id, execution_id=execution_id, node_id=step, node_name=step, action=tool_kind, context=context, meta=meta)

                claim_evt_id = await _next_snowflake_id(cur)
                claim_meta = {"command_id": command_id, "worker_id": req.worker_id, "actionable": False, "informative": True}
                if stale_reclaim:
                    claim_meta.update({"reclaimed": True, "reclaimed_from_worker": reclaimed_from, "reclaimed_reason": reclaimed_reason})
                
                res_obj = _build_reference_only_result(payload={"command_id": command_id}, status="RUNNING")
                await cur.execute("""
                    INSERT INTO noetl.event (event_id, execution_id, catalog_id, event_type, node_id, node_name, status, result, meta, worker_id, created_at)
                    SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    WHERE NOT EXISTS (SELECT 1 FROM noetl.event WHERE execution_id = %s AND event_type = ANY(%s) LIMIT 1)
                    RETURNING event_id
                """, (claim_evt_id, execution_id, catalog_id, "command.claimed", step, step, "RUNNING", Json(res_obj), Json(claim_meta), req.worker_id, datetime.now(timezone.utc), execution_id, _EXECUTION_TERMINAL_EVENT_TYPES))
                
                if not await cur.fetchone():
                    _active_claim_cache_invalidate(command_id=command_id, event_id=event_id)
                    raise HTTPException(409, detail={"code": "already_terminal"})

                await cur.execute(
                    """
                    UPDATE noetl.command
                    SET status = 'CLAIMED',
                        worker_id = %s,
                        claimed_at = now(),
                        latest_event_id = %s,
                        updated_at = now()
                    WHERE command_id = %s
                    """,
                    (req.worker_id, claim_evt_id, command_id),
                )
                
                await conn.commit()
                _active_claim_cache_set(event_id, command_id, req.worker_id)
                logger.info(f"[CLAIM] Command {command_id} claimed by {req.worker_id}")
                return ClaimResponse(status="ok", event_id=event_id, execution_id=execution_id, node_id=step, node_name=step, action=tool_kind, context=context, meta=meta)
    except HTTPException: raise
    except PoolTimeout:
        raise HTTPException(status_code=503, detail={"code": "pool_saturated"}, headers={"Retry-After": _compute_retry_after()})
    except Exception as e:
        if retry_after := _record_db_unavailable_failure(e, operation="claim_command"):
            raise HTTPException(status_code=503, detail={"code": "db_unavailable"}, headers={"Retry-After": retry_after})
        logger.error(f"claim_command failed: {e}", exc_info=True)
        raise HTTPException(500, detail={"code": "internal_error", "message": str(e)})

from psycopg.types.json import Json
