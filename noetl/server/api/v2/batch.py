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
from .metrics import *
from .commands import *
from .recovery import *
def _get_batch_acceptor_lock() -> asyncio.Lock:
    global _batch_acceptor_lock
    if _batch_acceptor_lock is None:
        _batch_acceptor_lock = asyncio.Lock()
    return _batch_acceptor_lock

def _has_live_batch_workers() -> bool:
    return any((not task.done() for task in _batch_accept_workers_tasks))

async def ensure_batch_acceptor_started() -> bool:
    """Ensure in-process batch acceptor queue and workers are running."""
    global _batch_accept_queue
    if _BATCH_ACCEPT_WORKERS <= 0:
        return False
    lock = _get_batch_acceptor_lock()
    async with lock:
        if _batch_accept_queue is None:
            _batch_accept_queue = asyncio.Queue(maxsize=_BATCH_ACCEPT_QUEUE_MAXSIZE)
        _batch_accept_workers_tasks[:] = [task for task in _batch_accept_workers_tasks if not task.done()]
        while len(_batch_accept_workers_tasks) < _BATCH_ACCEPT_WORKERS:
            worker_idx = len(_batch_accept_workers_tasks) + 1
            task = asyncio.create_task(_batch_accept_worker_loop(worker_idx), name=f'batch-acceptor-{worker_idx}')
            _batch_accept_workers_tasks.append(task)
        return _has_live_batch_workers()

async def shutdown_batch_acceptor() -> None:
    """Stop in-process batch acceptor workers."""
    lock = _get_batch_acceptor_lock()
    async with lock:
        if not _batch_accept_workers_tasks:
            return
        tasks = list(_batch_accept_workers_tasks)
        _batch_accept_workers_tasks.clear()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

async def _persist_batch_status_event(execution_id: int, catalog_id: Optional[int], request_id: str, worker_id: Optional[str], idempotency_key: Optional[str], event_type: str, status: str, payload: dict[str, Any], error: Optional[str]=None) -> None:
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            evt_id = await _next_snowflake_id(cur)
            meta_obj: dict[str, Any] = {'batch_request_id': request_id, 'actionable': False, 'informative': True}
            if worker_id:
                meta_obj['worker_id'] = worker_id
            if idempotency_key:
                meta_obj['idempotency_key'] = idempotency_key
            await cur.execute('\n                INSERT INTO noetl.event (\n                    event_id, execution_id, catalog_id, event_type,\n                    node_id, node_name, status, result, meta, worker_id, error, created_at\n                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)\n                ', (evt_id, execution_id, catalog_id, event_type, 'events.batch', 'events.batch', status, Json(_build_reference_only_result(payload=payload, status=status)), Json(meta_obj), worker_id, error, datetime.now(timezone.utc)))
            await conn.commit()

def _build_batch_error(code: str, message: str, request_id: Optional[str]=None) -> dict[str, Any]:
    detail: dict[str, Any] = {'code': code, 'message': message}
    if request_id:
        detail['request_id'] = request_id
    return detail

async def _persist_batch_failed_event(job: _BatchAcceptJob, code: str, message: str) -> None:
    try:
        await _persist_batch_status_event(execution_id=job.execution_id, catalog_id=job.catalog_id, request_id=job.request_id, worker_id=job.worker_id, idempotency_key=job.idempotency_key, event_type='batch.failed', status='FAILED', payload={'request_id': job.request_id, 'error_code': code, 'message': message}, error=message)
    except Exception as persist_error:
        logger.error('[BATCH-EVENTS] Failed to persist batch.failed request_id=%s code=%s: %s', job.request_id, code, persist_error, exc_info=True)

