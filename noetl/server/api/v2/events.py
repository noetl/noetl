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
from .cache import *
from .db import *
from .recovery import *
from .commands import *
@router.post('/events', response_model=EventResponse)
async def handle_event(req: EventRequest) -> EventResponse:
    """
    Handle worker event.
    
    Worker reports completion with result (inline or ref).
    Engine evaluates case/when/then and generates next commands.
    
    CRITICAL: Only process through engine for events that drive workflow:
    - step.exit: Step completed, evaluate case rules and generate next commands
    - call.done: Action completed, may trigger case rules
    - call.error: Action failed, may trigger error handling
    - command.failed: Command-level failure, must emit terminal failure lifecycle if unhandled
    - loop.item/loop.done: Loop iteration events
    
    Skip engine for administrative events:
    - command.claimed: Just persist, don't process
    - command.heartbeat: lease/liveness refresh, don't process
    - command.started: Just persist, don't process
    - command.completed: Already processed by worker
    - step.enter: Just marks step started
    """
    engine: Optional[ControlFlowEngine] = None
    commands_generated = False
    try:
        _raise_if_db_short_circuit_enabled(operation='handle_event')
        engine = get_engine()
        skip_engine_events = {'command.claimed', 'command.heartbeat', 'command.started', 'command.completed', 'step.enter'}
        if req.name == 'command.claimed':
            try:
                _validate_reference_only_payload(req.payload)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f"Invalid reference-only event payload for step '{req.step}' event '{req.name}': {exc}") from exc
            command_id = req.payload.get('command_id') or (req.meta or {}).get('command_id')
            if command_id:
                async with get_pool_connection() as conn:
                    async with conn.cursor(row_factory=dict_row) as cur:
                        evt_id = await _next_snowflake_id(cur)
                        await cur.execute('\n                            SELECT pg_try_advisory_xact_lock(hashtext(%s)::bigint) as lock_acquired\n                        ', (command_id,))
                        lock_result = await cur.fetchone()
                        if not lock_result or not lock_result.get('lock_acquired'):
                            logger.warning(f'[CLAIM-REJECT] Command {command_id} lock held by another worker, rejecting claim from {req.worker_id}')
                            raise HTTPException(409, f'Command already being claimed by another worker')
                        await cur.execute(_HANDLE_EVENT_CLAIMED_LOOKUP_SQL, _command_id_lookup_params(int(req.execution_id), command_id))
                        existing = await cur.fetchone()
                        if existing:
                            existing_worker = existing.get('worker_id') or (existing.get('meta') or {}).get('worker_id')
                            if existing_worker and existing_worker != req.worker_id:
                                logger.warning(f'[CLAIM-REJECT] Command {command_id} already claimed by {existing_worker}, rejecting claim from {req.worker_id}')
                                raise HTTPException(409, f'Command already claimed by {existing_worker}')
                            else:
                                logger.info(f'[CLAIM-IDEMPOTENT] Command {command_id} already claimed by SAME worker {req.worker_id}, returning success')
                                return EventResponse(status='ok', event_id=0, commands_generated=0)
                        await cur.execute('SELECT catalog_id FROM noetl.event WHERE execution_id = %s LIMIT 1', (int(req.execution_id),))
                        row = await cur.fetchone()
                        catalog_id = row['catalog_id'] if row else None
                        meta_obj = dict(req.meta or {})
                        meta_obj['actionable'] = req.actionable
                        meta_obj['informative'] = req.informative
                        meta_obj['command_id'] = command_id
                        if req.worker_id:
                            meta_obj['worker_id'] = req.worker_id
                        result_obj = _build_reference_only_result(payload=req.payload, status='RUNNING')
                        await cur.execute('\n                            INSERT INTO noetl.event (\n                                event_id, execution_id, catalog_id, event_type,\n                                node_id, node_name, status, result, meta, worker_id, created_at\n                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)\n                        ', (evt_id, int(req.execution_id), catalog_id, req.name, req.step, req.step, 'RUNNING', Json(result_obj), Json(meta_obj), req.worker_id, datetime.now(timezone.utc)))
                        await conn.commit()
                        _record_db_operation_success()
                        logger.info(f'[CLAIM-SUCCESS] Command {command_id} claimed by worker {req.worker_id}')
                        return EventResponse(status='ok', event_id=evt_id, commands_generated=0)
        status = _status_from_event_name(req.name)
        try:
            _validate_reference_only_payload(req.payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid reference-only event payload for step '{req.step}' event '{req.name}': {exc}") from exc
        result_obj = _build_reference_only_result(payload=req.payload, status=status)
        error_text = _extract_event_error(req.payload)
        command_id = _extract_event_command_id(req)
        event_meta = dict(req.meta or {})
        event_meta['actionable'] = req.actionable
        event_meta['informative'] = req.informative
        if req.worker_id:
            event_meta['worker_id'] = req.worker_id
        if command_id:
            event_meta['command_id'] = command_id
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute('SELECT catalog_id FROM noetl.event WHERE execution_id = %s LIMIT 1', (int(req.execution_id),))
                row = await cur.fetchone()
                catalog_id = row['catalog_id'] if row else None
                if command_id and req.name in _COMMAND_EVENT_DEDUPE_TYPES:
                    await cur.execute("\n                        SELECT event_id\n                        FROM noetl.event\n                        WHERE execution_id = %s\n                          AND event_type = %s\n                          AND node_name = %s\n                          AND meta ? 'command_id'\n                          AND meta->>'command_id' = %s\n                        ORDER BY event_id DESC\n                        LIMIT 1\n                        ", (int(req.execution_id), req.name, req.step, command_id))
                    duplicate_row = await cur.fetchone()
                    if duplicate_row:
                        duplicate_event_id = int(duplicate_row.get('event_id'))
                        logger.warning('[EVENT-DEDUPE] Ignoring duplicate event %s for execution=%s step=%s command_id=%s existing_event_id=%s', req.name, req.execution_id, req.step, command_id, duplicate_event_id)
                        if req.name in {'command.completed', 'command.failed'}:
                            _active_claim_cache_invalidate(command_id=command_id)
                        return EventResponse(status='ok', event_id=duplicate_event_id, commands_generated=0)
                evt_id = await _next_snowflake_id(cur)
                event_meta['persisted_event_id'] = str(evt_id)
                await cur.execute('\n                    INSERT INTO noetl.event (\n                        event_id, execution_id, catalog_id, event_type,\n                        node_id, node_name, status, result, meta, error, created_at\n                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)\n                ', (evt_id, int(req.execution_id), catalog_id, req.name, req.step, req.step, status, Json(result_obj), Json(event_meta), error_text, datetime.now(timezone.utc)))
                await conn.commit()
                _record_db_operation_success()
        await supervise_persisted_event(req.execution_id, req.step, req.name, req.payload, event_meta, event_id=int(evt_id))
        if req.name in {'command.completed', 'command.failed'}:
            if command_id:
                _active_claim_cache_invalidate(command_id=command_id)
        event = Event(execution_id=req.execution_id, step=req.step, name=req.name, payload=req.payload, meta=event_meta, timestamp=datetime.now(timezone.utc), worker_id=req.worker_id, attempt=event_meta.get('attempt', 1))
        commands = []
        if req.name not in skip_engine_events:
            async with get_pool_connection() as engine_conn:
                async with engine_conn.transaction():
                    async with engine_conn.cursor() as cur:
                        await cur.execute('SELECT pg_advisory_xact_lock(%s)', (int(req.execution_id),))
                    commands = await engine.handle_event(event, conn=engine_conn, already_persisted=True)
            commands_generated = bool(commands)
            logger.debug(f'[ENGINE] Processed {req.name} for step {req.step}, generated {len(commands)} commands')
        else:
            logger.debug(f'[ENGINE] Skipped engine for administrative event {req.name}')
        server_url = os.getenv('NOETL_SERVER_URL', 'http://noetl.noetl.svc.cluster.local:8082')
        command_events = []
        supervisor_commands: list[tuple[str, str, str, int, dict[str, Any]]] = []
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                for cmd in commands:
                    await cur.execute('SELECT catalog_id, parent_execution_id FROM noetl.event WHERE execution_id = %s LIMIT 1', (int(cmd.execution_id),))
                    row = await cur.fetchone()
                    cat_id = row['catalog_id'] if row else catalog_id
                    parent_exec = row['parent_execution_id'] if row else None
                    cmd_suffix = await _next_snowflake_id(cur)
                    cmd_id = f'{cmd.execution_id}:{cmd.step}:{cmd_suffix}'
                    new_evt_id = await _next_snowflake_id(cur)
                    context = _build_command_context(cmd)
                    _validate_postgres_command_context_or_422(step=cmd.step, tool_kind=cmd.tool.kind, context=context)
                    meta = {'command_id': cmd_id, 'step': cmd.step, 'tool_kind': cmd.tool.kind, 'triggered_by': req.name, 'trigger_step': req.step, 'actionable': True}
                    if cmd.metadata:
                        meta.update({k: v for k, v in cmd.metadata.items() if v is not None})
                    context = await _store_command_context_if_needed(execution_id=int(cmd.execution_id), step=cmd.step, command_id=cmd_id, context=context)
                    await cur.execute('\n                        INSERT INTO noetl.event (\n                            event_id, execution_id, catalog_id, event_type,\n                            node_id, node_name, node_type, status,\n                            context, meta, parent_event_id, parent_execution_id,\n                            created_at\n                        ) VALUES (\n                            %(event_id)s, %(execution_id)s, %(catalog_id)s, %(event_type)s,\n                            %(node_id)s, %(node_name)s, %(node_type)s, %(status)s,\n                            %(context)s, %(meta)s, %(parent_event_id)s, %(parent_execution_id)s,\n                            %(created_at)s\n                        )\n                    ', {'event_id': new_evt_id, 'execution_id': int(cmd.execution_id), 'catalog_id': cat_id, 'event_type': 'command.issued', 'node_id': cmd.step, 'node_name': cmd.step, 'node_type': cmd.tool.kind, 'status': 'PENDING', 'context': Json(context), 'meta': Json(meta), 'parent_event_id': evt_id, 'parent_execution_id': parent_exec, 'created_at': datetime.now(timezone.utc)})
                    command_events.append((int(cmd.execution_id), new_evt_id, cmd_id, cmd.step))
                    supervisor_commands.append((str(cmd.execution_id), cmd_id, cmd.step, int(new_evt_id), dict(meta)))
                await conn.commit()
        for supervisor_execution_id, supervisor_command_id, supervisor_step, supervisor_event_id, supervisor_meta in supervisor_commands:
            await supervise_command_issued(supervisor_execution_id, supervisor_command_id, supervisor_step, event_id=supervisor_event_id, meta=supervisor_meta)
        await _publish_commands_with_recovery(command_events, server_url=server_url)
        if req.name == 'command.completed' and req.step.lower() != 'end':
            try:
                from .run.orchestrator import evaluate_execution
                await evaluate_execution(execution_id=str(req.execution_id), trigger_event_type='command.completed', trigger_event_id=str(evt_id))
            except ImportError:
                logger.debug('Orchestrator module not available, skipping for command.completed')
            except Exception as e:
                logger.warning(f'Orchestrator error: {e}')
        terminal_events = {'playbook.completed', 'playbook.failed', 'workflow.completed', 'workflow.failed', 'execution.cancelled'}
        if req.name in terminal_events:
            try:
                await engine.state_store.evict_completed(req.execution_id)
                logger.debug(f'Evicted execution {req.execution_id} from cache after {req.name}')
            except Exception as e:
                logger.warning(f'Failed to evict execution {req.execution_id} from cache: {e}')
        return EventResponse(status='ok', event_id=evt_id, commands_generated=len(commands))
    except PoolTimeout:
        if engine is not None and commands_generated:
            await _invalidate_execution_state_cache(req.execution_id, reason='command_issue_pool_timeout', engine=engine)
        retry_after = _compute_retry_after()
        logger.warning('[EVENTS] DB pool saturated while persisting %s for step %s retry_after=%ss', req.name, req.step, retry_after)
        raise HTTPException(status_code=503, detail={'code': 'pool_saturated', 'message': 'Database temporarily overloaded; retry shortly'}, headers={'Retry-After': retry_after})
    except Exception as e:
        if engine is not None and commands_generated:
            await _invalidate_execution_state_cache(req.execution_id, reason=f'command_issue_failed:{type(e).__name__}', engine=engine)
        retry_after = _record_db_unavailable_failure(e, operation='handle_event')
        if retry_after is not None:
            raise HTTPException(status_code=503, detail={'code': 'db_unavailable', 'message': 'Database temporarily unavailable; retry shortly'}, headers={'Retry-After': retry_after})
        logger.error(f'handle_event failed: {e}', exc_info=True)
        raise HTTPException(500, str(e))

__all__ = ['handle_event']
