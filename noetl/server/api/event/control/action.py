from __future__ import annotations

from typing import Any, Dict
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


async def handle_action_event(event: Dict[str, Any], et: str) -> None:
    """
    Handle action lifecycle events with retry logic integration.
    
    For action_error events, evaluates retry configuration and either:
    - Re-enqueues the task for retry with backoff delay
    - Marks the task as terminally failed if retry exhausted
    
    For action_completed events, proceeds with normal workflow advancement.
    """
    try:
        execution_id = event.get('execution_id')
        if not execution_id:
            return
        
        # Check if this is an error/failure event that might need retry
        if et in ['action_error', 'action_failed']:
            await _handle_action_error_with_retry(event)
        
        # Always trigger broker evaluation to advance workflow
        from ..processing import evaluate_broker_for_execution
        trig = str(event.get('trigger_event_id') or event.get('event_id') or '') or None
        await evaluate_broker_for_execution(str(execution_id), trigger_event_id=trig)
        
    except Exception:
        logger.debug("ACTION_CONTROL: Failed handling action event", exc_info=True)


async def _handle_action_error_with_retry(event: Dict[str, Any]) -> None:
    """
    Handle action error with retry logic.
    
    Evaluates retry configuration and decides whether to retry or fail terminally.
    """
    try:
        execution_id = event.get('execution_id')
        node_id = event.get('node_id')
        
        if not execution_id or not node_id:
            logger.warning("ACTION_CONTROL: Missing execution_id or node_id in error event")
            return
        
        logger.info(f"ACTION_CONTROL: Handling error for execution={execution_id} node={node_id}")
        
        # Get current queue entry
        queue_entry = await _get_queue_entry(execution_id, node_id)
        if not queue_entry:
            logger.warning(f"ACTION_CONTROL: No queue entry found for {execution_id}/{node_id}")
            return
        
        # Get retry configuration from playbook
        from ..processing.retry import get_retry_config_for_step
        retry_config = await get_retry_config_for_step(execution_id, node_id)
        
        if not retry_config:
            logger.info(f"ACTION_CONTROL: No retry configured for {node_id}, terminal failure")
            # No retry configured, this is a terminal failure
            # Broker will handle marking as failed
            return
        
        # Evaluate retry decision
        from ..processing.retry import RetryEvaluator, enqueue_retry, handle_retry_exhausted
        evaluator = RetryEvaluator()
        
        current_attempt = queue_entry.get('attempts', 0)
        should_retry, delay = await evaluator.should_retry(
            execution_id,
            node_id,
            event,
            retry_config,
            current_attempt
        )
        
        if should_retry and delay is not None:
            logger.info(f"ACTION_CONTROL: Retry approved for {node_id}, delay={delay}s")
            await enqueue_retry(execution_id, node_id, event, delay, queue_entry, retry_config)
        else:
            logger.warning(f"ACTION_CONTROL: Retry exhausted for {node_id}")
            await handle_retry_exhausted(execution_id, node_id, event, queue_entry, retry_config)
            
    except Exception as e:
        logger.error(f"ACTION_CONTROL: Error in retry handling: {e}", exc_info=True)


async def _get_queue_entry(execution_id: str, node_id: str) -> Dict[str, Any] | None:
    """Get queue entry for a specific execution and node."""
    try:
        from noetl.core.common import get_async_db_connection
        
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT 
                        queue_id, execution_id, catalog_id, node_id, node_name,
                        node_type, action, context, status, priority, attempts,
                        max_attempts, available_at, lease_until, worker_id,
                        created_at, updated_at
                    FROM noetl.queue
                    WHERE execution_id = %s AND node_id = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                """, (execution_id, node_id))
                
                row = await cur.fetchone()
                if not row:
                    return None
                
                return {
                    'queue_id': row[0],
                    'execution_id': row[1],
                    'catalog_id': row[2],
                    'node_id': row[3],
                    'node_name': row[4],
                    'node_type': row[5],
                    'action': row[6],
                    'context': row[7],
                    'status': row[8],
                    'priority': row[9],
                    'attempts': row[10],
                    'max_attempts': row[11],
                    'available_at': row[12],
                    'lease_until': row[13],
                    'worker_id': row[14],
                    'created_at': row[15],
                    'updated_at': row[16]
                }
    except Exception as e:
        logger.error(f"ACTION_CONTROL: Error getting queue entry: {e}", exc_info=True)
        return None