async def _persist_batch_acceptance(req: BatchEventRequest, idempotency_key: Optional[str]) -> _BatchAcceptanceResult:
    skip_engine_events = {'command.claimed', 'command.heartbeat', 'command.started', 'command.completed', 'step.enter'}
    execution_id = int(req.execution_id)
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute('SELECT catalog_id FROM noetl.event WHERE execution_id = %s LIMIT 1', (execution_id,))
            row = await cur.fetchone()
            catalog_id = row['catalog_id'] if row else None
            if idempotency_key:
                await cur.execute("\n                    SELECT meta, result\n                    FROM noetl.event\n                    WHERE execution_id = %s\n                      AND event_type = 'batch.accepted'\n                      AND meta->>'idempotency_key' = %s\n                    ORDER BY event_id DESC\n                    LIMIT 1\n                    ", (execution_id, idempotency_key))
                existing = await cur.fetchone()
                if existing:
                    existing_meta = existing.get('meta') or {}
                    existing_result = existing.get('result') or {}
                    existing_context = existing_result.get('context') if isinstance(existing_result, dict) else {}
                    request_id = str(existing_meta.get('batch_request_id') or existing_context.get('request_id'))
                    existing_event_ids = existing_context.get('event_ids') or []
                    if request_id:
                        noop_job = _BatchAcceptJob(request_id=request_id, execution_id=execution_id, catalog_id=catalog_id, worker_id=req.worker_id, idempotency_key=idempotency_key, events=[], last_actionable_event=None, last_actionable_evt_id=None, accepted_event_id=0, accepted_at_monotonic=time.perf_counter())
                        return _BatchAcceptanceResult(job=noop_job, event_ids=[int(evt_id) for evt_id in existing_event_ids if isinstance(evt_id, int)], duplicate=True)
            request_id = str(await _next_snowflake_id(cur))
            accepted_event_id = await _next_snowflake_id(cur)
            event_ids: list[int] = []
            last_actionable_event: Optional[Event] = None
            last_actionable_evt_id: Optional[int] = None
            terminal_command_ids: set[str] = set()
            for item in req.events:
                try:
                    _validate_reference_only_payload(item.payload)
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail=f"Invalid reference-only batch event payload for step '{item.step}' event '{item.name}': {exc}") from exc
                evt_id = await _next_snowflake_id(cur)
                event_ids.append(evt_id)
                meta_obj: dict[str, Any] = {'actionable': item.actionable, 'informative': item.informative, 'batch_request_id': request_id, 'persisted_event_id': str(evt_id)}
                if req.worker_id:
                    meta_obj['worker_id'] = req.worker_id
                if idempotency_key:
                    meta_obj['idempotency_key'] = idempotency_key
                item_command_id = _extract_command_id_from_payload(item.payload)
                if item_command_id:
                    meta_obj['command_id'] = item_command_id
                await cur.execute('\n                    INSERT INTO noetl.event (\n                        event_id, execution_id, catalog_id, event_type,\n                        node_id, node_name, status, result, meta, worker_id, error, created_at\n                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)\n                    ', (evt_id, execution_id, catalog_id, item.name, item.step, item.step, _status_from_event_name(item.name), Json(_build_reference_only_result(payload=item.payload, status=_status_from_event_name(item.name))), Json(meta_obj), req.worker_id, _extract_event_error(item.payload), datetime.now(timezone.utc)))
                if item_command_id and item.name in _COMMAND_TERMINAL_EVENT_TYPES:
                    terminal_command_ids.add(item_command_id)
                if item.actionable and item.name not in skip_engine_events:
                    last_actionable_event = Event(execution_id=req.execution_id, step=item.step, name=item.name, payload=item.payload, meta=meta_obj, timestamp=datetime.now(timezone.utc), worker_id=req.worker_id)
                    last_actionable_evt_id = evt_id
            accepted_meta: dict[str, Any] = {'batch_request_id': request_id, 'actionable': False, 'informative': True, 'event_count': len(req.events)}
            if req.worker_id:
                accepted_meta['worker_id'] = req.worker_id
            if idempotency_key:
                accepted_meta['idempotency_key'] = idempotency_key
            if last_actionable_evt_id is not None:
                accepted_meta['last_actionable_event_id'] = str(last_actionable_evt_id)
            await cur.execute('\n                INSERT INTO noetl.event (\n                    event_id, execution_id, catalog_id, event_type,\n                    node_id, node_name, status, result, meta, worker_id, created_at\n                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)\n                ', (accepted_event_id, execution_id, catalog_id, 'batch.accepted', 'events.batch', 'events.batch', 'PENDING', Json(_build_reference_only_result(payload={'request_id': request_id, 'event_ids': event_ids, 'commands_generated': 0}, status='PENDING')), Json(accepted_meta), req.worker_id, datetime.now(timezone.utc)))
            await conn.commit()
            for terminal_command_id in terminal_command_ids:
                _active_claim_cache_invalidate(command_id=terminal_command_id)
    job = _BatchAcceptJob(request_id=request_id, execution_id=execution_id, catalog_id=catalog_id, worker_id=req.worker_id, idempotency_key=idempotency_key, events=req.events, last_actionable_event=last_actionable_event, last_actionable_evt_id=last_actionable_evt_id, accepted_event_id=accepted_event_id, accepted_at_monotonic=time.perf_counter())
    return _BatchAcceptanceResult(job=job, event_ids=event_ids, duplicate=False)

