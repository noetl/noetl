import os
import json
import time
import asyncio
import heapq
import math
from dataclasses import dataclass
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from typing import Any, Optional, Literal
from datetime import datetime, timezone
from psycopg.types.json import Json
from psycopg.rows import dict_row
from psycopg_pool import PoolTimeout
from noetl.core.dsl.v2.models import Event
from noetl.core.dsl.v2.engine import ControlFlowEngine, PlaybookRepo, StateStore
from noetl.core.db.pool import get_pool_connection, get_server_pool_stats
from noetl.core.messaging import NATSCommandPublisher
from noetl.core.storage import Scope, default_store, estimate_size
from noetl.claim_policy import decide_reclaim_for_existing_claim
from noetl.server.api.event_queries import PENDING_COMMAND_COUNT_SQL
from noetl.server.api.supervision import supervise_command_issued, supervise_persisted_event
from noetl.core.logger import setup_logger

from .core import *
from .models import *
from .utils import *
from .db import *
from .recovery import *
from .commands import *
@router.post('/execute', response_model=ExecuteResponse)
async def execute(req: ExecuteRequest) -> ExecuteResponse:
    """
    Start playbook execution.

    Creates playbook.initialized event, emits command.issued events.
    All state in event table - result column is reference-only (status + optional reference/context).
    """
    try:
        engine = get_engine()
        logger.debug(f'[EXECUTE] Request: path={req.path}, catalog_id={req.catalog_id}, version={req.version}')
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                if req.catalog_id:
                    await cur.execute('SELECT path, catalog_id FROM noetl.catalog WHERE catalog_id = %s', (req.catalog_id,))
                    row = await cur.fetchone()
                    if not row:
                        raise HTTPException(404, f'Playbook not found: catalog_id={req.catalog_id}')
                    path, catalog_id = (row['path'], row['catalog_id'])
                else:
                    if req.version is not None:
                        await cur.execute('SELECT catalog_id, path, version FROM noetl.catalog WHERE path = %s AND version = %s', (req.path, req.version))
                        row = await cur.fetchone()
                        if not row:
                            raise HTTPException(404, f'Playbook not found: {req.path} v{req.version}')
                    else:
                        await cur.execute('SELECT catalog_id, path, version FROM noetl.catalog WHERE path = %s ORDER BY version DESC LIMIT 1', (req.path,))
                        row = await cur.fetchone()
                        if not row:
                            raise HTTPException(404, f'Playbook not found: {req.path}')
                    catalog_id, path = (row['catalog_id'], row['path'])
                    logger.debug(f'[EXECUTE] Resolved playbook: {path} v{row.get('version', '?')} -> catalog_id={catalog_id}')
        execution_id, commands = await engine.start_execution(path, req.payload, catalog_id, req.parent_execution_id)
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("SELECT event_id FROM noetl.event WHERE execution_id = %s AND event_type = 'playbook.initialized' LIMIT 1", (int(execution_id),))
                row = await cur.fetchone()
                root_event_id = row['event_id'] if row else None
        server_url = os.getenv('NOETL_SERVER_URL', 'http://noetl.noetl.svc.cluster.local:8082')
        command_events = []
        supervisor_commands: list[tuple[str, str, str, int, dict[str, Any]]] = []
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                for cmd in commands:
                    cmd_suffix = await _next_snowflake_id(cur)
                    cmd_id = f'{execution_id}:{cmd.step}:{cmd_suffix}'
                    evt_id = await _next_snowflake_id(cur)
                    context = _build_command_context(cmd)
                    _validate_postgres_command_context_or_422(step=cmd.step, tool_kind=cmd.tool.kind, context=context)
                    meta = {'command_id': cmd_id, 'step': cmd.step, 'tool_kind': cmd.tool.kind, 'max_attempts': cmd.max_attempts or 3, 'attempt': 1, 'execution_id': str(execution_id), 'catalog_id': str(catalog_id)}
                    if cmd.metadata:
                        meta.update({k: v for k, v in cmd.metadata.items() if v is not None})
                    meta['actionable'] = True
                    context = await _store_command_context_if_needed(execution_id=int(execution_id), step=cmd.step, command_id=cmd_id, context=context)
                    await cur.execute('\n                        INSERT INTO noetl.event (\n                            event_id, execution_id, catalog_id, event_type,\n                            node_id, node_name, node_type, status,\n                            context, meta, parent_event_id, parent_execution_id,\n                            created_at\n                        ) VALUES (\n                            %(event_id)s, %(execution_id)s, %(catalog_id)s, %(event_type)s,\n                            %(node_id)s, %(node_name)s, %(node_type)s, %(status)s,\n                            %(context)s, %(meta)s, %(parent_event_id)s, %(parent_execution_id)s,\n                            %(created_at)s\n                        )\n                    ', {'event_id': evt_id, 'execution_id': int(execution_id), 'catalog_id': catalog_id, 'event_type': 'command.issued', 'node_id': cmd.step, 'node_name': cmd.step, 'node_type': cmd.tool.kind, 'status': 'PENDING', 'context': Json(context), 'meta': Json(meta), 'parent_event_id': root_event_id, 'parent_execution_id': req.parent_execution_id, 'created_at': datetime.now(timezone.utc)})
                    command_events.append((int(execution_id), evt_id, cmd_id, cmd.step))
                    supervisor_commands.append((str(execution_id), cmd_id, cmd.step, int(evt_id), dict(meta)))
            await conn.commit()
        for supervisor_execution_id, supervisor_command_id, supervisor_step, supervisor_event_id, supervisor_meta in supervisor_commands:
            await supervise_command_issued(supervisor_execution_id, supervisor_command_id, supervisor_step, event_id=supervisor_event_id, meta=supervisor_meta)
        await _publish_commands_with_recovery(command_events, server_url=server_url)
        return ExecuteResponse(execution_id=execution_id, status='started', commands_generated=len(commands))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f'execute failed: {e}', exc_info=True)
        raise HTTPException(500, str(e))

