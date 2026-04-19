import os
import json
from datetime import datetime, timezone
from typing import Any, Optional
from fastapi import APIRouter, HTTPException
from psycopg.rows import dict_row
from psycopg_pool import PoolTimeout
from psycopg.types.json import Json
from noetl.core.db.pool import get_pool_connection
from noetl.core.dsl.engine.models import Event
from noetl.server.api.supervision import supervise_persisted_event, supervise_command_issued
from .core import (
    logger,
    get_engine,
    _STRICT_PAYLOAD_FORBIDDEN_KEYS,
    _STRICT_RESULT_ALLOWED_KEYS,
    _STRICT_CONTEXT_FORBIDDEN_KEYS,
    _EVENT_RESULT_CONTEXT_MAX_BYTES,
    _COMMAND_EVENT_DEDUPE_TYPES,
)
from .models import EventRequest, EventResponse
from .utils import (
    _status_from_event_name,
    _estimate_json_size,
    _compute_retry_after,
    _contains_forbidden_payload_keys,
    _contains_legacy_command_keys,
)
from .db import (
    _next_snowflake_id,
    _record_db_operation_success,
    _record_db_unavailable_failure,
    _raise_if_db_short_circuit_enabled,
)
from .cache import _active_claim_cache_invalidate
from .recovery import _publish_commands_with_recovery

router = APIRouter()

def _validate_reference_only_payload(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict): raise ValueError("event payload must be an object")
    if any(key in payload for key in _STRICT_PAYLOAD_FORBIDDEN_KEYS):
        bad = sorted(key for key in payload.keys() if key in _STRICT_PAYLOAD_FORBIDDEN_KEYS)
        raise ValueError(f"payload includes forbidden inline output keys: {', '.join(bad)}")
    result_obj = payload.get("result")
    if result_obj is None: return
    if not isinstance(result_obj, dict): raise ValueError("payload.result must be an object")
    unknown = sorted(str(k) for k in result_obj.keys() if str(k) not in _STRICT_RESULT_ALLOWED_KEYS)
    if unknown: raise ValueError(f"payload.result includes unsupported keys: {', '.join(unknown)}")
    if (ref := result_obj.get("reference")) is not None and not isinstance(ref, dict):
        raise ValueError("payload.result.reference must be an object")
    if (ctx := result_obj.get("context")) is not None:
        if not isinstance(ctx, dict): raise ValueError("payload.result.context must be an object")
        if _contains_forbidden_payload_keys(ctx, _STRICT_CONTEXT_FORBIDDEN_KEYS):
            raise ValueError("payload.result.context includes forbidden inline data keys")
        if _contains_legacy_command_keys(ctx):
            raise ValueError("payload.result.context includes legacy command_* keys")

def _extract_event_error(payload: dict[str, Any]) -> Optional[str]:
    if not isinstance(payload, dict): return None
    direct_error = payload.get("error")
    if isinstance(direct_error, str): return direct_error.strip()[:2000] or None
    if isinstance(direct_error, dict):
        if (msg := direct_error.get("message")) and isinstance(msg, str): return msg.strip()[:2000]
        return json.dumps(direct_error, default=str)[:2000]
    if isinstance(res := payload.get("result"), dict):
        res_error = res.get("error")
        if isinstance(res_error, str): return res_error.strip()[:2000] or None
        if isinstance(res_error, dict):
            if (msg := res_error.get("message")) and isinstance(msg, str): return msg.strip()[:2000]
            return json.dumps(res_error, default=str)[:2000]
    return None

def _extract_command_id_from_payload(payload: Optional[dict[str, Any]], meta: Optional[dict[str, Any]] = None) -> Optional[str]:
    p = payload if isinstance(payload, dict) else {}
    m = meta if isinstance(meta, dict) else {}
    candidates = [p.get("command_id"), m.get("command_id")]
    if isinstance(ctx := p.get("context"), dict): candidates.append(ctx.get("command_id"))
    if isinstance(res := p.get("result"), dict):
        candidates.append(res.get("command_id"))
        if isinstance(rctx := res.get("context"), dict): candidates.append(rctx.get("command_id"))
    for val in candidates:
        if isinstance(val, str) and val.strip(): return val.strip()
    return None