async def _issue_commands_for_batch(job: _BatchAcceptJob, commands: list) -> None:
    if not commands:
        return
    server_url = os.getenv('NOETL_SERVER_URL', 'http://noetl.noetl.svc.cluster.local:8082')
    publish_items: list[tuple[int, str, str, int]] = []
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            for cmd in commands:
                await cur.execute('SELECT catalog_id, parent_execution_id FROM noetl.event WHERE execution_id = %s LIMIT 1', (int(cmd.execution_id),))
                row = await cur.fetchone()
                cat_id = row['catalog_id'] if row else job.catalog_id
                parent_exec = row['parent_execution_id'] if row else None
                cmd_suffix = await _next_snowflake_id(cur)
                cmd_id = f'{cmd.execution_id}:{cmd.step}:{cmd_suffix}'
                new_evt_id = await _next_snowflake_id(cur)
                context = _build_command_context(cmd)
                _validate_postgres_command_context_or_422(step=cmd.step, tool_kind=cmd.tool.kind, context=context)
                meta = {'command_id': cmd_id, 'step': cmd.step, 'tool_kind': cmd.tool.kind, 'triggered_by': job.last_actionable_event.name if job.last_actionable_event else 'batch', 'actionable': True, 'batch_request_id': job.request_id}
                if cmd.metadata:
                    meta.update({k: v for k, v in cmd.metadata.items() if v is not None})
                context = await _store_command_context_if_needed(execution_id=int(cmd.execution_id), step=cmd.step, command_id=cmd_id, context=context)
                await cur.execute('\n                    INSERT INTO noetl.event (\n                        event_id, execution_id, catalog_id, event_type,\n                        node_id, node_name, node_type, status,\n                        context, meta, parent_event_id, parent_execution_id,\n                        created_at\n                    ) VALUES (\n                        %(event_id)s, %(execution_id)s, %(catalog_id)s, %(event_type)s,\n                        %(node_id)s, %(node_name)s, %(node_type)s, %(status)s,\n                        %(context)s, %(meta)s, %(parent_event_id)s, %(parent_execution_id)s,\n                        %(created_at)s\n                    )\n                    ', {'event_id': new_evt_id, 'execution_id': int(cmd.execution_id), 'catalog_id': cat_id, 'event_type': 'command.issued', 'node_id': cmd.step, 'node_name': cmd.step, 'node_type': cmd.tool.kind, 'status': 'PENDING', 'context': Json(context), 'meta': Json(meta), 'parent_event_id': job.last_actionable_evt_id, 'parent_execution_id': parent_exec, 'created_at': datetime.now(timezone.utc)})
                publish_items.append((int(cmd.execution_id), cmd.step, cmd_id, new_evt_id))
            await conn.commit()
    await _publish_commands_with_recovery([(execution_id, evt_id, cmd_id, step) for execution_id, step, cmd_id, evt_id in publish_items], server_url=server_url)

