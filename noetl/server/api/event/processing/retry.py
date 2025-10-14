"""
Server-side retry logic for event-driven task execution.

This module evaluates retry decisions based on task results reported via events
and coordinates retry attempts through the queue system.
"""

import json
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from jinja2 import Environment, Template

from noetl.core.logger import setup_logger
from noetl.core.common import get_async_db_connection

logger = setup_logger(__name__, include_location=True)


class RetryEvaluator:
    """Evaluates retry decisions based on event results and retry configuration."""
    
    def __init__(self):
        """Initialize retry evaluator."""
        self.jinja_env = Environment()
    
    async def should_retry(
        self,
        execution_id: str,
        node_id: str,
        event: Dict[str, Any],
        retry_config: Dict[str, Any],
        current_attempt: int
    ) -> Tuple[bool, Optional[float]]:
        """
        Determine if a task should be retried based on its result event.
        
        Args:
            execution_id: Execution ID
            node_id: Step/node ID
            event: Event data from action_error or action_completed
            retry_config: Retry configuration from playbook
            current_attempt: Current attempt number (1-indexed)
            
        Returns:
            Tuple of (should_retry: bool, delay_seconds: Optional[float])
        """
        logger.info(f"Evaluating retry for execution={execution_id} node={node_id} attempt={current_attempt}")
        
        # Check max attempts
        max_attempts = retry_config.get('max_attempts', 3)
        if current_attempt >= max_attempts:
            logger.info(f"Max attempts ({max_attempts}) reached, no retry")
            return False, None
        
        # Build context for condition evaluation
        eval_context = self._build_evaluation_context(event, current_attempt, execution_id, node_id)
        
        # Check stop condition first (overrides retry)
        if 'stop_when' in retry_config:
            should_stop = await self._evaluate_condition(
                retry_config['stop_when'],
                eval_context
            )
            if should_stop:
                logger.info(f"Stop condition met: {retry_config['stop_when']}")
                return False, None
        
        # Check retry condition
        if 'retry_when' in retry_config:
            should_retry = await self._evaluate_condition(
                retry_config['retry_when'],
                eval_context
            )
            if not should_retry:
                logger.info(f"Retry condition not met: {retry_config['retry_when']}")
                return False, None
        else:
            # Default: retry on error/failure
            event_type = event.get('event_type', '')
            if event_type not in ['action_error', 'action_failed']:
                logger.info("No retry condition and event is not error/failure, no retry")
                return False, None
        
        # Calculate backoff delay
        delay = self._calculate_delay(retry_config, current_attempt)
        logger.info(f"Retry approved with delay={delay}s")
        return True, delay
    
    def _build_evaluation_context(
        self,
        event: Dict[str, Any],
        attempt: int,
        execution_id: str,
        node_id: str
    ) -> Dict[str, Any]:
        """Build context for Jinja2 expression evaluation."""
        result = event.get('result', {})
        if not isinstance(result, dict):
            result = {'data': result}
        
        return {
            'result': result,
            'response': result,  # Alias for HTTP compatibility
            'status_code': result.get('status_code'),
            'error': event.get('error') or result.get('error'),
            'success': result.get('success', event.get('status') == 'COMPLETED'),
            'data': result.get('data'),
            'attempt': attempt,
            'execution_id': execution_id,
            'node_id': node_id,
            'event_type': event.get('event_type'),
            'status': event.get('status')
        }
    
    async def _evaluate_condition(
        self,
        condition: str,
        context: Dict[str, Any]
    ) -> bool:
        """
        Evaluate a Jinja2 condition expression.
        
        Args:
            condition: Jinja2 template string that evaluates to boolean
            context: Context variables for template rendering
            
        Returns:
            Boolean result of condition evaluation
        """
        try:
            template = self.jinja_env.from_string(condition)
            result_str = template.render(**context)
            
            # Convert to boolean
            result = str(result_str).strip().lower() in ('true', '1', 'yes')
            logger.debug(f"Condition '{condition}' evaluated to: {result}")
            return result
            
        except Exception as e:
            logger.warning(f"Error evaluating condition '{condition}': {e}")
            # On evaluation error, don't retry
            return False
    
    def _calculate_delay(
        self,
        retry_config: Dict[str, Any],
        attempt: int
    ) -> float:
        """
        Calculate backoff delay for retry attempt.
        
        Uses exponential backoff: initial_delay * (backoff_multiplier ^ (attempt - 1))
        
        Args:
            retry_config: Retry configuration
            attempt: Current attempt number (1-indexed)
            
        Returns:
            Delay in seconds
        """
        initial_delay = retry_config.get('initial_delay', 1.0)
        backoff_multiplier = retry_config.get('backoff_multiplier', 2.0)
        max_delay = retry_config.get('max_delay', 60.0)
        jitter_enabled = retry_config.get('jitter', True)
        
        # Calculate exponential backoff
        delay = initial_delay * (backoff_multiplier ** (attempt - 1))
        delay = min(delay, max_delay)
        
        # Add jitter to prevent thundering herd
        if jitter_enabled:
            import random
            delay = delay * (0.5 + random.random())
        
        return delay


