"""
NoETL Queue API Service - Business logic for queue operations.

Handles:
- Job enqueuing and leasing
- Job completion with loop result mapping
- Job failure and retry logic
- Heartbeat and lease management
- Queue listing and statistics
- Expired job reclamation
"""

import json
import asyncio
from typing import Any, Dict, List, Optional, Tuple
from psycopg.rows import dict_row

from noetl.core.common import (
    get_async_db_connection,
    normalize_execution_id_for_db
)
from noetl.core.logger import setup_logger
from .schema import (
    EnqueueResponse,
    LeaseResponse,
    CompleteResponse,
    FailResponse,
    HeartbeatResponse,
    QueueListResponse,
    QueueSizeResponse,
    ReserveResponse,
    AckResponse,
    NackResponse,
    ReapResponse
)

logger = setup_logger(__name__, include_location=True)


class QueueService:
    """Service for queue management and job orchestration."""
    
    @staticmethod
    def normalize_execution_id(execution_id: str | int) -> int:
        """
        Normalize execution_id to integer for consistent database usage.
        
        Args:
            execution_id: String or integer Snowflake ID
            
        Returns:
            Integer representation of the execution_id
            
        Raises:
            ValueError: If execution_id cannot be converted to a valid integer
        """
        return normalize_execution_id_for_db(execution_id)
    
    @staticmethod
    async def get_catalog_id_from_execution(execution_id: int) -> int:
        """
        Get catalog_id from the first event of an execution.
        
        Args:
            execution_id: Execution ID
            
        Returns:
            Catalog ID
            
        Raises:
            ValueError: If no catalog_id found
        """
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
    
    @staticmethod
    async def enqueue_job(
        execution_id: str | int,
        node_id: str,
        action: str,
        context: Optional[Dict[str, Any]] = None,
        input_context: Optional[Dict[str, Any]] = None,
        priority: int = 0,
        max_attempts: int = 5,
        available_at: Optional[str] = None
    ) -> EnqueueResponse:
        """
        Enqueue a job into the queue table.
        
        Args:
            execution_id: Execution ID
            node_id: Node ID
            action: Action to execute
            context: Job context/input data
            input_context: Legacy field for context (backward compatibility)
            priority: Job priority (higher = more priority)
            max_attempts: Maximum retry attempts
            available_at: Timestamp when job becomes available
            
        Returns:
            EnqueueResponse with queue ID
        """
        # Handle backward compatibility for input_context
        if context is None:
            context = input_context or {}
        
        # Convert execution_id from string to int for database storage
        execution_id_int = QueueService.normalize_execution_id(execution_id)
        
        # Get catalog_id from the execution's first event
        catalog_id = await QueueService.get_catalog_id_from_execution(execution_id_int)
        
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
        
        return EnqueueResponse(
            status="ok",
            id=row[0] if row else None
        )
    
    @staticmethod
    async def lease_job(worker_id: str, lease_seconds: int = 60) -> LeaseResponse:
        """
        Atomically lease a queued job for a worker.
        
        Args:
            worker_id: Worker ID
            lease_seconds: Lease duration in seconds
            
        Returns:
            LeaseResponse with job details or empty status
        """
        async with get_async_db_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    WITH cte AS (
                      SELECT queue_id FROM noetl.queue
                      WHERE status IN ('queued', 'retry') AND (available_at IS NULL OR available_at <= now())
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
            return LeaseResponse(status="empty", job=None)
        
        # Normalize context naming
        if row.get("context") is None and row.get("input_context") is not None:
            row["context"] = row.get("input_context")
        if row.get("context") is None:
            row["context"] = {}
        # Remove legacy key to standardize responses
        row.pop("input_context", None)
        
        return LeaseResponse(status="ok", job=row)
    
    @staticmethod
    async def complete_job(queue_id: int) -> CompleteResponse:
        """
        Mark a job completed and trigger broker evaluation.
        
        This method handles complex loop result mapping logic, including:
        - Extracting child execution results
        - Emitting per-iteration result events
        - Aggregating final loop results when all iterations complete
        - Triggering parent execution broker evaluation
        
        Args:
            queue_id: Queue ID
            
        Returns:
            CompleteResponse with status
        """
        async with get_async_db_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "UPDATE noetl.queue SET status='done', lease_until = NULL WHERE queue_id = %s RETURNING queue_id, execution_id, context",
                    (queue_id,)
                )
                row = await cur.fetchone()
                await conn.commit()
        
        if not row:
            raise ValueError("job not found")
        
        exec_id = row[1] if isinstance(row, tuple) else row.get("execution_id")
        context = row[2] if isinstance(row, tuple) else row.get("context")
        
        logger.info(f"QUEUE_COMPLETION_DEBUG: Job {queue_id} completed for execution {exec_id}")
        
        # Handle loop result mapping (if this is a child execution)
        parent_execution_id, parent_step = await QueueService._handle_loop_result_mapping(
            queue_id, exec_id, context
        )
        
        # Schedule broker evaluation
        await QueueService._schedule_broker_evaluation(exec_id, parent_execution_id)
        
        return CompleteResponse(status="ok", id=queue_id)
    
    @staticmethod
    async def _handle_loop_result_mapping(
        queue_id: int,
        exec_id: int,
        context: Any
    ) -> Tuple[Optional[int], Optional[str]]:
        """
        Handle loop result mapping for child executions.
        
        Returns:
            Tuple of (parent_execution_id, parent_step)
        """
        parent_execution_id = None
        parent_step = None
        return_step = None
        
        # Check if this job has parent execution metadata (indicating it's part of a loop)
        if context:
            try:
                context_data = json.loads(context) if isinstance(context, str) else context
                if isinstance(context_data, dict):
                    meta = context_data.get('_meta', {})
                    parent_execution_id = meta.get('parent_execution_id')
                    parent_step = meta.get('parent_step')
                    
                    # Extract return_step from legacy action data
                    try:
                        action_data = context_data.get('action')
                        if isinstance(action_data, str):
                            try:
                                action_json = json.loads(action_data)
                                if isinstance(action_json, dict):
                                    return_step = action_json.get('with', {}).get('return_step')
                            except json.JSONDecodeError:
                                pass
                    except Exception as e:
                        logger.debug(f"Error extracting return_step from task: {e}")
            except Exception as e:
                logger.debug(f"Error processing job context metadata: {e}")
        
        # If this is a child execution, emit mapping events
        if parent_execution_id and parent_step and parent_execution_id != exec_id:
            logger.info(f"COMPLETION_HANDLER: Child execution {exec_id} completed for parent {parent_execution_id} step {parent_step}")
            try:
                from noetl.server.api.event import get_event_service
                
                async with get_async_db_connection() as conn:
                    async with conn.cursor() as cur:
                        # Resolve return_step from queue.action
                        return_step = await QueueService._resolve_return_step(cur, queue_id, return_step)
                        
                        # Get child execution result
                        child_result = await QueueService._get_child_execution_result(
                            cur, exec_id, return_step
                        )
                        
                        # Get iteration details
                        iter_data = await QueueService._get_iteration_data(
                            cur, parent_execution_id, parent_step, exec_id
                        )
                        
                        # Emit per-iteration result event
                        await get_event_service().emit({
                            'execution_id': parent_execution_id,
                            'event_type': 'result',
                            'status': 'COMPLETED',
                            'node_id': iter_data['node_id'],
                            'node_name': parent_step,
                            'node_type': 'task',
                            'result': child_result,
                            'iterator': iter_data.get('iterator'),
                            'current_index': iter_data.get('current_index'),
                            'current_item': iter_data.get('current_item'),
                            'loop_id': iter_data.get('loop_id'),
                            'loop_name': iter_data.get('loop_name'),
                            'context': {
                                'child_execution_id': exec_id,
                                'parent_step': parent_step,
                                'return_step': return_step
                            }
                        })
                        
                        logger.info(f"COMPLETION_HANDLER: Emitted action_completed for parent {parent_execution_id} step {parent_step} from child {exec_id}")
                        
                        # Check if all iterations are complete and emit aggregated result
                        await QueueService._check_and_emit_aggregated_result(
                            cur, conn, parent_execution_id, parent_step
                        )
            except Exception:
                logger.debug("Failed to emit loop mapping event", exc_info=True)
        
        return parent_execution_id, parent_step
    
    @staticmethod
    async def _resolve_return_step(cur, queue_id: int, current_return_step: Optional[str]) -> Optional[str]:
        """Resolve return_step from queue.action."""
        try:
            await cur.execute("SELECT action FROM noetl.queue WHERE queue_id = %s", (queue_id,))
            _act = await cur.fetchone()
            if _act:
                _act_val = _act[0] if isinstance(_act, tuple) else _act.get('action')
                if isinstance(_act_val, str) and _act_val.strip():
                    try:
                        _act_json = json.loads(_act_val)
                        if isinstance(_act_json, dict):
                            return (
                                (_act_json.get('with') or {}).get('return_step') or
                                _act_json.get('return_step') or
                                current_return_step
                            )
                    except Exception:
                        pass
        except Exception:
            pass
        return current_return_step
    
    @staticmethod
    async def _get_child_execution_result(
        cur,
        exec_id: int,
        return_step: Optional[str]
    ) -> Any:
        """Get the final result from a child execution."""
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
        
        # 1) Return step (if provided)
        if not result_row and return_step:
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
        
        # 2-5) Various fallback strategies
        if not result_row:
            result_row = await QueueService._find_meaningful_result(cur, exec_id)
        
        # Parse result
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
        
        return child_result
    
    @staticmethod
    async def _find_meaningful_result(cur, exec_id: int):
        """Find a meaningful result using various fallback strategies."""
        # Common step names
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
                return result_row
        
        # Any meaningful result
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
        return await cur.fetchone()
    
    @staticmethod
    async def _get_iteration_data(
        cur,
        parent_execution_id: int,
        parent_step: str,
        exec_id: int
    ) -> Dict[str, Any]:
        """Get iteration details from loop_iteration event."""
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
        
        iter_data = {
            'node_id': f'{parent_execution_id}-step-X-iter-{exec_id}'
        }
        
        if iter_row:
            getv = (lambda k: iter_row.get(k)) if isinstance(iter_row, dict) else None
            iter_data['node_id'] = (iter_row[0] if not isinstance(iter_row, dict) else getv('node_id'))
            iter_data['iterator'] = (iter_row[1] if not isinstance(iter_row, dict) else getv('iterator'))
            iter_data['current_index'] = (iter_row[2] if not isinstance(iter_row, dict) else getv('current_index'))
            iter_data['current_item'] = (iter_row[3] if not isinstance(iter_row, dict) else getv('current_item'))
            iter_data['loop_id'] = (iter_row[4] if not isinstance(iter_row, dict) else getv('loop_id'))
            iter_data['loop_name'] = (iter_row[5] if not isinstance(iter_row, dict) else getv('loop_name'))
        
        return iter_data
    
    @staticmethod
    async def _check_and_emit_aggregated_result(
        cur,
        conn,
        parent_execution_id: int,
        parent_step: str
    ):
        """Check if all iterations complete and emit aggregated result."""
        try:
            # Count expected iterations
            await cur.execute(
                """
                SELECT COUNT(*) FROM noetl.event
                WHERE execution_id = %s AND event_type = 'loop_iteration' AND node_name = %s
                """,
                (parent_execution_id, parent_step)
            )
            row_ct = await cur.fetchone()
            expected = (row_ct[0] if isinstance(row_ct, tuple) else row_ct.get('count')) if row_ct else 0
            
            # Count completed iterations
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
            
            # Check if final aggregate already exists
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
                from noetl.server.api.event import get_event_service
                
                # Collect results from each iteration
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
                
                result_data = {
                    'data': {
                        'results': final_results,
                        'result': final_results,
                        'count': len(final_results)
                    },
                    'results': final_results,
                    'result': final_results,
                    'count': len(final_results)
                }
                
                # Emit final aggregated action_completed
                await get_event_service().emit({
                    'execution_id': parent_execution_id,
                    'event_type': 'action_completed',
                    'node_name': parent_step,
                    'node_type': 'loop',
                    'status': 'COMPLETED',
                    'result': result_data,
                    'context': {
                        'loop_completed': True,
                        'total_iterations': expected
                    },
                    'loop_id': f"{parent_execution_id}:{parent_step}",
                    'loop_name': parent_step
                })
                
                # Emit result marker event
                await get_event_service().emit({
                    'execution_id': parent_execution_id,
                    'event_type': 'result',
                    'node_name': parent_step,
                    'node_type': 'loop',
                    'status': 'COMPLETED',
                    'result': result_data,
                    'context': {
                        'loop_completed': True,
                        'total_iterations': expected
                    },
                    'loop_id': f"{parent_execution_id}:{parent_step}",
                    'loop_name': parent_step
                })
                
                # Emit loop_completed marker
                try:
                    await get_event_service().emit({
                        'execution_id': parent_execution_id,
                        'event_type': 'loop_completed',
                        'node_name': parent_step,
                        'node_type': 'loop_control',
                        'status': 'COMPLETED',
                        'result': result_data,
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
                
                # Mark parent iterator job as done
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
                    logger.debug("COMPLETION_HANDLER: Failed to mark parent iterator job done", exc_info=True)
                
                # Trigger broker for parent
                try:
                    from noetl.server.api.event import evaluate_broker_for_execution
                    if asyncio.get_event_loop().is_running():
                        asyncio.create_task(evaluate_broker_for_execution(parent_execution_id))
                    else:
                        await evaluate_broker_for_execution(parent_execution_id)
                except Exception:
                    logger.debug("Failed to schedule broker evaluation after aggregated event", exc_info=True)
        except Exception:
            logger.debug("Failed to emit aggregated loop completion", exc_info=True)
    
    @staticmethod
    async def _schedule_broker_evaluation(
        exec_id: int,
        parent_execution_id: Optional[int]
    ):
        """Schedule broker evaluation for execution(s)."""
        try:
            from noetl.server.api.event import evaluate_broker_for_execution
            
            if asyncio.get_event_loop().is_running():
                asyncio.create_task(evaluate_broker_for_execution(exec_id))
                if parent_execution_id and parent_execution_id != exec_id:
                    asyncio.create_task(evaluate_broker_for_execution(parent_execution_id))
            else:
                await evaluate_broker_for_execution(exec_id)
                if parent_execution_id and parent_execution_id != exec_id:
                    await evaluate_broker_for_execution(parent_execution_id)
        except RuntimeError:
            await evaluate_broker_for_execution(exec_id)
            if parent_execution_id and parent_execution_id != exec_id:
                await evaluate_broker_for_execution(parent_execution_id)
        except Exception:
            logger.debug("Failed to schedule evaluation from complete_job", exc_info=True)
    
    @staticmethod
    async def fail_job(
        queue_id: int,
        retry_delay_seconds: int = 60,
        retry: bool = True
    ) -> FailResponse:
        """
        Mark job failed; optionally reschedule if attempts < max_attempts.
        
        Args:
            queue_id: Queue ID
            retry_delay_seconds: Delay before retry in seconds
            retry: Whether to retry the job
            
        Returns:
            FailResponse with status
        """
        job_is_dead = False
        job_info = None
        
        async with get_async_db_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                # Get job info including execution context
                await cur.execute(
                    "SELECT queue_id, execution_id, node_id, attempts, max_attempts, context, catalog_id FROM noetl.queue WHERE queue_id = %s",
                    (queue_id,)
                )
                row = await cur.fetchone()
                if not row:
                    raise ValueError("job not found")
                
                job_info = row
                attempts = row.get("attempts", 0)
                max_attempts = row.get("max_attempts", 5)
                
                if retry is False:
                    # Caller indicates this failure should not be retried
                    await cur.execute(
                        "UPDATE noetl.queue SET status='dead' WHERE queue_id = %s RETURNING queue_id",
                        (queue_id,)
                    )
                    job_is_dead = True
                elif attempts >= max_attempts:
                    await cur.execute(
                        "UPDATE noetl.queue SET status='dead' WHERE queue_id = %s RETURNING queue_id",
                        (queue_id,)
                    )
                    job_is_dead = True
                else:
                    # Set status to 'retry' (not 'queued') to distinguish retry attempts from initial queue
                    await cur.execute(
                        "UPDATE noetl.queue SET status='retry', available_at = now() + (%s || ' seconds')::interval WHERE queue_id = %s RETURNING queue_id",
                        (str(retry_delay_seconds), queue_id)
                    )
                await cur.fetchone()
                await conn.commit()
        
        # Emit failure events if job is permanently dead
        if job_is_dead and job_info:
            logger.info(f"Job {queue_id} is dead, emitting final failure events")
            try:
                await QueueService._emit_final_failure_events(job_info)
            except Exception as e:
                logger.warning(f"Failed to emit final failure events for job {queue_id}: {e}", exc_info=True)
        
        return FailResponse(status="ok", id=queue_id)
    
    @staticmethod
    async def _emit_final_failure_events(job_info: Dict[str, Any]) -> None:
        """
        Emit step_failed and execution_failed events when a job permanently fails.
        
        Args:
            job_info: Job dictionary with execution_id, node_id, context, etc.
        """
        try:
            from noetl.server.api.event import get_event_service
            import json
            
            execution_id = job_info.get("execution_id")
            node_id = job_info.get("node_id")
            catalog_id = job_info.get("catalog_id")
            context = job_info.get("context") or {}
            
            if isinstance(context, str):
                try:
                    context = json.loads(context)
                except:
                    context = {}
            
            step_name = context.get("step_name", "unknown")
            
            # Get the last action_error event for this step to extract error details
            last_error = None
            last_error_result = None
            
            try:
                async with get_async_db_connection() as conn:
                    async with conn.cursor(row_factory=dict_row) as cur:
                        await cur.execute(
                            """
                            SELECT error, result, traceback 
                            FROM noetl.event 
                            WHERE execution_id = %s AND node_name = %s AND event_type = 'action_error'
                            ORDER BY created_at DESC 
                            LIMIT 1
                            """,
                            (execution_id, step_name)
                        )
                        error_row = await cur.fetchone()
                        if error_row:
                            last_error = error_row.get("error") or "Task failed after all retry attempts"
                            last_error_result = error_row.get("result")
            except Exception as e:
                logger.warning(f"Failed to fetch last error for step {step_name}: {e}")
                last_error = "Task failed after all retry attempts"
            
            if not last_error:
                last_error = "Task failed after all retry attempts"
            
            # Emit step_failed event
            event_service = get_event_service()
            step_failed_payload = {
                "execution_id": execution_id,
                "catalog_id": catalog_id,
                "event_type": "step_failed",
                "status": "FAILED",
                "node_id": node_id,
                "node_name": step_name,
                "node_type": "step",
                "error": last_error,
                "result": last_error_result or {},
            }
            
            await event_service.emit(step_failed_payload)
            logger.info(f"Emitted step_failed event for step '{step_name}' in execution {execution_id}")
            
            # Emit execution_failed event
            execution_failed_payload = {
                "execution_id": execution_id,
                "catalog_id": catalog_id,
                "event_type": "execution_failed",
                "status": "FAILED",
                "node_id": execution_id,
                "node_name": step_name,
                "node_type": "execution",
                "error": f"Execution failed at step '{step_name}': {last_error}",
                "result": {"failed_step": step_name, "reason": last_error},
            }
            
            await event_service.emit(execution_failed_payload)
            logger.info(f"Emitted execution_failed event for execution {execution_id}")
        except Exception as e:
            logger.error(f"Error in _emit_final_failure_events: {e}", exc_info=True)
            raise
    
    @staticmethod
    async def heartbeat_job(
        queue_id: int,
        worker_id: Optional[str] = None,
        extend_seconds: Optional[int] = None
    ) -> HeartbeatResponse:
        """
        Update heartbeat and optionally extend lease_until.
        
        Args:
            queue_id: Queue ID
            worker_id: Worker ID
            extend_seconds: Extend lease by this many seconds
            
        Returns:
            HeartbeatResponse with status
        """
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                if extend_seconds:
                    await cur.execute(
                        "UPDATE noetl.queue SET last_heartbeat = now(), lease_until = now() + (%s || ' seconds')::interval WHERE queue_id = %s RETURNING queue_id",
                        (str(int(extend_seconds)), queue_id)
                    )
                else:
                    await cur.execute(
                        "UPDATE noetl.queue SET last_heartbeat = now() WHERE queue_id = %s RETURNING queue_id",
                        (queue_id,)
                    )
                row = await cur.fetchone()
                await conn.commit()
        
        if not row:
            raise ValueError("job not found")
        
        return HeartbeatResponse(status="ok", id=queue_id)
    
    @staticmethod
    async def list_queue(
        status: Optional[str] = None,
        execution_id: Optional[str] = None,
        worker_id: Optional[str] = None,
        limit: int = 100
    ) -> QueueListResponse:
        """
        List queue items with optional filtering.
        
        Args:
            status: Filter by status
            execution_id: Filter by execution ID
            worker_id: Filter by worker ID
            limit: Maximum results
            
        Returns:
            QueueListResponse with items
        """
        filters = []
        params: List[Any] = []
        
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
                await cur.execute(
                    f"SELECT * FROM noetl.queue {where} ORDER BY priority DESC, queue_id LIMIT %s",
                    params + [limit]
                )
                rows = await cur.fetchall()
        
        for r in rows:
            if r.get('context') is None:
                r['context'] = {}
        
        return QueueListResponse(status="ok", items=rows)
    
    @staticmethod
    async def queue_size(status: str = "queued") -> QueueSizeResponse:
        """
        Get the number of jobs in the queue for a given status.
        
        Args:
            status: Status to count
            
        Returns:
            QueueSizeResponse with count
        """
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT count(*) FROM noetl.queue WHERE status = %s",
                    (status,)
                )
                row = await cur.fetchone()
        
        return QueueSizeResponse(status="ok", count=row[0] if row else 0)
    
    @staticmethod
    async def reserve_job(worker_id: str, lease_seconds: int = 60) -> ReserveResponse:
        """
        Reserve a job (alternative to lease with different table structure).
        
        Args:
            worker_id: Worker ID
            lease_seconds: Lease duration in seconds
            
        Returns:
            ReserveResponse with job details
        """
        async with get_async_db_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    WITH cte AS (
                      SELECT id FROM noetl.queue
                      WHERE status IN ('queued', 'retry') AND available_at <= now()
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
            return ReserveResponse(job=None)
        
        if job.get("context") is None:
            job["context"] = {}
        
        return ReserveResponse(job=job)
    
    @staticmethod
    async def ack_job(queue_id: int, worker_id: str) -> AckResponse:
        """
        Acknowledge job completion.
        
        Args:
            queue_id: Queue ID
            worker_id: Worker ID
            
        Returns:
            AckResponse with status
        """
        async with get_async_db_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "SELECT worker_id FROM noetl.queue WHERE queue_id = %s",
                    (queue_id,)
                )
                row = await cur.fetchone()
                
                if not row:
                    raise ValueError("job not found")
                if row.get("worker_id") != worker_id:
                    raise ValueError("worker mismatch")
                
                await cur.execute(
                    "UPDATE noetl.queue SET status='done', lease_until=NULL WHERE queue_id = %s",
                    (queue_id,)
                )
                await conn.commit()
        
        return AckResponse(ok=True)
    
    @staticmethod
    async def nack_job(
        queue_id: int,
        worker_id: str,
        retry_delay_seconds: int = 60
    ) -> NackResponse:
        """
        Negative acknowledgment - job failed but can retry.
        
        Args:
            queue_id: Queue ID
            worker_id: Worker ID
            retry_delay_seconds: Delay before retry in seconds
            
        Returns:
            NackResponse with status
        """
        async with get_async_db_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "SELECT worker_id, attempts, max_attempts FROM noetl.queue WHERE queue_id = %s",
                    (queue_id,)
                )
                row = await cur.fetchone()
                
                if not row:
                    raise ValueError("job not found")
                if row.get("worker_id") != worker_id:
                    raise ValueError("worker mismatch")
                
                attempts = row.get("attempts", 0)
                max_attempts = row.get("max_attempts", 5)
                
                if attempts >= max_attempts:
                    await cur.execute(
                        "UPDATE noetl.queue SET status='dead' WHERE queue_id = %s",
                        (queue_id,)
                    )
                else:
                    await cur.execute(
                        "UPDATE noetl.queue SET status='queued', worker_id=NULL, lease_until=NULL, available_at = now() + (%s || ' seconds')::interval WHERE queue_id = %s",
                        (str(retry_delay_seconds), queue_id)
                    )
                await conn.commit()
        
        return NackResponse(ok=True)
    
    @staticmethod
    async def reap_expired_jobs() -> ReapResponse:
        """
        Reclaim expired leased jobs back to queued status.
        
        Returns:
            ReapResponse with count of reclaimed jobs
        """
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
        
        return ReapResponse(reclaimed=len(rows))