async def _process_accepted_batch(job: _BatchAcceptJob) -> int:
    commands: list = []
    engine: Optional[ControlFlowEngine] = None
    if job.last_actionable_event:
        engine = get_engine()
        async with get_pool_connection() as engine_conn:
            async with engine_conn.transaction():
                async with engine_conn.cursor() as cur:
                    timeout_ms = int(_BATCH_PROCESSING_STATEMENT_TIMEOUT_MS)
                    await cur.execute(f'SET LOCAL statement_timeout = {timeout_ms}')
                    await cur.execute('SELECT pg_advisory_xact_lock(%s)', (int(job.last_actionable_event.execution_id),))
                    commands = await engine.handle_event(job.last_actionable_event, conn=engine_conn, already_persisted=True)
    try:
        await _issue_commands_for_batch(job, commands)
    except Exception as e:
        if engine is not None and commands:
            await _invalidate_execution_state_cache(str(job.execution_id), reason=f'batch_command_issue_failed:{type(e).__name__}', engine=engine)
        raise
    return len(commands)

async def _batch_accept_worker_loop(worker_idx: int) -> None:
    logger.info('[BATCH-EVENTS] Batch acceptor worker-%s started', worker_idx)
    while True:
        try:
            if _batch_accept_queue is None:
                await asyncio.sleep(0.05)
                continue
            job = await _batch_accept_queue.get()
        except asyncio.CancelledError:
            logger.info('[BATCH-EVENTS] Batch acceptor worker-%s stopped', worker_idx)
            raise
        queue_wait_seconds = max(0.0, time.perf_counter() - job.accepted_at_monotonic)
        _observe_batch_metric('first_worker_claim_latency_seconds', queue_wait_seconds)
        try:
            await _persist_batch_status_event(execution_id=job.execution_id, catalog_id=job.catalog_id, request_id=job.request_id, worker_id=job.worker_id, idempotency_key=job.idempotency_key, event_type='batch.processing', status='RUNNING', payload={'request_id': job.request_id, 'queue_wait_ms': round(queue_wait_seconds * 1000, 3), 'event_count': len(job.events)})
            process_start = time.perf_counter()
            try:
                if _BATCH_PROCESSING_TIMEOUT_SECONDS > 0:
                    commands_generated = await asyncio.wait_for(_process_accepted_batch(job), timeout=_BATCH_PROCESSING_TIMEOUT_SECONDS)
                else:
                    commands_generated = await _process_accepted_batch(job)
            except asyncio.TimeoutError:
                _inc_batch_metric('processing_timeout_total')
                await _persist_batch_failed_event(job, _BATCH_FAILURE_PROCESSING_TIMEOUT, f'Batch processing exceeded {_BATCH_PROCESSING_TIMEOUT_SECONDS}s timeout')
                continue
            processing_seconds = time.perf_counter() - process_start
            if processing_seconds > _BATCH_PROCESSING_WARN_SECONDS:
                logger.warning('[BATCH-EVENTS] Slow async batch processing request_id=%s execution_id=%s event_count=%s processing_seconds=%.3f commands_generated=%s', job.request_id, job.execution_id, len(job.events), processing_seconds, commands_generated)
            await _persist_batch_status_event(execution_id=job.execution_id, catalog_id=job.catalog_id, request_id=job.request_id, worker_id=job.worker_id, idempotency_key=job.idempotency_key, event_type='batch.completed', status='COMPLETED', payload={'request_id': job.request_id, 'commands_generated': commands_generated, 'processing_ms': round(processing_seconds * 1000, 3)})
        except Exception as e:
            _inc_batch_metric('processing_error_total')
            await _persist_batch_failed_event(job, _BATCH_FAILURE_PROCESSING_ERROR, str(e))
        finally:
            if _batch_accept_queue is not None:
                _batch_accept_queue.task_done()

