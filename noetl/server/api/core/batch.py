import asyncio
import time
import os
import json
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any, Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from psycopg.rows import dict_row
from psycopg_pool import PoolTimeout
from psycopg.types.json import Json
from noetl.core.db.pool import get_pool_connection
from noetl.core.dsl.engine.models import Event
from .core import (
    logger, get_engine,
    _BATCH_ACCEPT_QUEUE_MAXSIZE, _BATCH_ACCEPT_WORKERS,
    _BATCH_ACCEPT_ENQUEUE_TIMEOUT_SECONDS, _BATCH_PROCESSING_TIMEOUT_SECONDS,
    _BATCH_PROCESSING_WARN_SECONDS, _BATCH_PROCESSING_STATEMENT_TIMEOUT_MS,
    _BATCH_STATUS_STREAM_POLL_SECONDS, _COMMAND_TERMINAL_EVENT_TYPES,
    _BATCH_FAILURE_QUEUE_UNAVAILABLE, _BATCH_FAILURE_WORKER_UNAVAILABLE,
    _BATCH_FAILURE_ENQUEUE_TIMEOUT, _BATCH_FAILURE_ENQUEUE_ERROR,
    _BATCH_FAILURE_PROCESSING_TIMEOUT, _BATCH_FAILURE_PROCESSING_ERROR,
)
from .models import BatchEventRequest, BatchEventResponse
from .utils import (
    _compute_retry_after, _status_from_event_name, _iso_timestamp,
)
from .db import (
    _next_snowflake_id, _record_db_operation_success,
    _record_db_unavailable_failure, _raise_if_db_short_circuit_enabled,
)
from .metrics import _inc_batch_metric, _observe_batch_metric
from .cache import _active_claim_cache_invalidate
from .recovery import _publish_commands_with_recovery

router = APIRouter()

@dataclass(slots=True)
class _BatchAcceptJob:
    request_id: str
    execution_id: int
    catalog_id: Optional[int]
    worker_id: Optional[str]
    idempotency_key: Optional[str]
    events: list[Any]
    last_actionable_event: Optional[Event]
    last_actionable_evt_id: Optional[int]
    accepted_event_id: int
    accepted_at_monotonic: float

@dataclass(slots=True)
class _BatchAcceptanceResult:
    job: _BatchAcceptJob
    event_ids: list[int]
    duplicate: bool

_batch_accept_queue: Optional[asyncio.Queue[_BatchAcceptJob]] = None
_batch_accept_workers_tasks: list[asyncio.Task] = []
_batch_acceptor_lock: Optional[asyncio.Lock] = None
_batch_execution_locks: dict[int, asyncio.Lock] = {}
_batch_execution_locks_guard: Optional[asyncio.Lock] = None

def _get_batch_acceptor_lock() -> asyncio.Lock:
    global _batch_acceptor_lock
    if _batch_acceptor_lock is None: _batch_acceptor_lock = asyncio.Lock()
    return _batch_acceptor_lock

def _get_batch_execution_locks_guard() -> asyncio.Lock:
    global _batch_execution_locks_guard
    if _batch_execution_locks_guard is None:
        _batch_execution_locks_guard = asyncio.Lock()
    return _batch_execution_locks_guard

async def _get_batch_execution_lock(execution_id: int) -> asyncio.Lock:
    async with _get_batch_execution_locks_guard():
        lock = _batch_execution_locks.get(execution_id)
        if lock is None:
            lock = asyncio.Lock()
            _batch_execution_locks[execution_id] = lock
        return lock

