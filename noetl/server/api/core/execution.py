import os
from datetime import datetime, timezone
from typing import Any, Optional
from fastapi import APIRouter, HTTPException
from psycopg.rows import dict_row
from psycopg.types.json import Json
from noetl.core.db.pool import get_pool_connection
from noetl.server.api.supervision import supervise_command_issued
from noetl.server.api.event_queries import PENDING_COMMAND_COUNT_SQL
from .core import logger, get_engine
from .models import ExecuteRequest, ExecuteResponse
from .utils import (
    _iso_timestamp, _duration_fields, _compact_status_variables,
)
from .db import _next_snowflake_id
from .recovery import _publish_commands_with_recovery

router = APIRouter()
_STATUS_TERMINAL_EVENT_TYPES = (
    "playbook.completed",
    "workflow.completed",
    "playbook.failed",
    "workflow.failed",
    "execution.cancelled",
    "command.failed",
)
_EXECUTABLE_CATALOG_KINDS = {"playbook", "agent"}


def _normalize_catalog_kind(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    aliases = {
        "playbooks": "playbook",
        "agents": "agent",
    }
    return aliases.get(normalized, normalized) if normalized else None

@router.post("/execute", response_model=ExecuteResponse)
async def execute(req: ExecuteRequest) -> ExecuteResponse:
    from .commands import _build_command_context, _validate_postgres_command_context_or_422, _store_command_context_if_needed
    try:
        engine = get_engine()
        requested_kind = _normalize_catalog_kind(req.resource_kind)
        if requested_kind and requested_kind not in _EXECUTABLE_CATALOG_KINDS:
            raise HTTPException(
                status_code=422,
                detail=f"Catalog kind '{req.resource_kind}' is not executable",
            )
        allowed_kinds = [requested_kind] if requested_kind else sorted(_EXECUTABLE_CATALOG_KINDS)
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                if req.catalog_id:
                    await cur.execute(
                        """
                        SELECT c.path, c.catalog_id, c.kind
                        FROM noetl.catalog c
                        WHERE c.catalog_id = %(catalog_id)s
                          AND lower(c.kind) = ANY(%(allowed_kinds)s)
                        """,
                        {
                            "catalog_id": req.catalog_id,
                            "allowed_kinds": allowed_kinds,
                        },
                    )
                    row = await cur.fetchone()
                    if not row: raise HTTPException(404, f"Executable catalog entry not found: catalog_id={req.catalog_id}")
                    path, catalog_id = row['path'], row['catalog_id']
                else:
                    if req.version is not None:
                        await cur.execute(
                            """
                            SELECT c.catalog_id, c.path
                            FROM noetl.catalog c
                            WHERE c.path = %(path)s
                              AND c.version = %(version)s
                              AND lower(c.kind) = ANY(%(allowed_kinds)s)
                            """,
                            {
                                "path": req.path,
                                "version": req.version,
                                "allowed_kinds": allowed_kinds,
                            },
                        )
                    else:
                        await cur.execute(
                            """
                            SELECT c.catalog_id, c.path
                            FROM noetl.catalog c
                            WHERE c.path = %(path)s
                              AND lower(c.kind) = ANY(%(allowed_kinds)s)
                            ORDER BY c.version DESC
                            LIMIT 1
                            """,
                            {
                                "path": req.path,
                                "allowed_kinds": allowed_kinds,
                            },
                        )
                    row = await cur.fetchone()
                    if not row: raise HTTPException(404, f"Executable catalog entry not found: {req.path}")
                    catalog_id, path = row['catalog_id'], row['path']
        
        execution_id, commands = await engine.start_execution(path, req.payload, catalog_id, req.parent_execution_id)
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("SELECT event_id FROM noetl.event WHERE execution_id = %s AND event_type = 'playbook.initialized' LIMIT 1", (int(execution_id),))
                root_evt_id = (await cur.fetchone() or {}).get('event_id')
                server_url = os.getenv("NOETL_SERVER_URL", "http://noetl.noetl.svc.cluster.local:8082")
                command_events, supervisor_commands = [], []
                for cmd in commands:
                    cmd_id, evt_id = await _next_snowflake_id(cur), await _next_snowflake_id(cur)
                    ctx = _build_command_context(cmd)
                    _validate_postgres_command_context_or_422(step=cmd.step, tool_kind=cmd.tool.kind, context=ctx)
                    meta = {"command_id": cmd_id, "step": cmd.step, "tool_kind": cmd.tool.kind, "max_attempts": cmd.max_attempts or 3, "attempt": 1, "execution_id": str(execution_id), "catalog_id": str(catalog_id), "actionable": True, **(cmd.metadata or {})}
                    ctx = await _store_command_context_if_needed(execution_id=int(execution_id), step=cmd.step, command_id=cmd_id, context=ctx)
                    now = datetime.now(timezone.utc)
                    await cur.execute("""
                        INSERT INTO noetl.event (event_id, execution_id, catalog_id, event_type, node_id, node_name, node_type, status, context, meta, parent_event_id, parent_execution_id, command_id, created_at)
                        VALUES (%(event_id)s, %(execution_id)s, %(catalog_id)s, 'command.issued', %(node_id)s, %(node_name)s, %(node_type)s, 'PENDING', %(context)s, %(meta)s, %(parent_event_id)s, %(parent_execution_id)s, %(command_id)s, %(created_at)s)
                    """, {"event_id": evt_id, "execution_id": int(execution_id), "catalog_id": catalog_id, "node_id": cmd.step, "node_name": cmd.step, "node_type": cmd.tool.kind, "context": Json(ctx), "meta": Json(meta), "parent_event_id": root_evt_id, "parent_execution_id": req.parent_execution_id, "command_id": cmd_id, "created_at": now})
                    await cur.execute("""
                        INSERT INTO noetl.command (
                            command_id, event_id, execution_id, catalog_id, parent_execution_id,
                            step_name, tool_kind, status, context, loop_event_id, iter_index, meta, created_at
                        )
                        VALUES (
                            %(command_id)s, %(event_id)s, %(execution_id)s, %(catalog_id)s, %(parent_execution_id)s,
                            %(step_name)s, %(tool_kind)s, 'PENDING', %(context)s, %(loop_event_id)s, %(iter_index)s, %(meta)s, %(created_at)s
                        )
                        ON CONFLICT (execution_id, command_id) DO NOTHING
                    """, {
                        "command_id": cmd_id,
                        "event_id": evt_id,
                        "execution_id": int(execution_id),
                        "catalog_id": catalog_id,
                        "parent_execution_id": req.parent_execution_id,
                        "step_name": cmd.step,
                        "tool_kind": cmd.tool.kind,
                        "context": Json(ctx),
                        "loop_event_id": meta.get("__loop_epoch_id") or meta.get("loop_event_id"),
                        "iter_index": meta.get("__loop_claimed_index") or meta.get("iter_index"),
                        "meta": Json(meta),
                        "created_at": now,
                    })
                    command_events.append((int(execution_id), evt_id, cmd_id, cmd.step))
                    supervisor_commands.append((str(execution_id), cmd_id, cmd.step, int(evt_id), dict(meta)))
                await conn.commit()
        for s_exec, s_cmd, s_step, s_evt, s_meta in supervisor_commands:
            await supervise_command_issued(s_exec, s_cmd, s_step, event_id=s_evt, meta=s_meta)
        await _publish_commands_with_recovery(command_events, server_url=server_url)
        return ExecuteResponse(execution_id=execution_id, status="started", commands_generated=len(commands))
    except HTTPException: raise
    except Exception as e: logger.error(f"execute failed: {e}", exc_info=True); raise HTTPException(500, str(e))

async def start_execution(req: ExecuteRequest) -> ExecuteResponse:
    return await execute(req)

@router.get("/executions/{execution_id}/status")
async def get_execution_status(execution_id: str, full: bool = False):
    try:
        engine = get_engine(); state = await engine.state_store.load_state(execution_id)
        if not state:
            async with get_pool_connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    try: exec_id_int = int(execution_id)
                    except ValueError: raise HTTPException(404, "Execution not found")
                    await cur.execute("SELECT event_type, node_name, status, created_at FROM noetl.event WHERE execution_id = %s ORDER BY event_id DESC LIMIT 1", (exec_id_int,))
                    latest = await cur.fetchone()
                    if not latest: raise HTTPException(404, "Execution not found")
                    await cur.execute("SELECT created_at FROM noetl.event WHERE execution_id = %s ORDER BY event_id ASC LIMIT 1", (exec_id_int,))
                    first = await cur.fetchone()
                    await cur.execute(
                        """
                        SELECT event_type, node_name, status, created_at
                        FROM noetl.event
                        WHERE execution_id = %s
                          AND event_type = ANY(%s)
                        ORDER BY event_id DESC
                        LIMIT 1
                        """,
                        (exec_id_int, list(_STATUS_TERMINAL_EVENT_TYPES)),
                    )
                    terminal = await cur.fetchone()
                    await cur.execute("SELECT node_name FROM noetl.event WHERE execution_id = %s AND event_type IN ('step.exit', 'loop.done') AND status = 'COMPLETED' ORDER BY event_id ASC", (exec_id_int,))
                    step_rows = await cur.fetchall()
                    pending_row = {"pending_count": 0}
                    if terminal is None and latest["event_type"] == "batch.completed" and latest["status"] == "COMPLETED":
                        await cur.execute(PENDING_COMMAND_COUNT_SQL, {"execution_id": exec_id_int})
                        pending_row = await cur.fetchone()
            completed, failed, inferred = False, False, False
            t_type = terminal["event_type"] if terminal else None
            if t_type in {"playbook.completed", "workflow.completed"}: completed = True
            elif t_type in {"playbook.failed", "workflow.failed", "execution.cancelled"}:
                completed = t_type == "execution.cancelled"; failed = t_type != "execution.cancelled"
            elif latest["node_name"] == "end" and latest["status"] == "COMPLETED" and latest["event_type"] in {"command.completed", "call.done", "step.exit"}:
                completed, inferred = True, True
            elif latest["event_type"] == "batch.completed" and latest["status"] == "COMPLETED" and int((pending_row or {}).get("pending_count", 0) or 0) <= 0:
                completed, inferred = True, True
            if failed: completed = False
            seen = set(); completed_steps = [r["node_name"] for r in (step_rows or []) if r["node_name"] and r["node_name"] not in seen and not r["node_name"].endswith(':task_sequence') and not seen.add(r["node_name"])]
            terminal_time = (terminal or latest).get("created_at") if (terminal or latest) else None
            duration = _duration_fields(
                first.get("created_at") if first else None,
                terminal_time,
                completed or failed,
            )
            return {"execution_id": execution_id, "current_step": latest.get("node_name"), "completed_steps": completed_steps, "failed": failed, "completed": completed, "completion_inferred": inferred, "variables": _compact_status_variables({}), "source": "event_log_fallback", **duration}

        completed, failed, inferred = state.completed, state.failed, False
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                exec_id_int = int(execution_id)
                await cur.execute("SELECT created_at FROM noetl.event WHERE execution_id = %s ORDER BY event_id ASC LIMIT 1", (exec_id_int,))
                first = await cur.fetchone()
                await cur.execute("SELECT event_type, node_name, status, created_at FROM noetl.event WHERE execution_id = %s ORDER BY event_id DESC LIMIT 1", (exec_id_int,))
                latest = await cur.fetchone()
                await cur.execute(
                    """
                    SELECT event_type, node_name, status, created_at
                    FROM noetl.event
                    WHERE execution_id = %s
                      AND event_type = ANY(%s)
                    ORDER BY event_id DESC
                    LIMIT 1
                    """,
                    (exec_id_int, list(_STATUS_TERMINAL_EVENT_TYPES)),
                )
                terminal = await cur.fetchone()
                pending_row = {"pending_count": 0}
                if terminal is None and latest and latest["event_type"] == "batch.completed" and latest["status"] == "COMPLETED":
                    await cur.execute(PENDING_COMMAND_COUNT_SQL, {"execution_id": exec_id_int})
                    pending_row = await cur.fetchone()
        if not completed:
            if state.current_step == "end" and "end" in state.completed_steps and not failed: completed, inferred = True, True
            else:
                t_type = terminal["event_type"] if terminal else None
                if t_type in {"playbook.completed", "workflow.completed"}: completed = True
                elif t_type in {"playbook.failed", "workflow.failed", "execution.cancelled"}:
                    completed = t_type == "execution.cancelled"; failed = t_type != "execution.cancelled"
                elif latest and latest["node_name"] == "end" and latest["status"] == "COMPLETED" and latest["event_type"] in {"command.completed", "call.done", "step.exit"}:
                    completed, inferred = True, True
                elif latest and latest["event_type"] == "batch.completed" and latest["status"] == "COMPLETED" and int((pending_row or {}).get("pending_count", 0) or 0) <= 0:
                    completed, inferred = True, True
        if failed: completed = False
        duration = _duration_fields(
            first.get("created_at") if first else None,
            (terminal or latest).get("created_at") if (terminal or latest) else None,
            completed or failed,
        )
        return {"execution_id": execution_id, "current_step": state.current_step, "completed_steps": list(state.completed_steps), "failed": failed, "completed": completed, "completion_inferred": inferred, "variables": state.variables if full else _compact_status_variables(state.variables), **duration}
    except HTTPException: raise
    except Exception as e: logger.error(f"get_execution_status failed: {e}", exc_info=True); raise HTTPException(500, str(e))