@router.post('/events/batch', response_model=BatchEventResponse, status_code=202)
async def handle_batch_events(req: BatchEventRequest, request: Request) -> BatchEventResponse:
    """
    Persist batched events and acknowledge with request_id before engine/NATS work.

    Contract:
    1. persist worker events + batch.accepted marker
    2. enqueue async processing
    3. return HTTP 202 with request_id
    """
    idempotency_key = request.headers.get('Idempotency-Key') or request.headers.get('X-Idempotency-Key')
    try:
        _raise_if_db_short_circuit_enabled(operation='events_batch')
        workers_ready = await ensure_batch_acceptor_started()
        if _batch_accept_queue is None:
            _inc_batch_metric('queue_unavailable_total')
            raise HTTPException(status_code=503, detail=_build_batch_error(_BATCH_FAILURE_QUEUE_UNAVAILABLE, 'Batch acceptance queue is unavailable'))
        if not workers_ready:
            _inc_batch_metric('worker_unavailable_total')
            raise HTTPException(status_code=503, detail=_build_batch_error(_BATCH_FAILURE_WORKER_UNAVAILABLE, 'No batch acceptance workers available'))
        acceptance = await _persist_batch_acceptance(req, idempotency_key)
        _record_db_operation_success()
        if acceptance.duplicate:
            return BatchEventResponse(status='accepted', request_id=acceptance.job.request_id, event_ids=acceptance.event_ids, commands_generated=0, queue_depth=_batch_queue_depth(), duplicate=True, idempotency_key=idempotency_key)
        enqueue_start = time.perf_counter()
        try:
            await asyncio.wait_for(_batch_accept_queue.put(acceptance.job), timeout=_BATCH_ACCEPT_ENQUEUE_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            _inc_batch_metric('ack_timeout_total')
            await _persist_batch_failed_event(acceptance.job, _BATCH_FAILURE_ENQUEUE_TIMEOUT, f'Timed out while waiting to enqueue batch request (>{_BATCH_ACCEPT_ENQUEUE_TIMEOUT_SECONDS}s)')
            raise HTTPException(status_code=503, detail=_build_batch_error(_BATCH_FAILURE_ENQUEUE_TIMEOUT, 'Timed out while waiting for batch enqueue acknowledgment', acceptance.job.request_id), headers={'Retry-After': '1'})
        except Exception as e:
            _inc_batch_metric('enqueue_error_total')
            await _persist_batch_failed_event(acceptance.job, _BATCH_FAILURE_ENQUEUE_ERROR, str(e))
            raise HTTPException(status_code=503, detail=_build_batch_error(_BATCH_FAILURE_ENQUEUE_ERROR, f'Failed to enqueue batch request: {e}', acceptance.job.request_id))
        _observe_batch_metric('enqueue_latency_seconds', time.perf_counter() - enqueue_start)
        _inc_batch_metric('accepted_total')
        return BatchEventResponse(status='accepted', request_id=acceptance.job.request_id, event_ids=acceptance.event_ids, commands_generated=0, queue_depth=_batch_queue_depth(), duplicate=False, idempotency_key=idempotency_key)
    except PoolTimeout:
        retry_after = _compute_retry_after()
        logger.warning('[BATCH-EVENTS] DB pool saturated during acceptance retry_after=%ss', retry_after)
        raise HTTPException(status_code=503, detail=_build_batch_error('pool_saturated', 'Database temporarily overloaded; retry shortly'), headers={'Retry-After': retry_after})
    except HTTPException:
        raise
    except Exception as e:
        retry_after = _record_db_unavailable_failure(e, operation='events_batch')
        if retry_after is not None:
            raise HTTPException(status_code=503, detail=_build_batch_error('db_unavailable', 'Database temporarily unavailable; retry shortly'), headers={'Retry-After': retry_after})
        logger.error('handle_batch_events failed: %s', e, exc_info=True)
        raise HTTPException(status_code=500, detail=_build_batch_error(_BATCH_FAILURE_ENQUEUE_ERROR, f'Batch acceptance failed: {e}'))

async def _get_batch_request_state(request_id: str) -> dict[str, Any]:
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("\n                SELECT execution_id, event_type, status, result, error, created_at, meta\n                FROM noetl.event\n                WHERE meta->>'batch_request_id' = %s\n                  AND event_type IN ('batch.accepted', 'batch.processing', 'batch.completed', 'batch.failed')\n                ORDER BY event_id DESC\n                LIMIT 1\n                ", (request_id,))
            row = await cur.fetchone()
    if not row:
        raise HTTPException(404, f'Batch request not found: {request_id}')
    event_type = row['event_type']
    if event_type == 'batch.completed':
        state = 'completed'
    elif event_type == 'batch.failed':
        state = 'failed'
    elif event_type == 'batch.processing':
        state = 'processing'
    else:
        state = 'accepted'
    result_obj = row.get('result') or {}
    result_context = result_obj.get('context') if isinstance(result_obj, dict) else {}
    error_code = result_context.get('error_code')
    message = result_context.get('message') or row.get('error')
    meta = row.get('meta') or {}
    return {'request_id': request_id, 'execution_id': str(row['execution_id']), 'state': state, 'status': row['status'], 'error_code': error_code, 'message': message, 'commands_generated': result_context.get('commands_generated'), 'idempotency_key': meta.get('idempotency_key'), 'updated_at': _iso_timestamp(row.get('created_at'))}

@router.get('/events/batch/{request_id}/status')
async def get_batch_event_status(request_id: str):
    """Fetch async processing status for a previously accepted batch request."""
    try:
        return await _get_batch_request_state(request_id)
    except PoolTimeout:
        retry_after = _compute_retry_after()
        raise HTTPException(status_code=503, detail={'code': 'pool_saturated', 'message': 'Database temporarily overloaded; retry shortly'}, headers={'Retry-After': retry_after})

@router.get('/events/batch/{request_id}/stream')
async def stream_batch_event_status(request_id: str, timeout_seconds: float=30.0):
    """SSE stream for batch status updates (accepted/processing/completed/failed)."""
    timeout_seconds = max(1.0, float(timeout_seconds))

    async def _stream():
        started_at = time.perf_counter()
        while True:
            try:
                payload = await _get_batch_request_state(request_id)
            except HTTPException as e:
                payload = {'request_id': request_id, 'state': 'not_found' if e.status_code == 404 else 'error', 'status': 'FAILED', 'error_code': 'not_found' if e.status_code == 404 else 'lookup_error', 'message': str(e.detail)}
                yield f'event: status\ndata: {json.dumps(payload)}\n\n'
                break
            yield f'event: status\ndata: {json.dumps(payload, default=str)}\n\n'
            if payload.get('state') in {'completed', 'failed'}:
                break
            if time.perf_counter() - started_at >= timeout_seconds:
                timeout_payload = {'request_id': request_id, 'state': 'timeout', 'status': 'RUNNING', 'message': 'SSE stream timeout reached; continue polling /status'}
                yield f'event: status\ndata: {json.dumps(timeout_payload)}\n\n'
                break
            await asyncio.sleep(_BATCH_STATUS_STREAM_POLL_SECONDS)
    return StreamingResponse(_stream(), media_type='text/event-stream')

__all__ = ['_get_batch_acceptor_lock', '_has_live_batch_workers', 'ensure_batch_acceptor_started', 'shutdown_batch_acceptor', '_persist_batch_status_event', '_build_batch_error', '_persist_batch_failed_event', '_persist_batch_acceptance', '_issue_commands_for_batch', '_process_accepted_batch', '_batch_accept_worker_loop', 'handle_batch_events', '_get_batch_request_state', 'get_batch_event_status', 'stream_batch_event_status']
