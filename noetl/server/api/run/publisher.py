"""
Queue publisher module for execution tasks.

Publishes actionable tasks to queue table for worker pools to consume.
"""

from typing import Dict, Any, Optional, List
import json
from datetime import datetime, timedelta
from psycopg.rows import dict_row
from noetl.core.db.pool import get_pool_connection, get_snowflake_id
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


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
            async with conn.cursor() as cur:
                for step_name in initial_steps:
                    step_def = step_map.get(step_name)
                    if not step_def:
                        logger.warning(
                            f"Initial step '{step_name}' not found in workflow, skipping"
                        )
                        continue
                    
                    # Generate queue_id from database
                    queue_id = await get_snowflake_id()
                    
                    # Build task context
                    task_context = {
                        "execution_id": execution_id,
                        "step_name": step_name,
                        "step_type": step_def["step_type"],
                        "step_config": json.loads(step_def["raw_config"])
                    }
                    
                    if context:
                        task_context["workload"] = context.get("workload", {})
                    
                    # Prepare action payload (raw step config)
                    action = step_def["raw_config"]
                    
                    # Determine priority (start step has higher priority)
                    priority = 100 if step_name.lower() == "start" else 50
                    
                    # Make available immediately
                    available_at = datetime.utcnow()
                    
                    await cur.execute(
                        """
                        INSERT INTO noetl.queue (
                            queue_id,
                            execution_id,
                            catalog_id,
                            node_id,
                            node_name,
                            node_type,
                            action,
                            context,
                            status,
                            priority,
                            attempts,
                            max_attempts,
                            available_at,
                            parent_event_id,
                            event_id,
                            created_at,
                            updated_at
                        ) VALUES (
                            %(queue_id)s,
                            %(execution_id)s,
                            %(catalog_id)s,
                            %(node_id)s,
                            %(node_name)s,
                            %(node_type)s,
                            %(action)s,
                            %(context)s,
                            %(status)s,
                            %(priority)s,
                            %(attempts)s,
                            %(max_attempts)s,
                            %(available_at)s,
                            %(parent_event_id)s,
                            %(event_id)s,
                            %(created_at)s,
                            %(updated_at)s
                        )
                        """,
                        {
                            "queue_id": queue_id,
                            "execution_id": execution_id,
                            "catalog_id": catalog_id,
                            "node_id": step_def["step_id"],
                            "node_name": step_name,
                            "node_type": step_def["step_type"],
                            "action": action,
                            "context": json.dumps(task_context),
                            "status": "queued",
                            "priority": priority,
                            "attempts": 0,
                            "max_attempts": 5,
                            "available_at": available_at,
                            "parent_event_id": parent_event_id,
                            "event_id": None,  # Will be set when worker picks up
                            "created_at": datetime.utcnow(),
                            "updated_at": datetime.utcnow()
                        }
                    )
                    
                    queue_ids.append(queue_id)
                    
                    logger.info(
                        f"Published step '{step_name}' to queue: "
                        f"execution_id={execution_id}, queue_id={queue_id}, priority={priority}"
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
        
        # Build task context
        task_context = {
            "execution_id": execution_id,
            "step_name": step_name,
            "step_type": step_type,
            "step_config": step_config
        }
        
        if context:
            task_context.update(context)
        
        # Make available after delay
        available_at = datetime.utcnow() + timedelta(seconds=delay_seconds)
        
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO noetl.queue (
                        queue_id,
                        execution_id,
                        catalog_id,
                        node_id,
                        node_name,
                        node_type,
                        action,
                        context,
                        status,
                        priority,
                        attempts,
                        max_attempts,
                        available_at,
                        parent_event_id,
                        created_at,
                        updated_at
                    ) VALUES (
                        %(queue_id)s,
                        %(execution_id)s,
                        %(catalog_id)s,
                        %(node_id)s,
                        %(node_name)s,
                        %(node_type)s,
                        %(action)s,
                        %(context)s,
                        %(status)s,
                        %(priority)s,
                        %(attempts)s,
                        %(max_attempts)s,
                        %(available_at)s,
                        %(parent_event_id)s,
                        %(created_at)s,
                        %(updated_at)s
                    )
                    """,
                    {
                        "queue_id": queue_id,
                        "execution_id": execution_id,
                        "catalog_id": catalog_id,
                        "node_id": step_name,
                        "node_name": step_name,
                        "node_type": step_type,
                        "action": json.dumps(step_config),
                        "context": json.dumps(task_context),
                        "status": "queued",
                        "priority": priority,
                        "attempts": 0,
                        "max_attempts": 5,
                        "available_at": available_at,
                        "parent_event_id": parent_event_id,
                        "created_at": datetime.utcnow(),
                        "updated_at": datetime.utcnow()
                    }
                )
        
        logger.info(
            f"Published step '{step_name}' to queue: "
            f"execution_id={execution_id}, queue_id={queue_id}, priority={priority}"
        )
        
        return queue_id