def _collect_compact_context(payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    keys = ("command_id", "loop_event_id", "request_id", "event_ids", "commands_generated", "error_code", "message", "worker_id", "batch_request_id")
    compact = {k: payload[k] for k in keys if k in payload and payload[k] is not None}
    return compact or None

def _bounded_context(context_obj: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not isinstance(context_obj, dict): return None
    # PERFORMANCE & CORRECTNESS FIX:
    # Do not silently delete entire contexts just because they contain "data" or "command_0" keys.
    # The JSON size threshold is sufficient to prevent event table bloat.
    if _estimate_json_size(context_obj) > _EVENT_RESULT_CONTEXT_MAX_BYTES: return None
    return context_obj

async def _invalidate_execution_state_cache(execution_id: str, reason: str, engine=None) -> None:
    try:
        active_engine = engine or get_engine()
        await active_engine.state_store.invalidate_state(str(execution_id), reason=reason)
    except Exception as e:
        logger.warning("[STATE-CACHE-INVALIDATE] failed execution_id=%s reason=%s error=%s", execution_id, reason, e)

@router.post("/events", response_model=EventResponse)
async def handle_event(req: EventRequest) -> EventResponse:
    from .commands import _build_reference_only_result, _build_command_context, _validate_postgres_command_context_or_422, _store_command_context_if_needed
    engine = None
    commands_generated = False
    try:
        _raise_if_db_short_circuit_enabled(operation="handle_event")
        engine = get_engine()
        skip_engine_events = {"command.claimed", "command.heartbeat", "command.started", "command.completed", "step.enter"}

        if req.name == "command.claimed":
            _validate_reference_only_payload(req.payload)
            command_id = _extract_command_id_from_payload(req.payload, req.meta)
            if command_id:
                async with get_pool_connection() as conn:
                    async with conn.cursor(row_factory=dict_row) as cur:
                        evt_id = await _next_snowflake_id(cur)
                        await cur.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s)::bigint) as lock_acquired", (command_id,))
                        if not (res := await cur.fetchone()) or not res.get('lock_acquired'):
                            raise HTTPException(409, "Command already being claimed")
                        await cur.execute("SELECT worker_id, meta FROM noetl.event WHERE execution_id = %s AND event_type = 'command.claimed' AND meta->>'command_id' = %s ORDER BY event_id DESC LIMIT 1", (int(req.execution_id), command_id))
                        if existing := await cur.fetchone():
                            existing_worker = existing.get('worker_id') or (existing.get('meta') or {}).get('worker_id')
                            if existing_worker and existing_worker != req.worker_id:
                                raise HTTPException(409, f"Command already claimed by {existing_worker}")
                            return EventResponse(status="ok", event_id=0, commands_generated=0)
                        await cur.execute("SELECT catalog_id FROM noetl.event WHERE execution_id = %s LIMIT 1", (int(req.execution_id),))
                        catalog_id = (await cur.fetchone() or {}).get('catalog_id')
                        meta_obj = {**(req.meta or {}), "actionable": req.actionable, "informative": req.informative, "command_id": command_id, "worker_id": req.worker_id}
                        res_obj = _build_reference_only_result(payload=req.payload, status="RUNNING")
                        await cur.execute("""
                            INSERT INTO noetl.event (event_id, execution_id, catalog_id, event_type, node_id, node_name, status, result, meta, worker_id, created_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (evt_id, int(req.execution_id), catalog_id, req.name, req.step, req.step, "RUNNING", Json(res_obj), Json(meta_obj), req.worker_id, datetime.now(timezone.utc)))
                        await conn.commit()
                        _record_db_operation_success()
                        return EventResponse(status="ok", event_id=evt_id, commands_generated=0)

        status = _status_from_event_name(req.name)
        _validate_reference_only_payload(req.payload)
        res_obj = _build_reference_only_result(payload=req.payload, status=status)
        error_text = _extract_event_error(req.payload)
        command_id = _extract_command_id_from_payload(req.payload, req.meta)
        event_meta = {**(req.meta or {}), "actionable": req.actionable, "informative": req.informative, "worker_id": req.worker_id, "command_id": command_id}

        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("SELECT catalog_id FROM noetl.event WHERE execution_id = %s LIMIT 1", (int(req.execution_id),))
                catalog_id = (await cur.fetchone() or {}).get('catalog_id')
                if command_id and req.name in _COMMAND_EVENT_DEDUPE_TYPES:
                    await cur.execute("SELECT event_id FROM noetl.event WHERE execution_id = %s AND event_type = %s AND node_name = %s AND meta->>'command_id' = %s ORDER BY event_id DESC LIMIT 1", (int(req.execution_id), req.name, req.step, command_id))
                    if duplicate := await cur.fetchone():
                        if req.name in {"command.completed", "command.failed"}: _active_claim_cache_invalidate(command_id=command_id)
                        return EventResponse(status="ok", event_id=int(duplicate['event_id']), commands_generated=0)
                evt_id = await _next_snowflake_id(cur)
                event_meta["persisted_event_id"] = str(evt_id)
                await cur.execute("""
                    INSERT INTO noetl.event (event_id, execution_id, catalog_id, event_type, node_id, node_name, status, result, meta, error, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (evt_id, int(req.execution_id), catalog_id, req.name, req.step, req.step, status, Json(res_obj), Json(event_meta), error_text, datetime.now(timezone.utc)))
                await conn.commit()
                _record_db_operation_success()

                # Update the mutable command projection for lifecycle events
                if command_id and req.name in {
                    "command.claimed", "command.started",
                    "command.completed", "command.failed", "command.cancelled",
                }:
                    try:
                        if req.name == "command.started":
                            # Guard against out-of-order lifecycle events: never downgrade terminal state.
                            await cur.execute(
                                """
                                UPDATE noetl.command
                                SET status = CASE WHEN completed_at IS NULL THEN 'RUNNING' ELSE status END,
                                    started_at = COALESCE(started_at, now()),
                                    latest_event_id = CASE WHEN completed_at IS NULL THEN %s ELSE latest_event_id END,
                                    updated_at = CASE WHEN completed_at IS NULL THEN now() ELSE updated_at END
                                WHERE command_id = %s
                                """,
                                (evt_id, command_id),
                            )
                        else:
                            _cmd_status = {
                                "command.claimed": "CLAIMED",
                                "command.completed": "COMPLETED",
                                "command.failed": "FAILED",
                                "command.cancelled": "CANCELLED",
                            }.get(req.name, status)
                            _cmd_updates = ["status = %s", "latest_event_id = %s", "updated_at = now()"]
                            _cmd_params: list = [_cmd_status, evt_id]
                            if req.name == "command.claimed":
                                _cmd_updates.extend(["worker_id = %s", "claimed_at = now()"])
                                _cmd_params.append(req.worker_id)
                            elif req.name in ("command.completed", "command.failed", "command.cancelled"):
                                _cmd_updates.extend(["completed_at = now()", "result = %s", "error = %s"])
                                _cmd_params.extend([Json(res_obj), error_text])
                            _cmd_params.append(command_id)
                            await cur.execute(
                                f"UPDATE noetl.command SET {', '.join(_cmd_updates)} WHERE command_id = %s",
                                _cmd_params,
                            )
                    except Exception as _cmd_exc:
                        logger.debug("[COMMAND-TABLE] Status update failed for %s: %s", command_id, _cmd_exc)

        await supervise_persisted_event(req.execution_id, req.step, req.name, req.payload, event_meta, event_id=int(evt_id))
        if req.name in {"command.completed", "command.failed"} and command_id: _active_claim_cache_invalidate(command_id=command_id)
        
        event = Event(execution_id=req.execution_id, step=req.step, name=req.name, payload=req.payload, meta=event_meta, timestamp=datetime.now(timezone.utc), worker_id=req.worker_id, attempt=event_meta.get("attempt", 1))
        commands = []
        if req.name not in skip_engine_events:
            async with get_pool_connection() as engine_conn:
                async with engine_conn.transaction():
                    async with engine_conn.cursor() as cur: await cur.execute("SELECT pg_advisory_xact_lock(%s)", (int(req.execution_id),))
                    commands = await engine.handle_event(event, conn=engine_conn, already_persisted=True)
            commands_generated = bool(commands)

        server_url = os.getenv("NOETL_SERVER_URL", "http://noetl.noetl.svc.cluster.local:8082")
        command_events, supervisor_commands = [], []
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                for cmd in commands:
                    await cur.execute("SELECT catalog_id, parent_execution_id FROM noetl.event WHERE execution_id = %s LIMIT 1", (int(cmd.execution_id),))
                    row = await cur.fetchone() or {}
                    cat_id, p_exec = row.get('catalog_id', catalog_id), row.get('parent_execution_id')
                    cmd_id, new_evt_id = f"{cmd.execution_id}:{cmd.step}:{await _next_snowflake_id(cur)}", await _next_snowflake_id(cur)
                    ctx = _build_command_context(cmd)
                    _validate_postgres_command_context_or_422(step=cmd.step, tool_kind=cmd.tool.kind, context=ctx)
                    meta = {"command_id": cmd_id, "step": cmd.step, "tool_kind": cmd.tool.kind, "triggered_by": req.name, "trigger_step": req.step, "actionable": True, **(cmd.metadata or {})}
                    ctx = await _store_command_context_if_needed(execution_id=int(cmd.execution_id), step=cmd.step, command_id=cmd_id, context=ctx)
                    _now = datetime.now(timezone.utc)
                    await cur.execute("""
                        INSERT INTO noetl.event (event_id, execution_id, catalog_id, event_type, node_id, node_name, node_type, status, context, meta, parent_event_id, parent_execution_id, command_id, created_at)
                        VALUES (%(event_id)s, %(execution_id)s, %(catalog_id)s, 'command.issued', %(node_id)s, %(node_name)s, %(node_type)s, 'PENDING', %(context)s, %(meta)s, %(parent_event_id)s, %(parent_execution_id)s, %(command_id)s, %(created_at)s)
                    """, {"event_id": new_evt_id, "execution_id": int(cmd.execution_id), "catalog_id": cat_id, "node_id": cmd.step, "node_name": cmd.step, "node_type": cmd.tool.kind, "context": Json(ctx), "meta": Json(meta), "parent_event_id": evt_id, "parent_execution_id": p_exec, "command_id": cmd_id, "created_at": _now})
                    # Dual-write: create the mutable command projection row
                    await cur.execute("""
                        INSERT INTO noetl.command (command_id, event_id, execution_id, catalog_id,
                            parent_execution_id, step_name, tool_kind, status, context,
                            loop_event_id, iter_index, meta, created_at)
                        VALUES (%(command_id)s, %(event_id)s, %(execution_id)s, %(catalog_id)s,
                            %(parent_execution_id)s, %(step_name)s, %(tool_kind)s, 'PENDING',
                            %(context)s, %(loop_event_id)s, %(iter_index)s, %(meta)s, %(created_at)s)
                        ON CONFLICT (command_id) DO NOTHING
                    """, {
                        "command_id": cmd_id,
                        "event_id": new_evt_id,
                        "execution_id": int(cmd.execution_id),
                        "catalog_id": cat_id,
                        "parent_execution_id": p_exec,
                        "step_name": cmd.step,
                        "tool_kind": cmd.tool.kind,
                        "context": Json(ctx),
                        "loop_event_id": meta.get("__loop_epoch_id") or meta.get("loop_event_id"),
                        "iter_index": meta.get("__loop_claimed_index") or meta.get("iter_index"),
                        "meta": Json(meta),
                        "created_at": _now,
                    })
                    command_events.append((int(cmd.execution_id), new_evt_id, cmd_id, cmd.step))
                    supervisor_commands.append((str(cmd.execution_id), cmd_id, cmd.step, int(new_evt_id), dict(meta)))
                await conn.commit()

        for s_exec, s_cmd, s_step, s_evt, s_meta in supervisor_commands:
            await supervise_command_issued(s_exec, s_cmd, s_step, event_id=s_evt, meta=s_meta)
        await _publish_commands_with_recovery(command_events, server_url=server_url)
        
        if req.name == "command.completed" and req.step.lower() != "end":
            try:
                from .run.orchestrator import evaluate_execution
                await evaluate_execution(execution_id=str(req.execution_id), trigger_event_type="command.completed", trigger_event_id=str(evt_id))
            except (ImportError, Exception): pass

        if req.name in {"playbook.completed", "playbook.failed", "workflow.completed", "workflow.failed", "execution.cancelled"}:
            try: await engine.state_store.evict_completed(req.execution_id)
            except Exception: pass
        return EventResponse(status="ok", event_id=evt_id, commands_generated=len(commands))
    except PoolTimeout:
        if engine and commands_generated: await _invalidate_execution_state_cache(req.execution_id, reason="command_issue_pool_timeout", engine=engine)
        raise HTTPException(status_code=503, detail={"code": "pool_saturated"}, headers={"Retry-After": _compute_retry_after()})
    except Exception as e:
        if engine and commands_generated: await _invalidate_execution_state_cache(req.execution_id, reason=f"command_issue_failed:{type(e).__name__}", engine=engine)
        if retry_after := _record_db_unavailable_failure(e, operation="handle_event"):
            raise HTTPException(status_code=503, detail={"code": "db_unavailable"}, headers={"Retry-After": retry_after})
        logger.error(f"handle_event failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))

import json
