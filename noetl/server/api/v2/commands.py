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
def _command_input_from_context(context: Any) -> dict[str, Any]:
    """Return canonical command input map from context."""
    if not isinstance(context, dict):
        return {}
    input_map = context.get('input')
    if isinstance(input_map, dict):
        return input_map
    return {}

def _command_input_from_model(cmd: Any) -> dict[str, Any]:
    """Read command input from canonical field."""
    cmd_input = getattr(cmd, 'input', None)
    if isinstance(cmd_input, dict):
        return cmd_input
    return {}

def _build_command_context(cmd: Any) -> dict[str, Any]:
    """Build command context envelope emitted in command.issued events."""
    return {'tool_config': cmd.tool.config, 'input': _command_input_from_model(cmd), 'render_context': cmd.render_context, 'next_targets': cmd.next_targets, 'pipeline': cmd.pipeline, 'spec': cmd.spec.model_dump() if cmd.spec else None}

def _validate_postgres_command_context(*, step: str, tool_kind: str, context: dict[str, Any]) -> None:
    """
    Enforce postgres command contract before command.issued is persisted.

    Postgres execution must include auth and must not pass direct db_* fields.
    """
    if str(tool_kind).lower() != 'postgres':
        return
    tool_config = context.get('tool_config') if isinstance(context, dict) else {}
    command_input = _command_input_from_context(context)
    auth_cfg = tool_config.get('auth') if isinstance(tool_config, dict) else None
    if auth_cfg in (None, '', {}):
        auth_cfg = command_input.get('auth') if isinstance(command_input, dict) else None
    if auth_cfg in (None, '', {}):
        raise ValueError(f"Postgres command for step '{step}' is missing auth in command context. Use tool.auth.")
    forbidden_fields = {'db_host', 'db_port', 'db_user', 'db_password', 'db_name', 'db_conn_string'}
    direct_fields: set[str] = set()
    if isinstance(tool_config, dict):
        direct_fields.update((key for key in forbidden_fields if tool_config.get(key) not in (None, '')))
    if isinstance(command_input, dict):
        direct_fields.update((key for key in forbidden_fields if command_input.get(key) not in (None, '')))
    if direct_fields:
        raise ValueError(f"Postgres command for step '{step}' includes forbidden direct connection fields: {', '.join(sorted(direct_fields))}. Use auth references only.")

def _validate_postgres_command_context_or_422(*, step: str, tool_kind: str, context: dict[str, Any]) -> None:
    try:
        _validate_postgres_command_context(step=step, tool_kind=tool_kind, context=context)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid command context for step '{step}' and tool '{tool_kind}': {exc}") from exc

async def _store_command_context_if_needed(*, execution_id: int, step: str, command_id: str, context: dict[str, Any]) -> dict[str, Any]:
    """
    Externalize oversized command context so claim responses stay bounded.

    Workers resolve the returned ref locally from shared storage when needed.
    """
    try:
        size_bytes = estimate_size(context)
    except Exception:
        size_bytes = _estimate_json_size(context)
    if size_bytes <= _COMMAND_CONTEXT_INLINE_MAX_BYTES:
        return context
    try:
        ref = await default_store.put(execution_id=str(execution_id), name=f'{step}_command_context', data=context, scope=Scope.EXECUTION, source_step=step, correlation={'command_id': command_id, 'kind': 'command_context', 'step': step})
        logger.info('[COMMAND-CONTEXT] Externalized command context execution_id=%s step=%s command_id=%s bytes=%s store=%s', execution_id, step, command_id, size_bytes, ref.store.value)
        return {'kind': ref.kind, 'ref': ref.ref, 'store': ref.store.value, 'scope': ref.scope.value, 'meta': ref.meta.model_dump(mode='json'), 'correlation': ref.correlation}
    except Exception as exc:
        logger.warning('[COMMAND-CONTEXT] Failed to externalize context execution_id=%s step=%s command_id=%s error=%s', execution_id, step, command_id, exc)
        return context

