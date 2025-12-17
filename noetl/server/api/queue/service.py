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

from noetl.core.db.pool import get_pool_connection
from noetl.core.common import normalize_execution_id_for_db
from noetl.core.logger import setup_logger
from noetl.server.api.broker.service import EventService
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
    async def enqueue_job(
        execution_id: str | int,
        node_id: str,
        action: str,
        catalog_id: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None,
        input_context: Optional[Dict[str, Any]] = None,
        node_name: Optional[str] = None,
        node_type: Optional[str] = None,
        priority: int = 0,
        max_attempts: int = 5,
        available_at: Optional[Any] = None,
        parent_event_id: Optional[str] = None,
        parent_execution_id: Optional[str] = None,
        event_id: Optional[str] = None,
        queue_id: Optional[int] = None,
        status: str = "queued",
        metadata: Optional[Dict[str, Any]] = None
    ) -> EnqueueResponse:
        """
        Enqueue a job into the queue table.
        
        Args:
            execution_id: Execution ID
            node_id: Node ID (or step_id)
            action: Action to execute (JSON string)
            catalog_id: Catalog ID (if None, will query from EventService)
            context: Job context/input data
            input_context: Legacy field for context (backward compatibility)
            node_name: Node name (step name)
            node_type: Node type (step type)
            priority: Job priority (higher = more priority)
            max_attempts: Maximum retry attempts
            available_at: Timestamp when job becomes available (datetime or string)
            parent_event_id: Parent event ID that triggered this job
            parent_execution_id: Parent execution ID (for sub-playbook calls)
            event_id: Associated event ID
            queue_id: Pre-generated queue ID (if None, will auto-generate)
            status: Job status (default: "queued")
            
        Returns:
            EnqueueResponse with queue ID
        """
        # Handle backward compatibility for input_context
        if context is None:
            context = input_context or {}
        
        # Convert execution_id from string to int for database storage
        execution_id_int = QueueService.normalize_execution_id(execution_id)
        
        # Get catalog_id if not provided
        if catalog_id is None:
            catalog_id = await EventService.get_catalog_id_from_execution(execution_id_int)
        
        # Generate queue_id if not provided
        if queue_id is None:
            from noetl.core.db.pool import get_snowflake_id
            queue_id = await get_snowflake_id()
        
        # Handle available_at - convert to proper timestamp
        from datetime import datetime, timezone
        if available_at is None:
            available_at = datetime.now(timezone.utc)
        elif isinstance(available_at, str):
            # Keep as string for database conversion
            pass
        
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                # Build metadata for queue entry
                meta = {}
                if parent_event_id:
                    meta['parent_event_id'] = str(parent_event_id)
                if parent_execution_id:
                    meta['parent_execution_id'] = str(parent_execution_id)
                
                # Include iterator/execution metadata if provided
                if metadata:
                    meta.update(metadata)
                
                # Convert parent_execution_id to int if provided
                parent_execution_id_int = None
                if parent_execution_id:
                    try:
                        parent_execution_id_int = QueueService.normalize_execution_id(parent_execution_id)
                    except (ValueError, TypeError):
                        logger.warning(f"Invalid parent_execution_id: {parent_execution_id}, setting to None")
                
                # Build INSERT query with all fields including meta
                from psycopg.types.json import Json
                
                # DEBUG LOGGING
                logger.critical(f"DEBUG QUEUE: context type={type(context)}, is_dict={isinstance(context, dict)}")
                logger.critical(f"DEBUG QUEUE: meta type={type(meta)}, is_dict={isinstance(meta, dict) if meta else 'None'}")
                
                await cur.execute(
                    """
                    INSERT INTO noetl.queue (
                        queue_id, execution_id, catalog_id,
                        node_id, node_name, node_type,
                        action, context, status, priority,
                        attempts, max_attempts, available_at,
                        parent_execution_id, parent_event_id, event_id, meta, created_at, updated_at
                    ) VALUES (
                        %(queue_id)s, %(execution_id)s, %(catalog_id)s,
                        %(node_id)s, %(node_name)s, %(node_type)s,
                        %(action)s, %(context)s, %(status)s, %(priority)s,
                        %(attempts)s, %(max_attempts)s, %(available_at)s,
                        %(parent_execution_id)s, %(parent_event_id)s, %(event_id)s, %(meta)s, %(created_at)s, %(updated_at)s
                    )
                    ON CONFLICT (execution_id, node_id) DO NOTHING
                    RETURNING queue_id
                    """,
                    {
                        "queue_id": queue_id,
                        "execution_id": execution_id_int,
                        "catalog_id": catalog_id,
                        "node_id": node_id,
                        "node_name": node_name or node_id,
                        "node_type": node_type,
                        "action": action if isinstance(action, str) else json.dumps(action),
                        "context": Json(context) if isinstance(context, dict) else (Json({}) if context is None else context),
                        "status": status,
                        "priority": priority,
                        "attempts": 0,
                        "max_attempts": max_attempts,
                        "available_at": available_at,
                        "parent_event_id": parent_event_id,
                        "parent_execution_id": parent_execution_id_int,
                        "event_id": event_id,
                        "meta": Json(meta) if meta else None,
                        "created_at": datetime.now(timezone.utc),
                        "updated_at": datetime.now(timezone.utc)
                    }
                )
                row = await cur.fetchone()
                await conn.commit()
        
        return EnqueueResponse(
            status="ok",
            id=row["queue_id"] if row else queue_id
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
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
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
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
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
                    meta = context_data.get('noetl_meta', {})
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
                # Note: V2 NATS-based event system handles event sourcing
                
                async with get_pool_connection() as conn:
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
                        
                        # Note: V2 NATS-based event system handles per-iteration result events
                        # Workers emit events directly via the v2_worker_nats module
                        # ))
                        
                        logger.debug(f"Child execution {exec_id} result collected for parent {parent_execution_id}")
                        
                        logger.info(f"COMPLETION_HANDLER: Collected result for parent {parent_execution_id} step {parent_step} from child {exec_id}")
                        
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
        parent_execution_id: str,
        parent_step: str
    ):
        """
        Check if all iterations complete and emit aggregated result.
        
        Note: This function is not used with V2 NATS-based event system.
        V2 workers handle iteration aggregation and result collection directly.
        Kept for backward compatibility with V1 playbooks.
        """
        logger.debug(
            f"Aggregated result check (V1 compatibility only). "
            f"parent_execution_id={parent_execution_id}, parent_step={parent_step}"
        )
        # Not needed for V2 - workers handle iteration aggregation
        pass
    
    @staticmethod
    async def _schedule_broker_evaluation(
        exec_id: int,
        parent_execution_id: Optional[int]
    ):
        """Schedule broker evaluation for execution(s) - USE NEW ORCHESTRATOR FROM RUN PACKAGE."""
        try:
            from noetl.server.api.run import evaluate_execution
            
            if asyncio.get_event_loop().is_running():
                asyncio.create_task(evaluate_execution(str(exec_id)))
                if parent_execution_id and parent_execution_id != exec_id:
                    asyncio.create_task(evaluate_execution(str(parent_execution_id)))
            else:
                await evaluate_execution(str(exec_id))
                if parent_execution_id and parent_execution_id != exec_id:
                    await evaluate_execution(str(parent_execution_id))
        except RuntimeError:
            await evaluate_execution(str(exec_id))
            if parent_execution_id and parent_execution_id != exec_id:
                await evaluate_execution(str(parent_execution_id))
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
        
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
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
        Emit step_failed and playbook_failed events when a job permanently fails.
        
        Args:
            job_info: Job dictionary with execution_id, node_id, context, etc.
        """
        # Note: V2 NATS-based event system handles failure events via workers
        logger.debug(f"Processing failure events for execution_id={job_info.get('execution_id')}")
        
        try:
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
                async with get_pool_connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            """
                            SELECT error, result, stack_trace 
                            FROM noetl.event 
                            WHERE execution_id = %s AND node_name = %s AND event_type = 'action_failed'
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
            
            # Note: V2 NATS-based workers emit step_failed events directly
            # This logging serves as a fallback notification mechanism
            logger.warning(f"Step '{step_name}' failed in execution {execution_id}: {last_error}")
            logger.info(f"Failure events handled by V2 worker for execution {execution_id}")
            
        except Exception as e:
            logger.exception(f"Error in _emit_final_failure_events: {e}")
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
        async with get_pool_connection() as conn:
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
        
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
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
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT count(*) as count FROM noetl.queue WHERE status = %s",
                    (status,)
                )
                row = await cur.fetchone()
                count = row["count"] if row else 0
        
        return QueueSizeResponse(status="ok", count=count)
    
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
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    WITH cte AS (
                      SELECT queue_id FROM noetl.queue
                      WHERE status IN ('queued', 'retry') AND available_at <= now()
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
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
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
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
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
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE noetl.queue
                    SET status='queued', worker_id=NULL, lease_until=NULL
                    WHERE status='leased' AND lease_until IS NOT NULL AND lease_until < now()
                    RETURNING queue_id
                    """
                )
                rows = await cur.fetchall()
                await conn.commit()
        
        return ReapResponse(reclaimed=len(rows))