async def ensure_batch_acceptor_started() -> bool:
    global _batch_accept_queue
    if _BATCH_ACCEPT_WORKERS <= 0: return False
    async with _get_batch_acceptor_lock():
        if _batch_accept_queue is None: _batch_accept_queue = asyncio.Queue(maxsize=_BATCH_ACCEPT_QUEUE_MAXSIZE)
        _batch_accept_workers_tasks[:] = [t for t in _batch_accept_workers_tasks if not t.done()]
        while len(_batch_accept_workers_tasks) < _BATCH_ACCEPT_WORKERS:
            worker_idx = len(_batch_accept_workers_tasks) + 1
            _batch_accept_workers_tasks.append(asyncio.create_task(_batch_accept_worker_loop(worker_idx), name=f"batch-acceptor-{worker_idx}"))
        return any(not t.done() for t in _batch_accept_workers_tasks)

async def shutdown_batch_acceptor() -> None:
    async with _get_batch_acceptor_lock():
        if not _batch_accept_workers_tasks: return
        tasks = list(_batch_accept_workers_tasks); _batch_accept_workers_tasks.clear()
        for t in tasks: t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

async def _persist_batch_status_event(execution_id: int, catalog_id: Optional[int], request_id: str, worker_id: Optional[str], idempotency_key: Optional[str], event_type: str, status: str, payload: dict[str, Any], error: Optional[str] = None) -> None:
    from .commands import _build_reference_only_result
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            evt_id = await _next_snowflake_id(cur)
            meta = {"batch_request_id": request_id, "actionable": False, "informative": True, "worker_id": worker_id, "idempotency_key": idempotency_key}
            await cur.execute("""
                INSERT INTO noetl.event (event_id, execution_id, catalog_id, event_type, node_id, node_name, status, result, meta, worker_id, error, created_at)
                VALUES (%s, %s, %s, %s, 'events.batch', 'events.batch', %s, %s, %s, %s, %s, %s)
            """, (evt_id, execution_id, catalog_id, event_type, status, Json(_build_reference_only_result(payload=payload, status=status)), Json(meta), worker_id, error, datetime.now(timezone.utc)))
            await conn.commit()

async def _persist_batch_failed_event(job: _BatchAcceptJob, code: str, message: str) -> None:
    try: await _persist_batch_status_event(job.execution_id, job.catalog_id, job.request_id, job.worker_id, job.idempotency_key, "batch.failed", "FAILED", {"request_id": job.request_id, "error_code": code, "message": message}, error=message)
    except Exception as e: logger.error("[BATCH-EVENTS] Failed to persist batch.failed request_id=%s: %s", job.request_id, e, exc_info=True)

