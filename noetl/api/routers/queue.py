import json
from typing import Any
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from noetl.core.common import get_async_db_connection, snowflake_id_to_int, convert_snowflake_ids_for_api
from noetl.core.logger import setup_logger


logger = setup_logger(__name__, include_location=True)
router = APIRouter()
router = APIRouter(tags=["Queue"])

def normalize_execution_id(execution_id: str | int) -> int:
    """Normalize execution_id to integer for consistent database usage."""
    if isinstance(execution_id, int):
        return execution_id
    return snowflake_id_to_int(execution_id)

async def get_catalog_id_from_execution(execution_id: int) -> int:
    """Get catalog_id from the first event of an execution."""
    async with get_async_db_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT catalog_id FROM noetl.event WHERE execution_id = %s ORDER BY created_at LIMIT 1",
                (execution_id,)
            )
            row = await cur.fetchone()
            if row:
                return row[0]
            else:
                raise ValueError(f"No catalog_id found for execution {execution_id}")

@router.post("/queue/enqueue", response_class=JSONResponse)
async def enqueue_job(request: Request):
    """Enqueue a job into the noetl.queue table.
    Body: { execution_id, node_id, action, context?,@router.post("/queue/{queue_id}/heartbeat", response_class=JSONResponse)
async def heartbeat_job(queue_id: int, request: Request):riority?, max_attempts?, available_at? } (input_context supported for backward compatibility)
    """
    try:
        body = await request.json()
        execution_id = body.get("execution_id")
        node_id = body.get("node_id")
        action = body.get("action")
        context = body.get("context")
        if context is None:
            context = body.get("input_context", {})
        priority = int(body.get("priority", 0))
        max_attempts = int(body.get("max_attempts", 5))
        available_at = body.get("available_at")

        if not execution_id or not node_id or not action:
            raise HTTPException(status_code=400, detail="execution_id, node_id and action are required")

        # Convert execution_id from string to int for database storage
        execution_id_int = normalize_execution_id(execution_id)
        
        # Get catalog_id from the execution's first event
        catalog_id = await get_catalog_id_from_execution(execution_id_int)

        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO noetl.queue (execution_id, catalog_id, node_id, action, context, priority, max_attempts, available_at)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, COALESCE(%s::timestamptz, now()))
                    ON CONFLICT (execution_id, node_id) DO NOTHING
                    RETURNING queue_id
                    """,
                    (execution_id_int, catalog_id, node_id, action, json.dumps(context), priority, max_attempts, available_at)
                )
                row = await cur.fetchone()
                await conn.commit()
        return {"status": "ok", "id": row[0] if row else None}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error enqueueing job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue/lease", response_class=JSONResponse)
async def lease_job(request: Request):
    """Atomically lease a queued job for a worker.
    Body: { worker_id, lease_seconds? }
    Returns queued job or {status: 'empty'} when nothing available.
    """
    try:
        body = await request.json()
        worker_id = body.get("worker_id")
        lease_seconds = int(body.get("lease_seconds", 60))
        if not worker_id:
            raise HTTPException(status_code=400, detail="worker_id is required")

        async with get_async_db_connection() as conn:
            # return dict-like row for JSON friendliness
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    WITH cte AS (
                      SELECT queue_id FROM noetl.queue
                      WHERE status='queued' AND (available_at IS NULL OR available_at <= now())
                      ORDER BY priority DESC, queue_id
                      FOR UPDATE SKIP LOCKED
                      LIMIT 1
                    )
                    UPDATE noetl.queue q
                    SET status='leased',
                        worker_id=%s,
                        lease_until=now() + (%s || ' seconds')::interval,
                        last_heartbeat=now(),
                        attempts = q.attempts + 1
                    FROM cte
                    WHERE q.queue_id = cte.queue_id
                    RETURNING q.*;
                    """,
                    (worker_id, str(lease_seconds))
                )
                row = await cur.fetchone()
                await conn.commit()

        if not row:
            return {"status": "empty"}

        # ensure JSON serializable
        # Normalize context naming
        if row.get("context") is None and row.get("input_context") is not None:
            row["context"] = row.get("input_context")
        if row.get("context") is None:
            row["context"] = {}
        # Remove legacy key to standardize responses
        row.pop("input_context", None)
        return {"status": "ok", "job": row}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error leasing job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue/{queue_id}/complete", response_class=JSONResponse)