async def enqueue_retry(
    execution_id: str,
    node_id: str,
    event: Dict[str, Any],
    delay_seconds: float,
    queue_entry: Dict[str, Any],
    retry_config: Dict[str, Any]
) -> None:
    """
    Re-enqueue a failed task for retry.
    
    Args:
        execution_id: Execution ID
        node_id: Step/node ID
        event: Event that triggered retry evaluation
        delay_seconds: Delay before retry becomes available
        queue_entry: Current queue entry data
        retry_config: Retry configuration from playbook
    """
    logger.info(f"Enqueueing retry for execution={execution_id} node={node_id} delay={delay_seconds}s")
    
    async with get_async_db_connection() as conn:
        async with conn.cursor() as cur:
            # Calculate available_at with backoff delay
            available_at = datetime.utcnow() + timedelta(seconds=delay_seconds)
            current_attempt = queue_entry.get('attempts', 0) + 1
            
            # Store retry config in queue for reference
            retry_config_json = json.dumps(retry_config) if retry_config else None
            
            # Update existing queue entry
            await cur.execute("""
                UPDATE noetl.queue
                SET status = 'queued',
                    attempts = %s,
                    available_at = %s,
                    worker_id = NULL,
                    lease_until = NULL,
                    updated_at = NOW()
                WHERE execution_id = %s AND node_id = %s
            """, (
                current_attempt,
                available_at,
                execution_id,
                node_id
            ))
            
            await conn.commit()
    
    # Emit retry event for observability
    from noetl.server.api.event.service import get_event_service
    service = get_event_service()
    await service.emit({
        'execution_id': execution_id,
        'catalog_id': queue_entry.get('catalog_id'),
        'event_type': 'step_retry',
        'status': 'PENDING',
        'node_id': node_id,
        'node_name': queue_entry.get('node_name'),
        'node_type': queue_entry.get('node_type'),
        'context': {
            'attempt': current_attempt,
            'max_attempts': retry_config.get('max_attempts', 3),
            'delay_seconds': delay_seconds,
            'last_error': event.get('error'),
            'available_at': available_at.isoformat()
        },
        'result': {
            'retry_scheduled': True,
            'next_attempt': current_attempt + 1,
            'delay': delay_seconds
        }
    })
    
    logger.info(f"Retry scheduled: attempt {current_attempt}/{retry_config.get('max_attempts', 3)}")


async def handle_retry_exhausted(
    execution_id: str,
    node_id: str,
    event: Dict[str, Any],
    queue_entry: Dict[str, Any],
    retry_config: Dict[str, Any]
) -> None:
    """
    Handle the case when all retry attempts are exhausted.
    
    Args:
        execution_id: Execution ID
        node_id: Step/node ID
        event: Final failure event
        queue_entry: Queue entry data
        retry_config: Retry configuration from playbook
    """
    logger.warning(f"Retry exhausted for execution={execution_id} node={node_id}")
    
    async with get_async_db_connection() as conn:
        async with conn.cursor() as cur:
            # Mark queue entry as dead/failed
            await cur.execute("""
                UPDATE noetl.queue
                SET status = 'dead',
                    updated_at = NOW()
                WHERE execution_id = %s AND node_id = %s
            """, (execution_id, node_id))
            
            await conn.commit()
    
    # Emit retry exhausted event
    from noetl.server.api.event.service import get_event_service
    service = get_event_service()
    await service.emit({
        'execution_id': execution_id,
        'catalog_id': queue_entry.get('catalog_id'),
        'event_type': 'step_retry_exhausted',
        'status': 'FAILED',
        'node_id': node_id,
        'node_name': queue_entry.get('node_name'),
        'node_type': queue_entry.get('node_type'),
        'error': f"All retry attempts exhausted: {event.get('error')}",
        'context': {
            'attempts': queue_entry.get('attempts', 0),
            'max_attempts': retry_config.get('max_attempts', 3),
            'final_error': event.get('error')
        }
    })
    
    # Emit terminal failure event
    await service.emit({
        'execution_id': execution_id,
        'catalog_id': queue_entry.get('catalog_id'),
        'event_type': 'step_failed_terminal',
        'status': 'FAILED',
        'node_id': node_id,
        'node_name': queue_entry.get('node_name'),
        'node_type': queue_entry.get('node_type'),
        'error': event.get('error'),
        'result': event.get('result')
    })
    
    logger.warning(f"Terminal failure recorded for {node_id}")


async def get_retry_config_for_step(
    execution_id: str,
    node_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get retry configuration for a step from the playbook.
    
    Args:
        execution_id: Execution ID
        node_id: Step/node ID
        
    Returns:
        Retry configuration dict or None if not configured
    """
    try:
        # Get playbook and workload from execution
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                # Get catalog_id and playbook path from workload
                await cur.execute("""
                    SELECT catalog_id, context
                    FROM noetl.workload
                    WHERE execution_id = %s
                """, (execution_id,))
                
                row = await cur.fetchone()
                if not row:
                    logger.warning(f"No workload found for execution={execution_id}")
                    return None
                
                catalog_id = row[0]
                
                # Get playbook from catalog
                await cur.execute("""
                    SELECT content
                    FROM noetl.catalog
                    WHERE catalog_id = %s
                """, (catalog_id,))
                
                catalog_row = await cur.fetchone()
                if not catalog_row:
                    logger.warning(f"No catalog entry found for catalog_id={catalog_id}")
                    return None
                
                playbook_content = catalog_row[0]
                
                # Parse playbook YAML
                import yaml
                playbook = yaml.safe_load(playbook_content)
                
                # Find the step in workflow
                workflow = playbook.get('workflow', [])
                for step in workflow:
                    if step.get('step') == node_id:
                        retry_config = step.get('retry')
                        if retry_config:
                            # Normalize retry config
                            if isinstance(retry_config, bool):
                                return {} if retry_config else None
                            elif isinstance(retry_config, int):
                                return {'max_attempts': retry_config}
                            elif isinstance(retry_config, dict):
                                return retry_config
                        return None
                
                logger.debug(f"No retry config found for node={node_id}")
                return None
                
    except Exception as e:
        logger.error(f"Error getting retry config: {e}", exc_info=True)
        return None
