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
from noetl.core.messaging import NATSEventPublisher
from noetl.core.outbox import enqueue_outbox, publish_outbox_batch
from noetl.core.sanitize import redact_keychain_values
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
from .metrics import get_batch_metrics_snapshot as _get_batch_metrics_snapshot
from .cache import _active_claim_cache_invalidate
from .recovery import _publish_commands_with_recovery

router = APIRouter()
_batch_event_subject_publisher: NATSEventPublisher | None = None

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


def get_batch_acceptor_metrics_snapshot() -> dict[str, float]:
    """Return batch metrics with live queue depth and worker count."""
    return _get_batch_metrics_snapshot(_batch_accept_queue, _batch_accept_workers_tasks)


def _get_batch_acceptor_lock() -> asyncio.Lock:
    global _batch_acceptor_lock
    if _batch_acceptor_lock is None: _batch_acceptor_lock = asyncio.Lock()
    return _batch_acceptor_lock

def _get_batch_execution_locks_guard() -> asyncio.Lock:
    global _batch_execution_locks_guard
    if _batch_execution_locks_guard is None:
        _batch_execution_locks_guard = asyncio.Lock()
    return _batch_execution_locks_guard


async def _mirror_batch_events(events: list[dict[str, Any]]) -> None:
    from .events import _mirror_events

    await _mirror_events(events)