async def complete_job(queue_id: int):
    """Mark a job completed."""
    try:
        async with get_async_db_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "UPDATE noetl.queue SET status='done', lease_until = NULL WHERE queue_id = %s RETURNING queue_id, execution_id, context",
                    (queue_id,)
                )
                row = await cur.fetchone()
                await conn.commit()
        if not row:
            raise HTTPException(status_code=404, detail="job not found")
        
        logger.info(f"QUEUE_COMPLETION_DEBUG: Job {queue_id} completed for execution {row[1] if isinstance(row, tuple) else row.get('execution_id')}")
        # schedule broker evaluation best-effort
        try:
            exec_id = row[1] if isinstance(row, tuple) else row.get("execution_id")
            context = row[2] if isinstance(row, tuple) else row.get("context")
            
            # Check if this job has parent execution metadata (indicating it's part of a loop)
            parent_execution_id = None
            parent_step = None
            return_step = None
            if context:
                try:
                    import json
                    context_data = json.loads(context) if isinstance(context, str) else context
                    if isinstance(context_data, dict):
                        meta = context_data.get('_meta', {})
                        parent_execution_id = meta.get('parent_execution_id')
                        parent_step = meta.get('parent_step')
                        # Extract return_step from the queue.action when available (preferred)
                        # NOTE: We no longer access a cursor here because the initial transaction scope is closed.
                        # This value will be resolved later within a fresh DB connection below.
                        
                        # Legacy fallback: some older producers embed action JSON in input_context
                        if return_step is None:
                            try:
                                action_data = context_data.get('action')
                                if isinstance(action_data, str):
                                    try:
                                        action_json = json.loads(action_data)
                                        if isinstance(action_json, dict):
                                            return_step = action_json.get('with', {}).get('return_step')
                                    except json.JSONDecodeError as e:
                                        logger.debug(f"Failed to parse action_data as JSON: {e}")
                                    except Exception as e:
                                        logger.warning(f"Unexpected error parsing action_data: {e}")
                            except Exception as e:
                                logger.debug(f"Error extracting return_step from task: {e}")
                except Exception as e:
                    logger.debug(f"Error processing job context metadata: {e}")
            
            # If this is a child execution that completed, emit a mapping event to link results to parent loop
            if parent_execution_id and parent_step and parent_execution_id != exec_id:
                logger.info(f"COMPLETION_HANDLER: Child execution {exec_id} completed for parent {parent_execution_id} step {parent_step}")
                try:
                    # Get the final result from the child execution
                    from noetl.api.routers.event import get_event_service
                    from noetl.core.common import get_async_db_connection as get_db_conn
                    async with get_db_conn() as conn:
                        async with conn.cursor() as cur:
                            # Resolve return_step from the queue.action for the completed job (best-effort)
                            try:
                                await cur.execute("SELECT action FROM noetl.queue WHERE queue_id = %s", (queue_id,))
                                _act = await cur.fetchone()
                                _act_json = None
                                if _act:
                                    _act_val = _act[0] if isinstance(_act, tuple) else _act.get('action')
                                    if isinstance(_act_val, str) and _act_val.strip():
                                        try:
                                            _act_json = json.loads(_act_val)
                                        except Exception:
                                            _act_json = None
                                if isinstance(_act_json, dict):
                                    return_step = ((_act_json.get('with') or {}).get('return_step')
                                                   or _act_json.get('return_step')
                                                   or return_step)
                            except Exception:
                                pass
                            # Get the end step's return value, or fall back to meaningful results
                            result_row = None
                            # 0) Prefer execution_complete final result
                            await cur.execute(
                                """
                                SELECT result FROM noetl.event
                                WHERE execution_id = %s AND event_type = 'execution_complete'
                                ORDER BY created_at DESC
                                LIMIT 1
                                """,
                                (exec_id,)
                            )
                            result_row = await cur.fetchone()
                            # 1) Return step (if provided), require non-empty and not a control_step
                            if return_step:
                                await cur.execute(
                                    """
                                    SELECT result FROM noetl.event
                                    WHERE execution_id = %s
                                      AND node_name = %s
                                      AND event_type = 'action_completed'
                                      AND lower(status) IN ('completed','success')
                                      AND result IS NOT NULL
                                      AND result != '{}'
                                              AND NOT (result::text LIKE '%%"skipped": true%%')
                                              AND NOT (result::text LIKE '%%"reason": "control_step"%%')
                                    ORDER BY created_at DESC
                                    LIMIT 1
                                    """,
                                    (exec_id, return_step)
                                )
                                result_row = await cur.fetchone()

                            # 2) Common step names
                            if not result_row:
                                for step_name in ['evaluate_weather_step', 'evaluate_weather', 'alert_step', 'log_step']:
                                    await cur.execute(
                                        """
                                        SELECT result FROM noetl.event
                                        WHERE execution_id = %s
                                          AND node_name = %s
                                          AND event_type = 'action_completed'
                                          AND lower(status) IN ('completed','success')
                                          AND result IS NOT NULL
                                          AND result != '{}'
                                          AND NOT (result::text LIKE '%%"skipped": true%%')
                                          AND NOT (result::text LIKE '%%"reason": "control_step"%%')
                                        ORDER BY created_at DESC
                                        LIMIT 1
                                        """,
                                        (exec_id, step_name)
                                    )
                                    result_row = await cur.fetchone()
                                    if result_row:
                                        break

                            # 3) Any meaningful result
                            if not result_row:
                                await cur.execute(
                                    """
                                    SELECT result FROM noetl.event
                                    WHERE execution_id = %s
                                      AND event_type = 'action_completed'
                                      AND lower(status) IN ('completed','success')
                                      AND result IS NOT NULL
                                      AND result != '{}'
                                      AND NOT (result::text LIKE '%%"skipped": true%%')
                                      AND NOT (result::text LIKE '%%"reason": "control_step"%%')
                                    ORDER BY created_at DESC
                                    LIMIT 1
                                    """,
                                    (exec_id,)
                                )
                                result_row = await cur.fetchone()

                            # 4) Prefer explicit 'result' events if present
                            if not result_row:
                                await cur.execute(
                                    """
                                    SELECT result FROM noetl.event
                                    WHERE execution_id = %s
                                      AND event_type = 'result'
                                      AND lower(status) IN ('completed','success')
                                      AND result IS NOT NULL
                                      AND result != '{}'
                                    ORDER BY created_at DESC
                                    LIMIT 1
                                    """,
                                    (exec_id,)
                                )
                                result_row = await cur.fetchone()

                            # 5) As last fallback, try 'end' only if it has a meaningful result
                            if not result_row:
                                await cur.execute(
                                    """
                                    SELECT result FROM noetl.event
                                    WHERE execution_id = %s
                                      AND node_name = 'end'
                                      AND event_type = 'action_completed'
                                      AND lower(status) IN ('completed','success')
                                      AND result IS NOT NULL
                                      AND result != '{}'
                                      AND NOT (result::text LIKE '%%"skipped": true%%')
                                      AND NOT (result::text LIKE '%%"reason": "control_step"%%')
                                    ORDER BY created_at DESC
                                    LIMIT 1
                                    """,
                                    (exec_id,)
                                )
                                result_row = await cur.fetchone()
                            
                            child_result = None
                            if result_row:
                                result_data = result_row[0] if isinstance(result_row, tuple) else result_row.get('result')
                                try:
                                    child_result = json.loads(result_data) if isinstance(result_data, str) else result_data
                                    # Extract data if wrapped
                                    if isinstance(child_result, dict) and 'data' in child_result:
                                        child_result = child_result['data']
                                except Exception:
                                    pass
                            
                            # If no meaningful result found, fall back to the last result
                            if not child_result:
                                await cur.execute(
                                    """
                                    SELECT result FROM noetl.event
                                    WHERE execution_id = %s
                                      AND event_type = 'action_completed'
                                      AND lower(status) IN ('completed','success')
                                    ORDER BY created_at DESC
                                    LIMIT 1
                                    """,
                                    (exec_id,)
                                )
                                result_row = await cur.fetchone()
                                if result_row:
                                    result_data = result_row[0] if isinstance(result_row, tuple) else result_row.get('result')
                                    try:
                                        child_result = json.loads(result_data) if isinstance(result_data, str) else result_data
                                        # Extract data if wrapped
                                        if isinstance(child_result, dict) and 'data' in child_result:
                                            child_result = child_result['data']
                                    except Exception:
                                        pass
                            
                            # Find the iteration details by looking up the loop_iteration event for this child
                            await cur.execute(
                                """
                                SELECT node_id, iterator, current_index, current_item, loop_id, loop_name
                                FROM noetl.event
                                WHERE execution_id = %s
                                  AND event_type = 'loop_iteration'
                                  AND node_name = %s
                                  AND context LIKE %s
                                ORDER BY created_at DESC
                                LIMIT 1
                                """,
                                (parent_execution_id, parent_step, f'%"child_execution_id": "{exec_id}"%')
                            )
                            iter_row = await cur.fetchone()
                            iter_node_id = None
                            iterator_val = None
                            current_index_val = None
                            current_item_val = None
                            loop_id_val = None
                            loop_name_val = None
                            if iter_row:
                                # dict_row or tuple support
                                getv = (lambda k: iter_row.get(k)) if isinstance(iter_row, dict) else None
                                iter_node_id = (iter_row[0] if not isinstance(iter_row, dict) else getv('node_id'))
                                iterator_val = (iter_row[1] if not isinstance(iter_row, dict) else getv('iterator'))
                                current_index_val = (iter_row[2] if not isinstance(iter_row, dict) else getv('current_index'))
                                current_item_val = (iter_row[3] if not isinstance(iter_row, dict) else getv('current_item'))
                                loop_id_val = (iter_row[4] if not isinstance(iter_row, dict) else getv('loop_id'))
                                loop_name_val = (iter_row[5] if not isinstance(iter_row, dict) else getv('loop_name'))
                            
                            # Emit per-iteration result event with iter- pattern and loop metadata for aggregation logic to detect
                            await get_event_service().emit({
                                'execution_id': parent_execution_id,
                                'event_type': 'result',
                                'status': 'COMPLETED',
                                'node_id': iter_node_id or f'{parent_execution_id}-step-X-iter-{exec_id}',
                                'node_name': parent_step,
                                'node_type': 'task',
                                'result': child_result,
                                'iterator': iterator_val,
                                'current_index': current_index_val,
                                'current_item': current_item_val,
                                'loop_id': loop_id_val,
                                'loop_name': loop_name_val,
                                'context': {
                                    'child_execution_id': exec_id,
                                    'parent_step': parent_step,
                                    'return_step': return_step
                                }
                            })
                            logger.info(f"COMPLETION_HANDLER: Emitted action_completed for parent {parent_execution_id} step {parent_step} from child {exec_id} with result: {child_result}")
                            logger.debug(f"LOOP MAPPING: Emitted action_completed for parent {parent_execution_id} step {parent_step} from child {exec_id} with node_id {iter_node_id}")
                            
                            # If this was part of a loop, check if all iterations are completed now; if so, emit a final aggregated event.
                            try:
                                if parent_execution_id and parent_step:
                                    # Count expected iterations for this loop on the parent
                                    await cur.execute(
                                        """
                                        SELECT COUNT(*) FROM noetl.event
                                        WHERE execution_id = %s AND event_type = 'loop_iteration' AND node_name = %s
                                        """,
                                        (parent_execution_id, parent_step)
                                    )
                                    row_ct = await cur.fetchone()
                                    expected = (row_ct[0] if isinstance(row_ct, tuple) else row_ct.get('count')) if row_ct else 0
                                    # Count completed iteration mapping events so far
                                    await cur.execute(
                                        """
                                        SELECT COUNT(*) FROM noetl.event
                                        WHERE execution_id = %s AND node_name = %s AND event_type IN ('result','action_completed')
                                          AND node_id LIKE '%%-iter-%%' AND lower(status) IN ('completed','success')
                                          AND result IS NOT NULL AND result != '{}'
                                          AND NOT (result::text LIKE '%%"skipped": true%%')
                                          AND NOT (result::text LIKE '%%"reason": "control_step"%%')
                                        """,
                                        (parent_execution_id, parent_step)
                                    )
                                    row_done = await cur.fetchone()
                                    done = row_done[0] if row_done else 0
                                    # Guard: if a final aggregate already exists, skip
                                    await cur.execute(
                                        """
                                        SELECT COUNT(*) FROM noetl.event
                                        WHERE execution_id = %s AND event_type = 'action_completed' AND node_name = %s
                                          AND context::text LIKE '%%loop_completed%%' AND context::text LIKE '%%true%%'
                                        """,
                                        (parent_execution_id, parent_step)
                                    )
                                    row_final = await cur.fetchone()
                                    already_final = (row_final[0] if row_final else 0) > 0
                                    if expected > 0 and done >= expected and not already_final:
                                        # Collect results from each iteration mapping event
                                        await cur.execute(
                                            """
                                            SELECT result FROM noetl.event
                                            WHERE execution_id = %s AND node_name = %s AND event_type IN ('result','action_completed')
                                              AND node_id LIKE '%%-iter-%%' AND lower(status) IN ('completed','success')
                                              AND result IS NOT NULL AND result != '{}'
                                              AND NOT (result::text LIKE '%%"skipped": true%%')
                                              AND NOT (result::text LIKE '%%"reason": "control_step"%%')
                                            ORDER BY created_at
                                            """,
                                            (parent_execution_id, parent_step)
                                        )
                                        rows_res = await cur.fetchall()
                                        final_results = []
                                        for rr in rows_res or []:
                                            val = rr[0] if isinstance(rr, tuple) else rr.get('result')
                                            try:
                                                parsed = json.loads(val) if isinstance(val, str) else val
                                            except Exception:
                                                parsed = val
                                            if parsed is not None:
                                                final_results.append(parsed)
                                        # Emit a single final aggregated event (will be the last action_completed for city_loop)
                                        # Emit final aggregated action_completed for the loop
                                        await get_event_service().emit({
                                            'execution_id': parent_execution_id,
                                            'event_type': 'action_completed',
                                            'node_name': parent_step,
                                            'node_type': 'loop',
                                            'status': 'COMPLETED',
                                            'result': {
                                                'data': {
                                                    'results': final_results,
                                                    'result': final_results,
                                                    'count': len(final_results)
                                                },
                                                'results': final_results,
                                                'result': final_results,
                                                'count': len(final_results)
                                            },
                                            'context': {
                                                'loop_completed': True,
                                                'total_iterations': expected
                                            },
                                            # Attach loop metadata for downstream consumers
                                            'loop_id': f"{parent_execution_id}:{parent_step}",
                                            'loop_name': parent_step
                                        })
                                        # Also emit a 'result' marker event for robust detection
                                        await get_event_service().emit({
                                            'execution_id': parent_execution_id,
                                            'event_type': 'result',
                                            'node_name': parent_step,
                                            'node_type': 'loop',
                                            'status': 'COMPLETED',
                                            'result': {
                                                'data': {
                                                    'results': final_results,
                                                    'result': final_results,
                                                    'count': len(final_results)
                                                },
                                                'results': final_results,
                                                'result': final_results,
                                                'count': len(final_results)
                                            },
                                            'context': {
                                                'loop_completed': True,
                                                'total_iterations': expected
                                            },
                                            'loop_id': f"{parent_execution_id}:{parent_step}",
                                            'loop_name': parent_step
                                        })
                                        # Emit an explicit loop_completed marker event for broker/control logic
                                        try:
                                            await get_event_service().emit({
                                                'execution_id': parent_execution_id,
                                                'event_type': 'loop_completed',
                                                'node_name': parent_step,
                                                'node_type': 'loop_control',
                                                'status': 'COMPLETED',
                                                'result': {
                                                    'data': {
                                                        'results': final_results,
                                                        'result': final_results,
                                                        'count': len(final_results)
                                                    },
                                                    'results': final_results,
                                                    'result': final_results,
                                                    'count': len(final_results)
                                                },
                                                'context': {
                                                    'loop_completed': True,
                                                    'total_iterations': expected,
                                                    'aggregated_results': final_results
                                                },
                                                'loop_id': f"{parent_execution_id}:{parent_step}",
                                                'loop_name': parent_step
                                            })
                                        except Exception:
                                            logger.debug("Failed to emit loop_completed marker event", exc_info=True)
                                        logger.info(f"COMPLETION_HANDLER: Emitted final aggregated event for {parent_step} with {len(final_results)} results")
                                        # Best-effort: mark any parent iterator job as done now that aggregation is complete
                                        try:
                                            await cur.execute(
                                                """
                                                UPDATE noetl.queue
                                                SET status='done', lease_until=NULL
                                                WHERE execution_id = %s
                                                  AND node_id = %s
                                                  AND status = 'leased'
                                                """,
                                                (parent_execution_id, f"{parent_execution_id}:{parent_step}")
                                            )
                                            await conn.commit()
                                        except Exception:
                                            logger.debug("COMPLETION_HANDLER: Failed to mark parent iterator job done (best-effort)", exc_info=True)
                                        # Trigger broker to advance the parent after aggregate
                                        try:
                                            from noetl.api.routers.event import evaluate_broker_for_execution
                                            import asyncio
                                            if asyncio.get_event_loop().is_running():
                                                asyncio.create_task(evaluate_broker_for_execution(parent_execution_id))
                                            else:
                                                await evaluate_broker_for_execution(parent_execution_id)
                                        except Exception:
                                            logger.debug("Failed to schedule broker evaluation after aggregated event", exc_info=True)
                            except Exception:
                                logger.debug("Failed to emit aggregated loop completion from queue complete", exc_info=True)
                            
                except Exception:
                    logger.debug("Failed to emit loop mapping event", exc_info=True)
            
            if exec_id:
                import asyncio
                from noetl.api.routers.event import evaluate_broker_for_execution
                try:
                    if asyncio.get_event_loop().is_running():
                        asyncio.create_task(evaluate_broker_for_execution(exec_id))
                        # Also trigger parent execution evaluation if this was a loop task
                        if parent_execution_id and parent_execution_id != exec_id:
                            asyncio.create_task(evaluate_broker_for_execution(parent_execution_id))
                    else:
                        await evaluate_broker_for_execution(exec_id)
                        # Also trigger parent execution evaluation if this was a loop task
                        if parent_execution_id and parent_execution_id != exec_id:
                            await evaluate_broker_for_execution(parent_execution_id)
                except RuntimeError:
                    await evaluate_broker_for_execution(exec_id)
                    # Also trigger parent execution evaluation if this was a loop task
                    if parent_execution_id and parent_execution_id != exec_id:
                        await evaluate_broker_for_execution(parent_execution_id)
        except Exception:
            logger.debug("Failed to schedule evaluation from complete_job", exc_info=True)
        return {"status": "ok", "id": queue_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error completing job {queue_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue/{queue_id}/fail", response_class=JSONResponse)
async def fail_job(queue_id: int, request: Request):
    """Mark job failed; optionally reschedule if attempts < max_attempts.
    Body: { retry_delay_seconds?, retry? }
    If retry is explicitly false, mark the job as terminal 'dead' immediately.
    """
    try:
        body = await request.json()
        retry_delay = int(body.get("retry_delay_seconds", 60))
        retry = body.get("retry", True)
        async with get_async_db_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("SELECT attempts, max_attempts FROM noetl.queue WHERE queue_id = %s", (queue_id,))
                row = await cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="job not found")
                attempts = row.get("attempts", 0)
                max_attempts = row.get("max_attempts", 5)

                if retry is False:
                    # Caller indicates this failure should not be retried
                    await cur.execute("UPDATE noetl.queue SET status='dead' WHERE queue_id = %s RETURNING queue_id", (queue_id,))
                elif attempts >= max_attempts:
                    await cur.execute("UPDATE noetl.queue SET status='dead' WHERE queue_id = %s RETURNING queue_id", (queue_id,))
                else:
                    await cur.execute("UPDATE noetl.queue SET status='queued', available_at = now() + (%s || ' seconds')::interval WHERE queue_id = %s RETURNING queue_id", (str(retry_delay), queue_id,))
                updated = await cur.fetchone()
                await conn.commit()
        return {"status": "ok", "id": queue_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error failing job {queue_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue/{queue_id}/heartbeat", response_class=JSONResponse)
async def heartbeat_job(queue_id: int, request: Request):
    """Update heartbeat and optionally extend lease_until.
    Body: { worker_id?, extend_seconds? }
    """
    try:
        body = await request.json()
        worker_id = body.get("worker_id")
        extend = body.get("extend_seconds")
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                if extend:
                    await cur.execute("UPDATE noetl.queue SET last_heartbeat = now(), lease_until = now() + (%s || ' seconds')::interval WHERE queue_id = %s RETURNING queue_id", (str(int(extend)), queue_id))
                else:
                    await cur.execute("UPDATE noetl.queue SET last_heartbeat = now() WHERE queue_id = %s RETURNING queue_id", (queue_id,))
                row = await cur.fetchone()
                await conn.commit()
        if not row:
            raise HTTPException(status_code=404, detail="job not found")
        return {"status": "ok", "id": queue_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error heartbeating job {queue_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/queue", response_class=JSONResponse)
async def list_queue(status: str = None, execution_id: str = None, worker_id: str = None, limit: int = 100):
    try:
        filters = []
        params: list[Any] = []
        if status:
            filters.append("status = %s")
            params.append(status)
        if execution_id:
            filters.append("execution_id = %s")
            params.append(execution_id)
        if worker_id:
            filters.append("worker_id = %s")
            params.append(worker_id)
        where = f"WHERE {' AND '.join(filters)}" if filters else ''
        async with get_async_db_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(f"SELECT * FROM noetl.queue {where} ORDER BY priority DESC, queue_id LIMIT %s", params + [limit])
                rows = await cur.fetchall()
        for r in rows:
            if r.get('context') is None:
                r['context'] = {}
        return {"status": "ok", "items": rows}
    except Exception as e:
        logger.exception(f"Error listing queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/queue/size", response_class=JSONResponse)
async def queue_size(status: str = "queued"):
    """Return the number of jobs in the queue for a given status."""
    try:
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT count(*) FROM noetl.queue WHERE status = %s", (status,))
                row = await cur.fetchone()
        return {"status": "ok", "count": row[0] if row else 0}
    except Exception as e:
        logger.exception(f"Error fetching queue size: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Compatibility endpoint for legacy workers expecting /jobs/queue/size
@router.get("/jobs/queue/size", response_class=JSONResponse)
async def jobs_queue_size():
    return await queue_size(status="queued")



@router.post("/queue/reserve")
async def reserve_job(request: Request):
    body = await request.json()
    worker_id = body.get("worker_id")
    lease_seconds = int(body.get("lease_seconds", 60))
    if not worker_id:
        raise HTTPException(status_code=400, detail="worker_id required")
    async with get_async_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                WITH cte AS (
                  SELECT id FROM noetl.queue
                  WHERE status='queued' AND available_at <= now()
                  ORDER BY priority DESC, id
                  FOR UPDATE SKIP LOCKED
                  LIMIT 1
                )
                UPDATE noetl.queue q
                SET status='leased',
                    worker_id=%s,
                    lease_until=now() + (%s || ' seconds')::interval,
                    last_heartbeat=now(),
                    attempts = q.attempts + 1
                FROM cte
                WHERE q.id = cte.id
                RETURNING q.*;
                """,
                (worker_id, str(lease_seconds))
            )
            job = await cur.fetchone()
            await conn.commit()
    if not job:
        return {"job": None}
    if job.get("context") is None:
        job["context"] = {}
    return {"job": job}


@router.post("/queue/ack")
async def ack_job(request: Request):
    body = await request.json()
    queue_id = body.get("queue_id")
    worker_id = body.get("worker_id")
    if not queue_id or not worker_id:
        raise HTTPException(status_code=400, detail="queue_id, worker_id required")
    async with get_async_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT worker_id FROM noetl.queue WHERE queue_id = %s", (queue_id,))
            row = await cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="job not found")
            if row.get("worker_id") != worker_id:
                raise HTTPException(status_code=409, detail="worker mismatch")
            await cur.execute("UPDATE noetl.queue SET status='done', lease_until=NULL WHERE queue_id = %s", (queue_id,))
            await conn.commit()
    return {"ok": True}

@router.post("/queue/nack")
async def nack_job(request: Request):
    body = await request.json()
    queue_id = body.get("queue_id")
    worker_id = body.get("worker_id")
    retry_delay_seconds = int(body.get("retry_delay_seconds", 60))
    if not queue_id or not worker_id:
        raise HTTPException(status_code=400, detail="queue_id, worker_id required")
    async with get_async_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT worker_id, attempts, max_attempts FROM noetl.queue WHERE queue_id = %s", (queue_id,))
            row = await cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="job not found")
            if row.get("worker_id") != worker_id:
                raise HTTPException(status_code=409, detail="worker mismatch")
            attempts = row.get("attempts", 0)
            max_attempts = row.get("max_attempts", 5)
            if attempts >= max_attempts:
                await cur.execute("UPDATE noetl.queue SET status='dead' WHERE queue_id = %s", (queue_id,))
            else:
                await cur.execute(
                    "UPDATE noetl.queue SET status='queued', worker_id=NULL, lease_until=NULL, available_at = now() + (%s || ' seconds')::interval WHERE queue_id = %s",
                    (str(retry_delay_seconds), queue_id)
                )
            await conn.commit()
    return {"ok": True}

@router.post("/queue/reap-expired")
async def reap_expired_jobs():
    async with get_async_db_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE noetl.queue
                SET status='queued', worker_id=NULL, lease_until=NULL
                WHERE status='leased' AND lease_until IS NOT NULL AND lease_until < now()
                RETURNING id
                """
            )
            rows = await cur.fetchall()
            await conn.commit()
    return {"reclaimed": len(rows)}