@router.get('/commands/{event_id}')
async def get_command(event_id: int):
    """
    Get command details from command.issued event.
    Workers call this to fetch command config after NATS notification.

    DEPRECATED: Use POST /commands/{event_id}/claim instead for atomic claim+fetch.
    """
    try:
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("\n                    SELECT execution_id, node_name as step, node_type as tool_kind, context, meta\n                    FROM noetl.event\n                    WHERE event_id = %s AND event_type = 'command.issued'\n                ", (event_id,))
                row = await cur.fetchone()
                if not row:
                    raise HTTPException(404, f'command.issued event not found: {event_id}')
                context = row['context'] or {}
                return {'execution_id': row['execution_id'], 'node_id': row['step'], 'node_name': row['step'], 'action': row['tool_kind'], 'context': context, 'meta': row['meta']}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f'get_command failed: {e}', exc_info=True)
        raise HTTPException(500, str(e))

@router.post('/commands/{event_id}/claim', response_model=ClaimResponse)
async def claim_command(event_id: int, req: ClaimRequest):
    """
    Atomically claim a command and return its details.

    Combines claim + fetch into single operation:
    1. Checks if the command is already terminal (command.completed / command.failed /
       command.cancelled) → 409 already_terminal
    2. Checks if the parent execution is already terminal (playbook.completed,
       playbook.failed, workflow.completed, workflow.failed, execution.cancelled)
       → 409 already_terminal
    3. Acquires advisory lock on command_id
    4. Checks if already claimed → 409 active_claim
    5. If not claimed, inserts command.claimed event
    6. Returns command details from command.issued event

    Returns 409 Conflict if:
      - command or execution is already in a terminal state (code: already_terminal)
      - command is being claimed by another worker (code: active_claim)
    Returns 404 if command.issued event not found.
    """
    try:
        _raise_if_db_short_circuit_enabled(operation='claim_command')
        cached_claim = _active_claim_cache_get(event_id)
        if cached_claim and cached_claim.worker_id != req.worker_id:
            raise HTTPException(409, detail={'code': 'active_claim', 'message': f'Command already claimed by {cached_claim.worker_id}', 'worker_id': cached_claim.worker_id, 'claim_policy': 'cache_fast_path'}, headers={'Retry-After': str(max(1, _CLAIM_ACTIVE_RETRY_AFTER_SECONDS))})
        async with get_pool_connection(timeout=_CLAIM_DB_ACQUIRE_TIMEOUT_SECONDS) as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("\n                    SELECT execution_id, catalog_id, node_name as step, node_type as tool_kind,\n                           context, meta\n                    FROM noetl.event\n                    WHERE event_id = %s AND event_type = 'command.issued'\n                ", (event_id,))
                cmd_row = await cur.fetchone()
                _record_db_operation_success()
                if not cmd_row:
                    raise HTTPException(404, f'command.issued event not found: {event_id}')
                execution_id = cmd_row['execution_id']
                catalog_id = cmd_row['catalog_id']
                step = cmd_row['step']
                tool_kind = cmd_row['tool_kind']
                context = cmd_row['context'] or {}
                meta = cmd_row['meta'] or {}
                command_id = meta.get('command_id', f'{execution_id}:{step}:{event_id}')
                await cur.execute(_CLAIM_TERMINAL_LOOKUP_SQL, _command_id_lookup_params(execution_id, command_id))
                terminal_row = await cur.fetchone()
                if terminal_row:
                    _active_claim_cache_invalidate(command_id=command_id, event_id=event_id)
                    raise HTTPException(409, detail={'code': 'already_terminal', 'message': 'Command already reached a terminal state', 'event_type': terminal_row.get('event_type')})
                terminal_execution = await _fetch_execution_terminal_event(cur, execution_id)
                if terminal_execution:
                    _active_claim_cache_invalidate(command_id=command_id, event_id=event_id)
                    raise HTTPException(409, detail={'code': 'already_terminal', 'message': 'Execution already reached a terminal state', 'event_type': terminal_execution.get('event_type')})
                await cur.execute('\n                    SELECT pg_try_advisory_xact_lock(hashtext(%s)::bigint) as lock_acquired\n                ', (command_id,))
                lock_result = await cur.fetchone()
                if not lock_result or not lock_result.get('lock_acquired'):
                    raise HTTPException(409, detail={'code': 'active_claim', 'message': 'Command is being claimed by another worker'}, headers={'Retry-After': str(max(1, _CLAIM_ACTIVE_RETRY_AFTER_SECONDS))})
                await cur.execute(_CLAIM_EXISTING_LOOKUP_SQL, _command_id_lookup_params(execution_id, command_id))
                existing = await cur.fetchone()
                stale_reclaim = False
                reclaimed_from_worker = None
                reclaimed_reason = None
                if existing:
                    existing_event_id = existing.get('event_id')
                    existing_worker = existing.get('worker_id') or (existing.get('meta') or {}).get('worker_id')
                    created_at = existing.get('created_at')
                    claim_age_seconds = 0.0
                    if isinstance(created_at, datetime):
                        created_at_dt = created_at
                        if created_at_dt.tzinfo is None:
                            created_at_dt = created_at_dt.replace(tzinfo=timezone.utc)
                        claim_age_seconds = max(0.0, (datetime.now(created_at_dt.tzinfo) - created_at_dt).total_seconds())
                    if existing_worker and existing_worker != req.worker_id:
                        worker_runtime_status = None
                        worker_heartbeat_age = None
                        try:
                            await cur.execute("\n                                SELECT status, heartbeat\n                                FROM noetl.runtime\n                                WHERE kind = 'worker_pool' AND name = %s\n                                ORDER BY updated_at DESC\n                                LIMIT 1\n                                ", (existing_worker,))
                            runtime_row = await cur.fetchone()
                            if runtime_row:
                                worker_runtime_status = (runtime_row.get('status') or '').lower()
                                heartbeat_ts = runtime_row.get('heartbeat')
                                if isinstance(heartbeat_ts, datetime):
                                    heartbeat_dt = heartbeat_ts
                                    if heartbeat_dt.tzinfo is None:
                                        heartbeat_dt = heartbeat_dt.replace(tzinfo=timezone.utc)
                                    worker_heartbeat_age = max(0.0, (datetime.now(heartbeat_dt.tzinfo) - heartbeat_dt).total_seconds())
                        except Exception:
                            logger.debug('[CLAIM] Runtime status lookup failed for worker=%s', existing_worker, exc_info=True)
                        decision = decide_reclaim_for_existing_claim(existing_worker=existing_worker, requesting_worker=req.worker_id, claim_age_seconds=claim_age_seconds, lease_seconds=_CLAIM_LEASE_SECONDS, worker_runtime_status=worker_runtime_status, worker_heartbeat_age_seconds=worker_heartbeat_age, heartbeat_stale_seconds=_CLAIM_WORKER_HEARTBEAT_STALE_SECONDS, healthy_worker_hard_timeout_seconds=_CLAIM_HEALTHY_WORKER_HARD_TIMEOUT_SECONDS)
                        if decision.reclaim:
                            stale_reclaim = True
                            reclaimed_from_worker = existing_worker
                            reclaimed_reason = decision.reason or 'lease_expired'
                            logger.warning('[CLAIM] Reclaiming command %s from worker=%s age=%.3fs reason=%s (lease=%.3fs heartbeat_age=%.3fs status=%s)', command_id, existing_worker, claim_age_seconds, reclaimed_reason, _CLAIM_LEASE_SECONDS, worker_heartbeat_age or -1.0, worker_runtime_status)
                        else:
                            retry_after = _CLAIM_ACTIVE_RETRY_AFTER_SECONDS
                            if decision.retry_reason == 'lease_active':
                                retry_after = max(1, min(_CLAIM_ACTIVE_RETRY_AFTER_SECONDS, int(max(1.0, _CLAIM_LEASE_SECONDS - claim_age_seconds))))
                            _active_claim_cache_set(event_id, command_id, existing_worker)
                            raise HTTPException(409, detail={'code': 'active_claim', 'message': f'Command already claimed by {existing_worker}', 'worker_id': existing_worker, 'claim_event_id': existing_event_id, 'age_seconds': round(claim_age_seconds, 3), 'lease_seconds': _CLAIM_LEASE_SECONDS, 'hard_timeout_seconds': _CLAIM_HEALTHY_WORKER_HARD_TIMEOUT_SECONDS, 'claim_policy': decision.retry_reason, 'worker_status': worker_runtime_status, 'worker_heartbeat_age_seconds': round(worker_heartbeat_age, 3) if worker_heartbeat_age is not None else None}, headers={'Retry-After': str(retry_after)})
                    if existing_worker and existing_worker == req.worker_id:
                        await cur.execute(_CLAIM_SAME_WORKER_LATEST_LOOKUP_SQL, _command_id_lookup_params(execution_id, command_id))
                        same_worker_latest = await cur.fetchone()
                        latest_event_type = (same_worker_latest or {}).get('event_type')
                        if latest_event_type == 'command.started':
                            _active_claim_cache_set(event_id, command_id, existing_worker)
                            raise HTTPException(409, detail={'code': 'active_claim', 'message': f'Command already running on {existing_worker}', 'worker_id': existing_worker, 'claim_event_id': existing_event_id, 'age_seconds': round(claim_age_seconds, 3), 'lease_seconds': _CLAIM_LEASE_SECONDS, 'hard_timeout_seconds': _CLAIM_HEALTHY_WORKER_HARD_TIMEOUT_SECONDS, 'claim_policy': 'same_worker_running', 'worker_status': 'running'}, headers={'Retry-After': str(_CLAIM_ACTIVE_RETRY_AFTER_SECONDS)})
                    if not stale_reclaim:
                        _active_claim_cache_set(event_id, command_id, req.worker_id)
                        return ClaimResponse(status='ok', event_id=event_id, execution_id=execution_id, node_id=step, node_name=step, action=tool_kind, context=context, meta=meta)
                claim_evt_id = await _next_snowflake_id(cur)
                claim_meta = {'command_id': command_id, 'worker_id': req.worker_id, 'actionable': False, 'informative': True}
                if stale_reclaim:
                    claim_meta['reclaimed'] = True
                    claim_meta['reclaimed_from_worker'] = reclaimed_from_worker
                    if reclaimed_reason:
                        claim_meta['reclaimed_reason'] = reclaimed_reason
                result_obj = _build_reference_only_result(payload={'command_id': command_id}, status='RUNNING')
                await cur.execute('\n                    INSERT INTO noetl.event (\n                        event_id, execution_id, catalog_id, event_type,\n                        node_id, node_name, status, result, meta, worker_id, created_at\n                    )\n                    SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s\n                    WHERE NOT EXISTS (\n                        SELECT 1 FROM noetl.event\n                        WHERE execution_id = %s\n                          AND event_type = ANY(%s)\n                        LIMIT 1\n                    )\n                    RETURNING event_id\n                ', (claim_evt_id, execution_id, catalog_id, 'command.claimed', step, step, 'RUNNING', Json(result_obj), Json(claim_meta), req.worker_id, datetime.now(timezone.utc), execution_id, _EXECUTION_TERMINAL_EVENT_TYPES))
                inserted = await cur.fetchone()
                if not inserted:
                    late_terminal = await _fetch_execution_terminal_event(cur, execution_id)
                    _active_claim_cache_invalidate(command_id=command_id, event_id=event_id)
                    raise HTTPException(409, detail={'code': 'already_terminal', 'message': 'Execution reached a terminal state concurrently', 'event_type': late_terminal.get('event_type') if late_terminal else None})
                await conn.commit()
                _active_claim_cache_set(event_id, command_id, req.worker_id)
                logger.info(f'[CLAIM] Command {command_id} claimed by {req.worker_id} (event_id={claim_evt_id})')
                return ClaimResponse(status='ok', event_id=event_id, execution_id=execution_id, node_id=step, node_name=step, action=tool_kind, context=context, meta=meta)
    except HTTPException:
        raise
    except PoolTimeout:
        retry_after = _compute_retry_after()
        logger.warning('[CLAIM] DB pool saturated for event_id=%s (acquire_timeout=%.3fs) retry_after=%ss', event_id, _CLAIM_DB_ACQUIRE_TIMEOUT_SECONDS, retry_after)
        raise HTTPException(status_code=503, detail={'code': 'pool_saturated', 'message': 'Database temporarily overloaded; retry shortly'}, headers={'Retry-After': retry_after})
    except Exception as e:
        retry_after = _record_db_unavailable_failure(e, operation='claim_command')
        if retry_after is not None:
            raise HTTPException(status_code=503, detail={'code': 'db_unavailable', 'message': 'Database temporarily unavailable; retry shortly'}, headers={'Retry-After': retry_after})
        logger.error(f'claim_command failed with unhandled error: {e}', exc_info=True)
        raise HTTPException(status_code=500, detail={'code': 'internal_error', 'message': str(e)})
        logger.error(f'claim_command failed: {e}', exc_info=True)
        raise HTTPException(500, str(e))

__all__ = ['_command_input_from_context', '_command_input_from_model', '_build_command_context', '_validate_postgres_command_context', '_validate_postgres_command_context_or_422', '_store_command_context_if_needed', 'get_command', 'claim_command']