def _batch_event_mirror_enabled() -> bool:
    return os.getenv("NOETL_EVENT_MIRROR_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def _batch_event_subject(event: dict[str, Any]) -> str:
    global _batch_event_subject_publisher
    if _batch_event_subject_publisher is None:
        _batch_event_subject_publisher = NATSEventPublisher()
    return _batch_event_subject_publisher.subject_for_event(event)


async def _enqueue_batch_outbox(cur: Any, event: dict[str, Any]) -> None:
    if not _batch_event_mirror_enabled():
        return
    await enqueue_outbox(cur, event, subject=_batch_event_subject(event))


async def _drain_batch_outbox() -> None:
    if not _batch_event_mirror_enabled():
        return
    try:
        limit = int(os.getenv("NOETL_BATCH_OUTBOX_DRAIN_LIMIT", "100"))
        await publish_outbox_batch(limit=limit)
    except Exception as exc:
        logger.warning("Batch outbox drain failed: %s", exc)

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
    from .events import _event_envelope
    from .commands import _build_reference_only_result
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            evt_id = await _next_snowflake_id(cur)
            meta = {"batch_request_id": request_id, "actionable": False, "informative": True, "worker_id": worker_id, "idempotency_key": idempotency_key}
            created_at = datetime.now(timezone.utc)
            result_obj = _build_reference_only_result(payload=payload, status=status)
            await cur.execute("""
                INSERT INTO noetl.event (event_id, execution_id, catalog_id, event_type, node_id, node_name, status, result, meta, worker_id, error, created_at)
                VALUES (%s, %s, %s, %s, 'events.batch', 'events.batch', %s, %s, %s, %s, %s, %s)
            """, (evt_id, execution_id, catalog_id, event_type, status, Json(result_obj), Json(meta), worker_id, error, created_at))
            await _enqueue_batch_outbox(
                cur,
                _event_envelope(
                    event_id=evt_id,
                    execution_id=execution_id,
                    catalog_id=catalog_id,
                    event_type=event_type,
                    node_name="events.batch",
                    status=status,
                    result=result_obj,
                    meta=meta,
                    event_time=created_at,
                ),
            )
            await conn.commit()
    await _drain_batch_outbox()

async def _persist_batch_failed_event(job: _BatchAcceptJob, code: str, message: str) -> None:
    try: await _persist_batch_status_event(job.execution_id, job.catalog_id, job.request_id, job.worker_id, job.idempotency_key, "batch.failed", "FAILED", {"request_id": job.request_id, "error_code": code, "message": message}, error=message)
    except Exception as e: logger.error("[BATCH-EVENTS] Failed to persist batch.failed request_id=%s: %s", job.request_id, e, exc_info=True)

async def _persist_batch_acceptance(req: BatchEventRequest, idempotency_key: Optional[str]) -> _BatchAcceptanceResult:
    from .events import _event_envelope, _validate_reference_only_payload, _extract_command_id_from_payload, _extract_event_error
    from .commands import _build_reference_only_result
    skip_engine = {"command.claimed", "command.heartbeat", "command.started", "command.completed", "step.enter"}
    exec_id = int(req.execution_id)
    mirrored_events: list[dict[str, Any]] = []
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT catalog_id FROM noetl.event WHERE execution_id = %s LIMIT 1", (exec_id,))
            catalog_id = (await cur.fetchone() or {}).get("catalog_id")
            # Fall back to the request's caller-supplied catalog_id when no
            # prior event row exists for this execution.  This is the
            # inline-runner path: a worker creates a child execution_id
            # in-process and emits its first events via this endpoint —
            # there is no ``POST /api/execute`` ingress for that execution,
            # so the DB lookup above returns ``None`` and the
            # ``noetl.event.catalog_id`` NOT NULL constraint would block
            # the insert.  The DB-discovered value still wins when present
            # so cross-batch rows stay consistent.
            if catalog_id is None and req.catalog_id is not None:
                catalog_id = req.catalog_id
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
                cmd_id = _extract_command_id_from_payload(item.payload)
                if cmd_id: meta["command_id"] = cmd_id
                status = _status_from_event_name(item.name)
                result_obj = _build_reference_only_result(payload=item.payload, status=status)
                
                insert_params.append((
                    evt_id, exec_id, catalog_id, item.name, item.step, item.step, 
                    status,
                    Json(result_obj),
                    Json(meta), req.worker_id, _extract_event_error(item.payload), cmd_id, now
                ))
                mirrored_events.append(_event_envelope(
                    event_id=evt_id,
                    execution_id=exec_id,
                    catalog_id=catalog_id,
                    event_type=item.name,
                    node_name=item.step,
                    status=status,
                    result=result_obj,
                    meta=meta,
                    command_id=cmd_id,
                    stage_id=meta.get("stage_id"),
                    frame_id=meta.get("frame_id"),
                    event_time=now,
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
                        SET status = CASE WHEN completed_at IS NULL THEN 'RUNNING' ELSE status END,
                            started_at = COALESCE(started_at, now()),
                            latest_event_id = CASE WHEN completed_at IS NULL THEN %s ELSE latest_event_id END,
                            updated_at = CASE WHEN completed_at IS NULL THEN now() ELSE updated_at END
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
            accepted_at = datetime.now(timezone.utc)
            accepted_result = _build_reference_only_result(payload={"request_id": request_id, "event_ids": event_ids, "commands_generated": 0}, status="PENDING")
            await cur.execute("""
                INSERT INTO noetl.event (event_id, execution_id, catalog_id, event_type, node_id, node_name, status, result, meta, worker_id, created_at)
                VALUES (%s, %s, %s, %s, 'events.batch', 'events.batch', 'PENDING', %s, %s, %s, %s)
            """, (accepted_evt_id, exec_id, catalog_id, "batch.accepted", Json(accepted_result), Json(acc_meta), req.worker_id, accepted_at))
            mirrored_events.append(_event_envelope(
                event_id=accepted_evt_id,
                execution_id=exec_id,
                catalog_id=catalog_id,
                event_type="batch.accepted",
                node_name="events.batch",
                status="PENDING",
                result=accepted_result,
                meta=acc_meta,
                event_time=accepted_at,
            ))
            for event in mirrored_events:
                await _enqueue_batch_outbox(cur, event)
            await conn.commit()
            for cid in term_cmd_ids: _active_claim_cache_invalidate(command_id=cid)
    await _drain_batch_outbox()
    return _BatchAcceptanceResult(job=_BatchAcceptJob(request_id, exec_id, catalog_id, req.worker_id, idempotency_key, req.events, last_act_evt, last_act_evt_id, accepted_evt_id, time.perf_counter()), event_ids=event_ids, duplicate=False)

async def _issue_commands_for_batch(job: _BatchAcceptJob, commands: list) -> None:
    from .commands import _build_command_context, _validate_postgres_command_context_or_422, _store_command_context_if_needed
    from .events import _command_issued_envelope
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
                
                cmd_id = cmd_suffix  # already a snowflake bigint
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
                (p["evt_id"], p["execution_id"], cat_id, "command.issued", p["step"], p["step"], p["tool_kind"], "PENDING", Json(p["ctx"]), Json(p["meta"]), job.last_actionable_evt_id, p_exec, p["cmd_id"], p["meta"].get("stage_id"), p["meta"].get("frame_id"), now)
                for p in prepared_commands
            ]
            command_table_params = [
                (p["cmd_id"], p["evt_id"], p["execution_id"], cat_id, p_exec, p["step"], p["tool_kind"], "PENDING", Json(p["ctx"]), p["meta"].get("__loop_epoch_id") or p["meta"].get("loop_event_id"), p["meta"].get("__loop_claimed_index") or p["meta"].get("iter_index"), Json(p["meta"]), p["meta"].get("stage_id"), p["meta"].get("frame_id"), now)
                for p in prepared_commands
            ]
            # Chunk the inserts to prevent massive database payload crashes
            chunk_size = 10
            for j in range(0, len(insert_params), chunk_size):
                chunk = insert_params[j:j + chunk_size]
                prepared_chunk = prepared_commands[j:j + chunk_size]
                await cur.executemany("""
                    INSERT INTO noetl.event (event_id, execution_id, catalog_id, event_type, node_id, node_name, node_type, status, context, meta, parent_event_id, parent_execution_id, command_id, stage_id, frame_id, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, chunk)
                await cur.executemany("""
                    INSERT INTO noetl.command (
                        command_id, event_id, execution_id, catalog_id, parent_execution_id,
                        step_name, tool_kind, status, context, loop_event_id, iter_index, meta, stage_id, frame_id, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (execution_id, command_id) DO NOTHING
                """, command_table_params[j:j + chunk_size])
                for p in prepared_chunk:
                    await _enqueue_batch_outbox(
                        cur,
                        _command_issued_envelope(
                            event_id=p["evt_id"],
                            execution_id=p["execution_id"],
                            catalog_id=cat_id,
                            command_id=p["cmd_id"],
                            step=p["step"],
                            tool_kind=p["tool_kind"],
                            context=p["ctx"],
                            meta=p["meta"],
                            parent_event_id=job.last_actionable_evt_id,
                            parent_execution_id=p_exec,
                            stage_id=p["meta"].get("stage_id"),
                            frame_id=p["meta"].get("frame_id"),
                            created_at=now,
                        ),
                    )
                await conn.commit()

    await _drain_batch_outbox()

    # 5. Parallel NATS publish.  Tuple is 5-wide:
    # ``(execution_id, evt_id, cmd_id, step, tool_kind)``.  The trailing
    # ``tool_kind`` drives the NATS subject derivation when pool
    # routing is enabled — see noetl/ai-meta#42 + the route_subject
    # helper in noetl.core.runtime.pool_routing.  Today the field is
    # captured but the subject stays single until the cutover env
    # flag flips.
    publish_items = [(p["execution_id"], p["evt_id"], p["cmd_id"], p["step"], p.get("tool_kind")) for p in prepared_commands]
    await _publish_commands_with_recovery(publish_items, server_url=server_url)

async def _process_accepted_batch(
    job: _BatchAcceptJob,
    timing_capture: Optional[dict] = None,
) -> int:
    """Run the batch's engine pass + command issuance.

    When ``timing_capture`` is supplied (the dispatcher passes a dict from
    ``_process_batch_job``), populate per-phase wall-clock measurements in
    milliseconds.  See noetl/ai-meta#29 for the profiling brief.  Phases
    captured at this layer:

      - ``pool_checkout_ms``: wall-clock for ``get_pool_connection`` to
        return a usable connection.  Reflects pool saturation.
      - ``lock_acquire_ms``: wall-clock for the
        ``pg_advisory_xact_lock(execution_id)`` SQL.  Reflects lock
        contention against other batches for the same execution.
      - ``engine_total_ms`` + ``state_load_ms``: populated by
        ``engine.handle_event`` itself via the same ``timing_capture``
        dict.  See that method's docstring for definitions.
      - ``issue_commands_ms``: wall-clock for ``_issue_commands_for_batch``.
      - ``commit_ms``: wall-clock for the transaction commit (measured as
        the time spent inside the ``engine_conn.transaction()`` __aexit__
        after ``engine.handle_event`` returns).
      - ``actionable_event``: ``True`` when ``last_actionable_event`` was
        non-None and the engine ran; ``False`` for batches that were
        accepted but had nothing actionable (the fast no-op path).
    """
    from .events import _invalidate_execution_state_cache
    commands = []
    engine = None
    if job.last_actionable_event:
        engine = get_engine()
        if timing_capture is not None:
            timing_capture["actionable_event"] = True
        pool_start = time.perf_counter()
        async with get_pool_connection() as engine_conn:
            if timing_capture is not None:
                timing_capture["pool_checkout_ms"] = round(
                    (time.perf_counter() - pool_start) * 1000, 3
                )
            tx_start = time.perf_counter()
            async with engine_conn.transaction():
                async with engine_conn.cursor() as cur:
                    await cur.execute(f"SET LOCAL statement_timeout = {int(_BATCH_PROCESSING_STATEMENT_TIMEOUT_MS)}"); await cur.execute(f"SET LOCAL idle_in_transaction_session_timeout = {int(_BATCH_PROCESSING_STATEMENT_TIMEOUT_MS)}")
                    lock_start = time.perf_counter()
                    await cur.execute("SELECT pg_advisory_xact_lock(%s)", (int(job.last_actionable_event.execution_id),))
                    if timing_capture is not None:
                        timing_capture["lock_acquire_ms"] = round(
                            (time.perf_counter() - lock_start) * 1000, 3
                        )
                    commands = await engine.handle_event(
                        job.last_actionable_event,
                        conn=engine_conn,
                        already_persisted=True,
                        timing_capture=timing_capture,
                    )
                    engine_done_ts = time.perf_counter()
            if timing_capture is not None:
                # Time between engine.handle_event returning and transaction
                # commit completing — captures COMMIT wall-clock (writes any
                # dirtied state JSONB + advisory-lock release + flush).
                timing_capture["commit_ms"] = round(
                    (time.perf_counter() - engine_done_ts) * 1000, 3
                )
                # Total time inside the engine_conn.transaction() block.
                timing_capture["transaction_ms"] = round(
                    (time.perf_counter() - tx_start) * 1000, 3
                )
    elif timing_capture is not None:
        timing_capture["actionable_event"] = False
    issue_start = time.perf_counter()
    try: await _issue_commands_for_batch(job, commands)
    except Exception as e:
        if engine and commands: await _invalidate_execution_state_cache(str(job.execution_id), reason=f"batch_command_issue_failed:{type(e).__name__}", engine=engine)
        raise
    finally:
        if timing_capture is not None:
            timing_capture["issue_commands_ms"] = round(
                (time.perf_counter() - issue_start) * 1000, 3
            )
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
    # Per-phase timing breakdown for noetl/ai-meta#29.  Populated by
    # ``_process_accepted_batch`` + ``engine.handle_event``.  Always-on,
    # low-overhead (~microseconds per perf_counter call).  Operators
    # can read the breakdown directly off the ``batch.completed``
    # event's ``context`` JSONB.
    timing_capture: dict = {}
    try:
        if _BATCH_PROCESSING_TIMEOUT_SECONDS > 0:
            cmd_gen = await asyncio.wait_for(
                _process_accepted_batch(job, timing_capture=timing_capture),
                timeout=_BATCH_PROCESSING_TIMEOUT_SECONDS,
            )
        else:
            cmd_gen = await _process_accepted_batch(job, timing_capture=timing_capture)
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
            "[BATCH-EVENTS] Slow async batch processing request_id=%s exec_id=%s event_count=%s p_sec=%.3f cmd_gen=%s timing=%s",
            job.request_id,
            job.execution_id,
            len(job.events),
            p_sec,
            cmd_gen,
            timing_capture,
        )
    completed_context: dict = {
        "request_id": job.request_id,
        "commands_generated": cmd_gen,
        "processing_ms": round(p_sec * 1000, 3),
    }
    if timing_capture:
        # Promote each captured phase into the event context.  Existing
        # consumers reading ``processing_ms`` / ``commands_generated``
        # see the same fields; new operators can now read
        # ``state_load_ms`` / ``engine_total_ms`` / ``pool_checkout_ms``
        # / ``lock_acquire_ms`` / ``issue_commands_ms`` / ``commit_ms``
        # / ``transaction_ms`` / ``actionable_event`` to localise
        # per-execution finalization cost.  See noetl/ai-meta#29.
        completed_context.update(timing_capture)
    await _persist_batch_status_event(
        job.execution_id,
        job.catalog_id,
        job.request_id,
        job.worker_id,
        job.idempotency_key,
        "batch.completed",
        "COMPLETED",
        completed_context,
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
                        # Log the full traceback before persisting the
                        # batch.failed event — `_persist_batch_failed_event`
                        # only records `str(e)` into the event payload, which
                        # loses the stack frame and makes regressions like
                        # noetl/ai-meta#36 (pyarrow type-inference choke on
                        # inline mixed-type rows) un-diagnosable without
                        # locally reproducing.  `execution_id` carried as a
                        # structured field per agents/rules/observability.md
                        # Principle 4.
                        logger.exception(
                            "[BATCH-EVENTS] Processing failed request_id=%s execution_id=%s",
                            grouped_job.request_id,
                            grouped_job.execution_id,
                        )
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
    return redact_keychain_values({"request_id": request_id, "execution_id": str(row["execution_id"]), "state": state, "status": row["status"], "error_code": ctx.get("error_code"), "message": ctx.get("message") or row.get("error"), "commands_generated": ctx.get("commands_generated"), "idempotency_key": meta.get("idempotency_key"), "updated_at": _iso_timestamp(row.get("created_at"))})

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