async def start_execution(req: ExecuteRequest) -> ExecuteResponse:
    """
    Start playbook execution - function wrapper for endpoint.
    Used by /api/run/playbook endpoint for backward compatibility.
    """
    return await execute(req)

@router.get('/executions/{execution_id}/status')
async def get_execution_status(execution_id: str, full: bool=False):
    """Get execution status from engine state."""
    try:
        engine = get_engine()
        state = await engine.state_store.load_state(execution_id)
        if not state:
            async with get_pool_connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    try:
                        exec_id_int = int(execution_id)
                    except ValueError:
                        raise HTTPException(404, 'Execution not found')
                    await cur.execute('\n                        SELECT event_type, node_name, status, created_at\n                        FROM noetl.event\n                        WHERE execution_id = %s\n                        ORDER BY event_id DESC\n                        LIMIT 1\n                    ', (exec_id_int,))
                    latest_event = await cur.fetchone()
                    if not latest_event:
                        raise HTTPException(404, 'Execution not found')
                    await cur.execute('\n                        SELECT created_at\n                        FROM noetl.event\n                        WHERE execution_id = %s\n                        ORDER BY event_id ASC\n                        LIMIT 1\n                    ', (exec_id_int,))
                    first_event = await cur.fetchone()
                    await cur.execute("\n                        SELECT event_type\n                        FROM noetl.event\n                        WHERE execution_id = %s\n                          AND event_type IN (\n                            'playbook.completed',\n                            'workflow.completed',\n                            'playbook.failed',\n                            'workflow.failed',\n                            'execution.cancelled'\n                          )\n                        ORDER BY event_id DESC\n                        LIMIT 1\n                    ", (exec_id_int,))
                    terminal_event = await cur.fetchone()
                    await cur.execute("\n                        SELECT node_name\n                        FROM noetl.event\n                        WHERE execution_id = %s\n                          AND event_type IN ('step.exit', 'loop.done')\n                          AND status = 'COMPLETED'\n                        ORDER BY event_id ASC\n                    ", (exec_id_int,))
                    step_rows = await cur.fetchall()
                    pending_row = {'pending_count': 0}
                    should_check_pending_commands = terminal_event is None and latest_event['event_type'] == 'batch.completed' and (latest_event['status'] == 'COMPLETED')
                    if should_check_pending_commands:
                        await cur.execute(_PENDING_COMMAND_COUNT_SQL, {'execution_id': exec_id_int})
                        pending_row = await cur.fetchone()
            terminal_complete_events = {'playbook.completed', 'workflow.completed'}
            terminal_failed_events = {'playbook.failed', 'workflow.failed', 'execution.cancelled'}
            pending_count = int((pending_row or {}).get('pending_count', 0))
            completed = False
            failed = False
            completion_inferred = False
            terminal_type = terminal_event['event_type'] if terminal_event else None
            if terminal_type in terminal_complete_events:
                completed = True
                failed = False
                completion_inferred = False
            elif terminal_type in terminal_failed_events:
                completed = terminal_type == 'execution.cancelled'
                failed = terminal_type in {'playbook.failed', 'workflow.failed'}
                completion_inferred = False
            elif latest_event['node_name'] == 'end' and latest_event['status'] == 'COMPLETED' and (latest_event['event_type'] in {'command.completed', 'call.done', 'step.exit'}):
                completed = True
                failed = False
                completion_inferred = True
            if failed:
                completed = False
            completed_steps: list[str] = []
            seen_steps: set[str] = set()
            for row in step_rows or []:
                step_name = row.get('node_name')
                if not step_name or step_name in seen_steps or step_name.endswith(':task_sequence'):
                    continue
                seen_steps.add(step_name)
                completed_steps.append(step_name)
            fallback_variables: dict[str, Any] = {}
            duration = _duration_fields(first_event.get('created_at') if first_event else None, latest_event.get('created_at') if latest_event else None, completed)
            return {'execution_id': execution_id, 'current_step': latest_event.get('node_name'), 'completed_steps': completed_steps, 'failed': failed, 'completed': completed, 'completion_inferred': completion_inferred, 'variables': fallback_variables if full else _compact_status_variables(fallback_variables), 'source': 'event_log_fallback', **duration}
        completed = state.completed
        failed = state.failed
        completion_inferred = False
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute('\n                    SELECT created_at\n                    FROM noetl.event\n                    WHERE execution_id = %s\n                    ORDER BY event_id ASC\n                    LIMIT 1\n                ', (int(execution_id),))
                first_event = await cur.fetchone()
                await cur.execute('\n                    SELECT event_type, node_name, status, created_at\n                    FROM noetl.event\n                    WHERE execution_id = %s\n                    ORDER BY event_id DESC\n                    LIMIT 1\n                ', (int(execution_id),))
                latest_event = await cur.fetchone()
                await cur.execute("\n                    SELECT event_type, node_name, status, created_at\n                    FROM noetl.event\n                    WHERE execution_id = %s\n                      AND event_type IN (\n                        'playbook.completed',\n                        'workflow.completed',\n                        'playbook.failed',\n                        'workflow.failed',\n                        'execution.cancelled'\n                      )\n                    ORDER BY event_id DESC\n                    LIMIT 1\n                ", (int(execution_id),))
                terminal_event = await cur.fetchone()
                pending_row = {'pending_count': 0}
                should_check_pending_commands = terminal_event is None and latest_event is not None and (latest_event['event_type'] == 'batch.completed') and (latest_event['status'] == 'COMPLETED')
                if should_check_pending_commands:
                    await cur.execute(_PENDING_COMMAND_COUNT_SQL, {'execution_id': int(execution_id)})
                    pending_row = await cur.fetchone()
        if not completed:
            if state.current_step == 'end' and 'end' in state.completed_steps and (not failed):
                completed = True
                completion_inferred = True
            else:
                terminal_complete_events = {'playbook.completed', 'workflow.completed'}
                terminal_failed_events = {'playbook.failed', 'workflow.failed', 'execution.cancelled'}
                terminal_type = terminal_event['event_type'] if terminal_event else None
                pending_count = int((pending_row or {}).get('pending_count', 0))
                if terminal_type in terminal_complete_events:
                    completed = True
                    completion_inferred = False
                elif terminal_type in terminal_failed_events:
                    completed = terminal_type == 'execution.cancelled'
                    failed = terminal_type in {'playbook.failed', 'workflow.failed'}
                    completion_inferred = False
                elif latest_event and (latest_event['node_name'] == 'end' and latest_event['status'] == 'COMPLETED' and (latest_event['event_type'] in {'command.completed', 'call.done', 'step.exit'})):
                    completed = True
                    completion_inferred = True
        if failed:
            completed = False
        duration_anchor = terminal_event or latest_event
        duration = _duration_fields(first_event.get('created_at') if first_event else None, duration_anchor.get('created_at') if duration_anchor else None, completed)
        return {'execution_id': execution_id, 'current_step': state.current_step, 'completed_steps': list(state.completed_steps), 'failed': failed, 'completed': completed, 'completion_inferred': completion_inferred, 'variables': state.variables if full else _compact_status_variables(state.variables), **duration}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f'get_execution_status failed: {e}', exc_info=True)
        raise HTTPException(500, str(e))

__all__ = ['execute', 'start_execution', 'get_execution_status']