async def _persist_batch_acceptance(req: BatchEventRequest, idempotency_key: Optional[str]) -> _BatchAcceptanceResult:
    from .events import _validate_reference_only_payload, _extract_command_id_from_payload, _extract_event_error
    from .commands import _build_reference_only_result
    skip_engine = {"command.claimed", "command.heartbeat", "command.started", "command.completed", "step.enter"}
    exec_id = int(req.execution_id)
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT catalog_id FROM noetl.event WHERE execution_id = %s LIMIT 1", (exec_id,))
            catalog_id = (await cur.fetchone() or {}).get("catalog_id")
            if idempotency_key:
                await cur.execute("SELECT meta, result FROM noetl.event WHERE execution_id = %s AND event_type = 'batch.accepted' AND meta->>'idempotency_key' = %s ORDER BY event_id DESC LIMIT 1", (exec_id, idempotency_key))
                if row := await cur.fetchone():
                    meta, res = row.get("meta") or {}, row.get("result") or {}
                    ctx = res.get("context") if isinstance(res, dict) else {}
                    request_id = str(meta.get("batch_request_id") or ctx.get("request_id"))
                    if request_id:
                        return _BatchAcceptanceResult(job=_BatchAcceptJob(request_id, exec_id, catalog_id, req.worker_id, idempotency_key, [], None, None, 0, time.perf_counter()), event_ids=[int(eid) for eid in (ctx.get("event_ids") or []) if isinstance(eid, int)], duplicate=True)

            request_id, accepted_evt_id = str(await _next_snowflake_id(cur)), await _next_snowflake_id(cur)
            event_ids, last_act_evt, last_act_evt_id, term_cmd_ids = [], None, None, set()
            now = datetime.now(timezone.utc)
            insert_params = []
            command_updates = []
            for item in req.events:
                _validate_reference_only_payload(item.payload)
                evt_id = await _next_snowflake_id(cur); event_ids.append(evt_id)
                meta = {"actionable": item.actionable, "informative": item.informative, "batch_request_id": request_id, "persisted_event_id": str(evt_id), "worker_id": req.worker_id, "idempotency_key": idempotency_key, **(item.meta or {})}
                if cmd_id := _extract_command_id_from_payload(item.payload): meta["command_id"] = cmd_id
                status = _status_from_event_name(item.name)
                result_obj = _build_reference_only_result(payload=item.payload, status=status)
                
                insert_params.append((
                    evt_id, exec_id, catalog_id, item.name, item.step, item.step, 
                    status,
                    Json(result_obj),
                    Json(meta), req.worker_id, _extract_event_error(item.payload), cmd_id, now
                ))

                if cmd_id and item.name in {
                    "command.started", "command.completed", "command.failed", "command.cancelled",
                }:
                    command_updates.append((item.name, evt_id, req.worker_id, Json(result_obj), _extract_event_error(item.payload), cmd_id))

                if cmd_id and item.name in _COMMAND_TERMINAL_EVENT_TYPES: term_cmd_ids.add(cmd_id)
                if item.actionable and item.name not in skip_engine:
                    last_act_evt = Event(execution_id=req.execution_id, step=item.step, name=item.name, payload=item.payload, meta=meta, timestamp=now, worker_id=req.worker_id)
                    last_act_evt_id = evt_id
            
            if insert_params:
                await cur.executemany("""
                    INSERT INTO noetl.event (event_id, execution_id, catalog_id, event_type, node_id, node_name, status, result, meta, worker_id, error, command_id, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, insert_params)

            for event_name, evt_id, worker_id, result_obj, error_text, cmd_id in command_updates:
                if event_name == "command.started":
                    await cur.execute(
                        """
                        UPDATE noetl.command
                        SET status = 'RUNNING',
                            started_at = now(),
                            latest_event_id = %s,
                            updated_at = now()
                        WHERE command_id = %s
                        """,
                        (evt_id, cmd_id),
                    )
                else:
                    terminal_status = {
                        "command.completed": "COMPLETED",
                        "command.failed": "FAILED",
                        "command.cancelled": "CANCELLED",
                    }[event_name]
                    await cur.execute(
                        """
                        UPDATE noetl.command
                        SET status = %s,
                            completed_at = now(),
                            latest_event_id = %s,
                            result = %s,
                            error = %s,
                            updated_at = now()
                        WHERE command_id = %s
                        """,
                        (terminal_status, evt_id, result_obj, error_text, cmd_id),
                    )
            
            acc_meta = {"batch_request_id": request_id, "actionable": False, "informative": True, "event_count": len(req.events), "worker_id": req.worker_id, "idempotency_key": idempotency_key}
            if last_act_evt_id: acc_meta["last_actionable_event_id"] = str(last_act_evt_id)
            await cur.execute("""
                INSERT INTO noetl.event (event_id, execution_id, catalog_id, event_type, node_id, node_name, status, result, meta, worker_id, created_at)
                VALUES (%s, %s, %s, %s, 'events.batch', 'events.batch', 'PENDING', %s, %s, %s, %s)
            """, (accepted_evt_id, exec_id, catalog_id, "batch.accepted", Json(_build_reference_only_result(payload={"request_id": request_id, "event_ids": event_ids, "commands_generated": 0}, status="PENDING")), Json(acc_meta), req.worker_id, datetime.now(timezone.utc)))
            await conn.commit()
            for cid in term_cmd_ids: _active_claim_cache_invalidate(command_id=cid)
    return _BatchAcceptanceResult(job=_BatchAcceptJob(request_id, exec_id, catalog_id, req.worker_id, idempotency_key, req.events, last_act_evt, last_act_evt_id, accepted_evt_id, time.perf_counter()), event_ids=event_ids, duplicate=False)

async def _issue_commands_for_batch(job: _BatchAcceptJob, commands: list) -> None:
    from .commands import _build_command_context, _validate_postgres_command_context_or_422, _store_command_context_if_needed
    if not commands: return
    server_url = os.getenv("NOETL_SERVER_URL", "http://noetl.noetl.svc.cluster.local:8082")
    
    # 1. Fetch catalog_id and parent_exec once
    cat_id, p_exec = job.catalog_id, None
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT catalog_id, parent_execution_id FROM noetl.event WHERE execution_id = %s LIMIT 1", (int(job.execution_id),))
            if row := await cur.fetchone():
                cat_id, p_exec = row.get("catalog_id") or cat_id, row.get("parent_execution_id")

            from .db import _next_snowflake_ids
            # 2. Prepare command contexts and metadata (BATCHED SNOWFLAKES)
            prepared_commands = []
            # Need 2 snowflakes per command
            all_snowflakes = await _next_snowflake_ids(cur, len(commands) * 2)
            
            for i, cmd in enumerate(commands):
                # Yield to the event loop every 20 items
                await asyncio.sleep(0)
                
                cmd_suffix = all_snowflakes[i * 2]
                new_evt_id = all_snowflakes[i * 2 + 1]
                
                cmd_id = f"{cmd.execution_id}:{cmd.step}:{cmd_suffix}"
                ctx = _build_command_context(cmd)
                _validate_postgres_command_context_or_422(step=cmd.step, tool_kind=cmd.tool.kind, context=ctx)
                meta = {
                    "command_id": cmd_id, 
                    "step": cmd.step, 
                    "tool_kind": cmd.tool.kind, 
                    "triggered_by": job.last_actionable_event.name if job.last_actionable_event else "batch", 
                    "actionable": True, 
                    "batch_request_id": job.request_id, 
                    **(cmd.metadata or {})
                }
                prepared_commands.append({
                    "cmd_id": cmd_id, "evt_id": new_evt_id, "ctx": ctx, "meta": meta, "step": cmd.step, "execution_id": int(cmd.execution_id), "tool_kind": cmd.tool.kind
                })

            # 3. Parallel context storage with DE-DUPLICATION and MEMORY CLEANUP
            storage_semaphore = asyncio.Semaphore(10)
            async def _sem_store(p, cmd):
                async with storage_semaphore:
                    p['ctx'] = await _store_command_context_if_needed(execution_id=p['execution_id'], step=p['step'], command_id=p['cmd_id'], context=p['ctx'])
                    if hasattr(cmd, 'render_context'): cmd.render_context = None
                    if hasattr(cmd, 'tool') and hasattr(cmd.tool, 'config'): cmd.tool.config = None
            
            await asyncio.gather(*[_sem_store(p, cmd) for p, cmd in zip(prepared_commands, commands)])

            # 4. Batch insert commands
            now = datetime.now(timezone.utc)
            insert_params = [
                (p["evt_id"], p["execution_id"], cat_id, "command.issued", p["step"], p["step"], p["tool_kind"], "PENDING", Json(p["ctx"]), Json(p["meta"]), job.last_actionable_evt_id, p_exec, p["cmd_id"], now)
                for p in prepared_commands
            ]
            command_table_params = [
                (p["cmd_id"], p["evt_id"], p["execution_id"], cat_id, p_exec, p["step"], p["tool_kind"], "PENDING", Json(p["ctx"]), p["meta"].get("__loop_epoch_id") or p["meta"].get("loop_event_id"), p["meta"].get("__loop_claimed_index") or p["meta"].get("iter_index"), Json(p["meta"]), now)
                for p in prepared_commands
            ]
            # Chunk the inserts to prevent massive database payload crashes
            chunk_size = 10
            for j in range(0, len(insert_params), chunk_size):
                chunk = insert_params[j:j + chunk_size]
                await cur.executemany("""
                    INSERT INTO noetl.event (event_id, execution_id, catalog_id, event_type, node_id, node_name, node_type, status, context, meta, parent_event_id, parent_execution_id, command_id, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, chunk)
                await cur.executemany("""
                    INSERT INTO noetl.command (
                        command_id, event_id, execution_id, catalog_id, parent_execution_id,
                        step_name, tool_kind, status, context, loop_event_id, iter_index, meta, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (command_id) DO NOTHING
                """, command_table_params[j:j + chunk_size])
                await conn.commit()

    # 5. Parallel NATS publish
    publish_items = [(p["execution_id"], p["evt_id"], p["cmd_id"], p["step"]) for p in prepared_commands]
    await _publish_commands_with_recovery(publish_items, server_url=server_url)

async def _process_accepted_batch(job: _BatchAcceptJob) -> int:
    from .events import _invalidate_execution_state_cache
    commands = []
    engine = None
    if job.last_actionable_event:
        engine = get_engine()
        async with get_pool_connection() as engine_conn:
            async with engine_conn.transaction():
                async with engine_conn.cursor() as cur:
                    await cur.execute(f"SET LOCAL statement_timeout = {int(_BATCH_PROCESSING_STATEMENT_TIMEOUT_MS)}"); await cur.execute(f"SET LOCAL idle_in_transaction_session_timeout = {int(_BATCH_PROCESSING_STATEMENT_TIMEOUT_MS)}")
                    await cur.execute("SELECT pg_advisory_xact_lock(%s)", (int(job.last_actionable_event.execution_id),))
                    commands = await engine.handle_event(job.last_actionable_event, conn=engine_conn, already_persisted=True)
    try: await _issue_commands_for_batch(job, commands)
    except Exception as e:
        if engine and commands: await _invalidate_execution_state_cache(str(job.execution_id), reason=f"batch_command_issue_failed:{type(e).__name__}", engine=engine)
        raise
    return len(commands)

def _drain_contiguous_jobs_for_execution(execution_id: int) -> list[_BatchAcceptJob]:
    if _batch_accept_queue is None:
        return []
    queue_impl = getattr(_batch_accept_queue, "_queue", None)
    if queue_impl is None:
        return []

    drained: list[_BatchAcceptJob] = []
    while queue_impl:
        next_job = queue_impl[0]
        if next_job.execution_id != execution_id:
            break
        drained.append(queue_impl.popleft())
    return drained

async def _process_batch_job(job: _BatchAcceptJob) -> None:
    q_wait = max(0.0, time.perf_counter() - job.accepted_at_monotonic)
    _observe_batch_metric("first_worker_claim_latency_seconds", q_wait)
    await _persist_batch_status_event(
        job.execution_id,
        job.catalog_id,
        job.request_id,
        job.worker_id,
        job.idempotency_key,
        "batch.processing",
        "RUNNING",
        {
            "request_id": job.request_id,
            "queue_wait_ms": round(q_wait * 1000, 3),
            "event_count": len(job.events),
        },
    )
    p_start = time.perf_counter()
    try:
        if _BATCH_PROCESSING_TIMEOUT_SECONDS > 0:
            cmd_gen = await asyncio.wait_for(
                _process_accepted_batch(job),
                timeout=_BATCH_PROCESSING_TIMEOUT_SECONDS,
            )
        else:
            cmd_gen = await _process_accepted_batch(job)
    except asyncio.TimeoutError:
        _inc_batch_metric("processing_timeout_total")
        await _persist_batch_failed_event(
            job,
            _BATCH_FAILURE_PROCESSING_TIMEOUT,
            f"Batch processing timed out (>{_BATCH_PROCESSING_TIMEOUT_SECONDS}s)",
        )
        return

    p_sec = time.perf_counter() - p_start
    if p_sec > _BATCH_PROCESSING_WARN_SECONDS:
        logger.warning(
            "[BATCH-EVENTS] Slow async batch processing request_id=%s exec_id=%s event_count=%s p_sec=%.3f cmd_gen=%s",
            job.request_id,
            job.execution_id,
            len(job.events),
            p_sec,
            cmd_gen,
        )
    await _persist_batch_status_event(
        job.execution_id,
        job.catalog_id,
        job.request_id,
        job.worker_id,
        job.idempotency_key,
        "batch.completed",
        "COMPLETED",
        {
            "request_id": job.request_id,
            "commands_generated": cmd_gen,
            "processing_ms": round(p_sec * 1000, 3),
        },
    )

async def _batch_accept_worker_loop(worker_idx: int) -> None:
    logger.info("[BATCH-EVENTS] Batch acceptor worker-%s started", worker_idx)
    while True:
        try:
            if _batch_accept_queue is None: await asyncio.sleep(0.05); continue
            job = await _batch_accept_queue.get()
        except asyncio.CancelledError: logger.info("[BATCH-EVENTS] Batch acceptor worker-%s stopped", worker_idx); raise
        try:
            execution_lock = await _get_batch_execution_lock(job.execution_id)
            async with execution_lock:
                jobs = [job]
                drained_jobs = _drain_contiguous_jobs_for_execution(job.execution_id)
                if drained_jobs:
                    logger.debug(
                        "[BATCH-EVENTS] worker-%s coalesced %s additional queued batch jobs for execution %s",
                        worker_idx,
                        len(drained_jobs),
                        job.execution_id,
                    )
                    jobs.extend(drained_jobs)

                for idx, grouped_job in enumerate(jobs):
                    try:
                        await _process_batch_job(grouped_job)
                    except Exception as e:
                        _inc_batch_metric("processing_error_total")
                        await _persist_batch_failed_event(grouped_job, _BATCH_FAILURE_PROCESSING_ERROR, str(e))
                    finally:
                        if idx > 0 and _batch_accept_queue is not None:
                            _batch_accept_queue.task_done()
        finally:
            if _batch_accept_queue is not None: _batch_accept_queue.task_done()

@router.post("/events/batch", response_model=BatchEventResponse, status_code=202)
async def handle_batch_events(req: BatchEventRequest, request: Request) -> BatchEventResponse:
    idem_key = request.headers.get("Idempotency-Key") or request.headers.get("X-Idempotency-Key")
    try:
        _raise_if_db_short_circuit_enabled(operation="events_batch")
        ready = await ensure_batch_acceptor_started()
        if _batch_accept_queue is None: _inc_batch_metric("queue_unavailable_total"); raise HTTPException(503, detail={"code": _BATCH_FAILURE_QUEUE_UNAVAILABLE, "message": "Batch queue unavailable"})
        if not ready: _inc_batch_metric("worker_unavailable_total"); raise HTTPException(503, detail={"code": _BATCH_FAILURE_WORKER_UNAVAILABLE, "message": "No batch workers ready"})
        acc = await _persist_batch_acceptance(req, idem_key); _record_db_operation_success()
        if acc.duplicate: return BatchEventResponse(status="accepted", request_id=acc.job.request_id, event_ids=acc.event_ids, commands_generated=0, queue_depth=_batch_accept_queue.qsize(), duplicate=True, idempotency_key=idem_key)
        enq_start = time.perf_counter()
        try: await asyncio.wait_for(_batch_accept_queue.put(acc.job), timeout=_BATCH_ACCEPT_ENQUEUE_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            _inc_batch_metric("ack_timeout_total"); await _persist_batch_failed_event(acc.job, _BATCH_FAILURE_ENQUEUE_TIMEOUT, f"Enqueue timeout (>{_BATCH_ACCEPT_ENQUEUE_TIMEOUT_SECONDS}s)"); raise HTTPException(503, detail={"code": _BATCH_FAILURE_ENQUEUE_TIMEOUT, "request_id": acc.job.request_id}, headers={"Retry-After": "1"})
        except Exception as e:
            _inc_batch_metric("enqueue_error_total"); await _persist_batch_failed_event(acc.job, _BATCH_FAILURE_ENQUEUE_ERROR, str(e)); raise HTTPException(503, detail={"code": _BATCH_FAILURE_ENQUEUE_ERROR, "message": str(e), "request_id": acc.job.request_id})
        _observe_batch_metric("enqueue_latency_seconds", time.perf_counter() - enq_start); _inc_batch_metric("accepted_total")
        return BatchEventResponse(status="accepted", request_id=acc.job.request_id, event_ids=acc.event_ids, commands_generated=0, queue_depth=_batch_accept_queue.qsize(), duplicate=False, idempotency_key=idem_key)
    except PoolTimeout: raise HTTPException(503, detail={"code": "pool_saturated"}, headers={"Retry-After": _compute_retry_after()})
    except HTTPException: raise
    except Exception as e:
        if retry_after := _record_db_unavailable_failure(e, operation="events_batch"): raise HTTPException(503, detail={"code": "db_unavailable"}, headers={"Retry-After": retry_after})
        logger.error("handle_batch_events failed: %s", e, exc_info=True); raise HTTPException(500, detail={"code": _BATCH_FAILURE_ENQUEUE_ERROR, "message": str(e)})

async def _get_batch_request_state(request_id: str) -> dict[str, Any]:
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("""
                SELECT execution_id, event_type, status, result, error, created_at, meta FROM noetl.event
                WHERE meta->>'batch_request_id' = %s AND event_type IN ('batch.accepted', 'batch.processing', 'batch.completed', 'batch.failed')
                ORDER BY event_id DESC LIMIT 1
            """, (request_id,))
            row = await cur.fetchone()
    if not row: raise HTTPException(404, f"Batch request not found: {request_id}")
    et = row["event_type"]
    state = "completed" if et == "batch.completed" else "failed" if et == "batch.failed" else "processing" if et == "batch.processing" else "accepted"
    res = row.get("result") or {}
    ctx = res.get("context") if isinstance(res, dict) else {}
    meta = row.get("meta") or {}
    return {"request_id": request_id, "execution_id": str(row["execution_id"]), "state": state, "status": row["status"], "error_code": ctx.get("error_code"), "message": ctx.get("message") or row.get("error"), "commands_generated": ctx.get("commands_generated"), "idempotency_key": meta.get("idempotency_key"), "updated_at": _iso_timestamp(row.get("created_at"))}

@router.get("/events/batch/{request_id}/status")
async def get_batch_event_status(request_id: str):
    try: return await _get_batch_request_state(request_id)
    except PoolTimeout: raise HTTPException(503, headers={"Retry-After": _compute_retry_after()})

@router.get("/events/batch/{request_id}/stream")
async def stream_batch_event_status(request_id: str, timeout_seconds: float = 30.0):
    async def _stream():
        start = time.perf_counter()
        while True:
            try: payload = await _get_batch_request_state(request_id)
            except HTTPException as e:
                payload = {"request_id": request_id, "state": "not_found" if e.status_code == 404 else "error", "status": "FAILED", "message": str(e.detail)}
                yield f"event: status\ndata: {json.dumps(payload)}\n\n"; break
            yield f"event: status\ndata: {json.dumps(payload, default=str)}\n\n"
            if payload.get("state") in {"completed", "failed"}: break
            if time.perf_counter() - start >= max(1.0, float(timeout_seconds)):
                yield f"event: status\ndata: {json.dumps({'request_id': request_id, 'state': 'timeout', 'status': 'RUNNING', 'message': 'SSE timeout'})}\n\n"; break
            await asyncio.sleep(_BATCH_STATUS_STREAM_POLL_SECONDS)
    return StreamingResponse(_stream(), media_type="text/event-stream")
