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
        logger.debug("Failed to encode task fields", exc_info=True)
    
    return encoded_task


async def expand_workbook_reference(
    step_config: Dict[str, Any],
    catalog_id: str
) -> Dict[str, Any]:
    """
    Expand workbook action references by fetching the actual action definition from the playbook.
    
    If step_config has type='workbook', this function:
    1. Fetches the playbook from catalog
    2. Looks up the action by name in the workbook section
    3. Merges the action definition into step_config
    4. Preserves step-level overrides (args, data)
    
    Args:
        step_config: Step configuration (may contain type='workbook' and name='action_name')
        catalog_id: Catalog entry ID to fetch playbook from
        
    Returns:
        Expanded step configuration with workbook action merged in
    """
    # Only expand if type is 'workbook'
    if not isinstance(step_config, dict):
        return step_config
    
    step_type = step_config.get("type", "").lower()
    if step_type != "workbook":
        return step_config
    
    workbook_action_name = step_config.get("name")
    if not workbook_action_name:
        logger.warning("Workbook step missing 'name' attribute, cannot expand")
        return step_config
    
    try:
        # Lazy import to avoid circular dependency
        from noetl.server.api.catalog.service import CatalogService
        import yaml
        
        # Fetch playbook from catalog
        catalog_entry = await CatalogService.fetch_entry(catalog_id=catalog_id)
        if not catalog_entry or not catalog_entry.content:
            logger.warning(f"No playbook content found for catalog_id {catalog_id}")
            return step_config
        
        playbook = yaml.safe_load(catalog_entry.content)
        
        # Find the workbook action in the playbook's workbook section
        workbook_actions = playbook.get("workbook", [])
        workbook_action = None
        for action in workbook_actions:
            if action.get("name") == workbook_action_name:
                workbook_action = dict(action)
                break
        
        if not workbook_action:
            logger.warning(f"Workbook action '{workbook_action_name}' not found in playbook")
            return step_config
        
        # Preserve step-level overrides
        step_args = step_config.get("args", {})
        step_data = step_config.get("data", {})
        
        # Merge workbook action into step config
        expanded_config = dict(workbook_action)
        expanded_config["type"] = workbook_action.get("type", "python")
        
        # Restore step-level overrides (they take precedence)
        if step_args:
            if "args" not in expanded_config:
                expanded_config["args"] = {}
            expanded_config["args"].update(step_args)
        if step_data:
            if "data" not in expanded_config:
                expanded_config["data"] = {}
            expanded_config["data"].update(step_data)
        
        # Preserve other step-level fields that aren't in the workbook action
        for key in ["desc", "next", "step"]:
            if key in step_config and key not in expanded_config:
                expanded_config[key] = step_config[key]
        
        logger.info(f"Expanded workbook action '{workbook_action_name}' to type '{expanded_config['type']}'")
        return expanded_config
        
    except Exception:
        logger.exception(f"Failed to expand workbook action '{workbook_action_name}'")
        return step_config


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
        context: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None
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
            metadata: Optional iterator/execution metadata to propagate through queue
            
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
                                logger.exception("Error merging with_params into step config")

                            # Expand workbook references before publishing
                            step_cfg = await expand_workbook_reference(step_cfg, catalog_id)

                            # Publish the actionable next step
                            qid = await QueuePublisher.publish_step(
                                execution_id=execution_id,
                                catalog_id=catalog_id,
                                step_name=to_step,
                                step_config=step_cfg,
                                step_type=nxt_type,
                                parent_event_id=parent_event_id,
                                context={"workload": (context or {}).get("workload", {})},
                                priority=90,  # just below start's 100, but urgent
                                metadata=metadata
                            )
                            queue_ids.append(qid)

                        # Done with router; do not enqueue router itself
                        logger.info(f"Router step '{step_name}' resolved to {len(next_rows)} next steps")
                        continue

                    # Actionable start (has explicit type) — enqueue via QueueService
                    # Lazy import to avoid circular dependency
                    from noetl.server.api.queue.service import QueueService
                    
                    queue_id = await get_snowflake_id()

                    # Parse step config - handle both string (JSON) and dict (JSONB) from PostgreSQL
                    raw_config = step_def["raw_config"]
                    if isinstance(raw_config, str):
                        step_cfg = json.loads(raw_config)
                    else:
                        step_cfg = raw_config or {}
                    
                    # Expand workbook references (if type='workbook')
                    step_cfg = await expand_workbook_reference(step_cfg, catalog_id)
                    
                    # Encode step config for queue
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
                        status="queued",
                        metadata=metadata
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
        delay_seconds: int = 0,
        metadata: Optional[Dict[str, Any]] = None
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
            metadata: Optional iterator/execution metadata to propagate
            
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
            status="queued",
            metadata=metadata
        )
        
        logger.info(
            f"Published step '{step_name}' to queue: "
            f"execution_id={execution_id}, queue_id={response.id}, priority={priority}"
        )
        
        # Emit step_started event when step is enqueued
        try:
            from noetl.server.api.broker.service import EventService
            from noetl.server.api.broker.schema import EventEmitRequest
            
            step_started_request = EventEmitRequest(
                execution_id=int(execution_id),
                catalog_id=int(catalog_id),
                event_type="step_started",
                node_id=step_name,
                node_name=step_name,
                node_type=step_type,
                status="RUNNING",
                parent_event_id=int(parent_event_id) if parent_event_id else None,
                context={"step_config": step_config},
                meta={"emitter": "publisher", "queue_id": str(response.id)}
            )
            
            step_started_result = await EventService.emit_event(step_started_request)
            logger.debug(f"Emitted step_started event for '{step_name}', event_id={step_started_result.event_id}")
        except Exception as e:
            logger.warning(f"Failed to emit step_started event for step '{step_name}': {e}", exc_info=True)
        
        return response.id
