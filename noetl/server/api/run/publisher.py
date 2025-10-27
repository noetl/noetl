"""
Queue publisher module for execution tasks.

Publishes actionable tasks to queue table for worker pools to consume.
"""

from typing import Dict, Any, Optional, List
import json
import base64
from datetime import datetime, timedelta, timezone
from psycopg.rows import dict_row
from noetl.core.db.pool import get_pool_connection, get_snowflake_id
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def encode_task_for_queue(task_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply base64 encoding to multiline code/commands in task configuration
    to prevent serialization issues when passing through JSON in queue table.
    Only base64 versions are stored - original fields are removed to ensure single method of handling.
    
    Args:
        task_config: The original task configuration
        
    Returns:
        Modified task configuration with base64 encoded fields, original fields removed
    """
    if not isinstance(task_config, dict):
        return task_config
    
    encoded_task = dict(task_config)
    
    try:
        # Encode Python code and remove original
        code_val = encoded_task.get('code')
        if isinstance(code_val, str) and code_val.strip():
            encoded_task['code_b64'] = base64.b64encode(code_val.encode('utf-8')).decode('ascii')
            # Remove original to ensure only base64 is used
            encoded_task.pop('code', None)
            
        # Encode command/commands for PostgreSQL and DuckDB and remove originals
        for field in ('command', 'commands'):
            cmd_val = encoded_task.get(field)
            if isinstance(cmd_val, str) and cmd_val.strip():
                encoded_task[f'{field}_b64'] = base64.b64encode(cmd_val.encode('utf-8')).decode('ascii')
                # Remove original to ensure only base64 is used
                encoded_task.pop(field, None)
                
    except Exception:
        logger.debug("Failed to encode task fields with base64", exc_info=True)
        
    return encoded_task


class QueuePublisher:
    """
    Publishes tasks to queue table for worker execution.
    
    Responsibilities:
    - Publish initial workflow steps to queue
    - Set appropriate priority and availability
    - Link tasks to execution and events
    """
    
    @staticmethod
    async def publish_initial_steps(
        execution_id: str,
        catalog_id: str,
        initial_steps: List[str],
        workflow_steps: List[Dict[str, Any]],
        parent_event_id: str,
        context: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """
        Publish initial workflow steps to queue.
        
        Router steps (e.g., start without actionable type) are not enqueued.
        Instead, their actionable next steps are resolved from transitions and enqueued directly.
        
        Args:
            execution_id: Execution identifier
            catalog_id: Catalog entry ID
            initial_steps: List of step names to publish (e.g., ['start'])
            workflow_steps: Complete workflow step definitions
            parent_event_id: Parent event ID (workflow initialized event)
            context: Optional execution context
            
        Returns:
            List of queue_ids for published tasks
        """
        queue_ids = []
        
        # Build lookup map for workflow steps
        step_map = {
            step["step_name"]: step
            for step in workflow_steps
        }
        
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                for step_name in initial_steps:
                    step_def = step_map.get(step_name)
                    if not step_def:
                        logger.warning(f"Initial step '{step_name}' not found in workflow, skipping")
                        continue

                    step_type = (step_def.get("step_type") or "").lower()

                    # If router (e.g. start without actionable type), do not enqueue itself.
                    if step_type == "router":
                        # Lookup transitions from this step and enqueue actionable next steps
                        await cur.execute(
                            """
                            SELECT to_step, condition, with_params
                            FROM noetl.transition
                            WHERE execution_id = %(execution_id)s
                              AND from_step = %(from_step)s
                            """,
                            {"execution_id": execution_id, "from_step": step_name}
                        )
                        next_rows = await cur.fetchall() or []

                        for row in next_rows:
                            to_step = row.get("to_step")
                            if not to_step:
                                continue
                            next_def = step_map.get(to_step)
                            if not next_def:
                                logger.warning(f"Transition target step '{to_step}' not found in workflow, skipping")
                                continue
                            nxt_type = (next_def.get("step_type") or "").lower()
                            # Skip non-actionable types (router/end)
                            if nxt_type in ("router", "end"):
                                logger.debug(f"Skipping non-actionable next step '{to_step}' of type '{nxt_type}'")
                                continue

                            # Merge transition with_params into the step config as inputs
                            step_cfg = json.loads(next_def["raw_config"]) if isinstance(next_def.get("raw_config"), str) else (next_def.get("raw_config") or {})
                            try:
                                with_params = row.get("with_params") or {}
                                if isinstance(step_cfg, dict) and isinstance(with_params, dict):
                                    # Normalize into 'args' to be read by worker
                                    args = step_cfg.get("args") if isinstance(step_cfg.get("args"), dict) else {}
                                    step_cfg["args"] = {**args, **with_params}
                            except Exception:
                                pass

                            # Publish the actionable next step
                            qid = await QueuePublisher.publish_step(
                                execution_id=execution_id,
                                catalog_id=catalog_id,
                                step_name=to_step,
                                step_config=step_cfg,
                                step_type=nxt_type,
                                parent_event_id=parent_event_id,
                                context={"workload": (context or {}).get("workload", {})},
                                priority=90  # just below start's 100, but urgent
                            )
                            queue_ids.append(qid)

                        # Done with router; do not enqueue router itself
                        logger.info(f"Router step '{step_name}' resolved to {len(next_rows)} next steps")
                        continue

                    # Actionable start (has explicit type) — enqueue via QueueService
                    # Lazy import to avoid circular dependency
                    from noetl.server.api.queue.service import QueueService
                    
                    queue_id = await get_snowflake_id()

                    # Parse and encode step config
                    step_cfg = json.loads(step_def["raw_config"])
                    encoded_step_cfg = encode_task_for_queue(step_cfg)
                    
                    task_context = {
                        "execution_id": execution_id,
                        "step_name": step_name,
                        "step_type": step_def["step_type"],
                        "step_config": encoded_step_cfg
                    }
                    if context:
                        task_context["workload"] = context.get("workload", {})

                    action = json.dumps(encoded_step_cfg)  # Use encoded config for action
                    priority = 100 if step_name.lower() == "start" else 50
                    available_at = datetime.now(timezone.utc)

                    # Use QueueService to enqueue the job
                    response = await QueueService.enqueue_job(
                        execution_id=execution_id,
                        catalog_id=catalog_id,
                        node_id=step_def["step_id"],
                        node_name=step_name,
                        node_type=step_def["step_type"],
                        action=action,
                        context=task_context,
                        priority=priority,
                        max_attempts=5,
                        available_at=available_at,
                        parent_event_id=parent_event_id,
                        event_id=None,
                        queue_id=queue_id,
                        status="queued"
                    )

                    queue_ids.append(response.id)
                    logger.info(
                        f"Published step '{step_name}' to queue: execution_id={execution_id}, queue_id={queue_id}, priority={priority}"
                    )
        
        return queue_ids
    
    @staticmethod
    async def publish_step(
        execution_id: str,
        catalog_id: str,
        step_name: str,
        step_config: Dict[str, Any],
        step_type: str,
        parent_event_id: str,
        context: Optional[Dict[str, Any]] = None,
        priority: int = 50,
        delay_seconds: int = 0
    ) -> str:
        """
        Publish a single step to queue.
        
        Args:
            execution_id: Execution identifier
            catalog_id: Catalog entry ID
            step_name: Step name
            step_config: Step configuration
            step_type: Step type
            parent_event_id: Parent event ID
            context: Optional execution context
            priority: Task priority (0-100, higher is more urgent)
            delay_seconds: Delay before making available (default: 0)
            
        Returns:
            queue_id of published task
        """
        # Generate queue_id from database
        queue_id = await get_snowflake_id()
        
        # Encode task config for queue (base64 encode code/command fields)
        encoded_step_config = encode_task_for_queue(step_config)
        
        # Build task context
        task_context = {
            "execution_id": execution_id,
            "step_name": step_name,
            "step_type": step_type,
            "step_config": encoded_step_config
        }
        
        if context:
            task_context.update(context)
        
        # Make available after delay (use UTC timezone-aware datetime)
        available_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
        
        # Lazy import to avoid circular dependency
        from noetl.server.api.queue.service import QueueService
        
        # Use QueueService to enqueue the job
        response = await QueueService.enqueue_job(
            execution_id=execution_id,
            catalog_id=catalog_id,
            node_id=step_name,
            node_name=step_name,
            node_type=step_type,
            action=json.dumps(encoded_step_config),
            context=task_context,
            priority=priority,
            max_attempts=5,
            available_at=available_at,
            parent_event_id=parent_event_id,
            event_id=None,
            queue_id=queue_id,
            status="queued"
        )
        
        logger.info(
            f"Published step '{step_name}' to queue: "
            f"execution_id={execution_id}, queue_id={response.id}, priority={priority}"
        )
        
        return response.id
