"""
Queue publisher module for execution tasks.

Publishes actionable tasks to queue table for worker pools to consume.
"""

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from psycopg.rows import dict_row

from noetl.core.db.pool import get_pool_connection, get_snowflake_id
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def encode_task_for_queue(task_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply base64 encoding to multiline code in task configuration.
    
    IMPORTANT: command/commands fields are NOT encoded here because they contain
    Jinja2 templates that must be rendered by the worker with full execution context
    (including results from previous steps). The rendering happens via /context/render
    endpoint before task execution. The postgres/duckdb executors accept inline 'command'
    field directly without base64 encoding.

    Args:
        task_config: The original task configuration

    Returns:
        Modified task configuration with code_b64 field (if code present), command/commands unchanged
    """
    if not isinstance(task_config, dict):
        return task_config

    encoded_task = dict(task_config)

    try:
        # Encode Python code and remove original
        code_val = encoded_task.get("code")
        if isinstance(code_val, str) and code_val.strip():
            encoded_task["code_b64"] = base64.b64encode(
                code_val.encode("utf-8")
            ).decode("ascii")
            # Remove original to ensure only base64 is used
            encoded_task.pop("code", None)

        # DO NOT encode command/commands - they need to be rendered with Jinja2 first
        # The postgres/duckdb executors support inline 'command' field without base64 encoding

    except Exception:
        logger.debug("Failed to encode task fields", exc_info=True)

    return encoded_task


async def expand_workbook_reference(
    step_config: Dict[str, Any], catalog_id: str
) -> Dict[str, Any]:
    """
    Expand workbook action references by fetching the actual action definition from the playbook.

    If step_config has tool='workbook', this function:
    1. Fetches the playbook from catalog
    2. Looks up the action by name in the workbook section
    3. Merges the action definition into step_config
    4. Preserves step-level overrides (args, data)

    Args:
        step_config: Step configuration (tool='workbook' and name='action_name')
        catalog_id: Catalog entry ID to fetch playbook from

    Returns:
        Expanded step configuration with workbook action merged in
    """
    # Only expand if type is 'workbook'
    if not isinstance(step_config, dict):
        return step_config

    tool_raw = step_config.get("tool", "")
    # Handle both string tool names and dict tool definitions
    if isinstance(tool_raw, dict):
        step_tool = (tool_raw.get("kind") or tool_raw.get("type") or "").lower()
    else:
        step_tool = tool_raw.lower() if isinstance(tool_raw, str) else str(tool_raw).lower()
    
    if step_tool != "workbook":
        return step_config

    workbook_action_name = step_config.get("name")
    if not workbook_action_name:
        logger.warning("Workbook step missing 'name' attribute, cannot expand")
        return step_config

    try:
        # Lazy import to avoid circular dependency
        import yaml

        from noetl.server.api.catalog.service import CatalogService

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
            logger.warning(
                f"Workbook action '{workbook_action_name}' not found in playbook"
            )
            return step_config

        # Preserve step-level overrides
        step_args = step_config.get("args", {})
        step_data = step_config.get("data", {})

        # Merge workbook action into step config
        expanded_config = dict(workbook_action)
        tool_name = expanded_config.get("tool")
        if not tool_name:
            raise ValueError(
                f"Workbook action '{workbook_action_name}' must define a 'tool'"
            )

        # Ensure legacy 'type' field is cleared
        expanded_config.pop("type", None)

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

        logger.info(
            f"Expanded workbook action '{workbook_action_name}' to tool '{expanded_config['tool']}'"
        )
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
        metadata: Optional[Dict[str, Any]] = None,
        parent_execution_id: Optional[str] = None,
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
            parent_execution_id: Optional parent execution ID for nested playbook calls

        Returns:
            List of queue_ids for published tasks
        """
        queue_ids = []

        # Build lookup map for workflow steps
        step_map = {step["step_name"]: step for step in workflow_steps}

        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                for step_name in initial_steps:
                    step_def = step_map.get(step_name)
                    if not step_def:
                        logger.warning(
                            f"Initial step '{step_name}' not found in workflow, skipping"
                        )
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
                            {"execution_id": execution_id, "from_step": step_name},
                        )
                        next_rows = await cur.fetchall() or []

                        for row in next_rows:
                            to_step = row.get("to_step")
                            if not to_step:
                                continue
                            next_def = step_map.get(to_step)
                            if not next_def:
                                logger.warning(
                                    f"Transition target step '{to_step}' not found in workflow, skipping"
                                )
                                continue
                            nxt_type = (next_def.get("step_type") or "").lower()
                            # Skip non-actionable types (router/end)
                            if nxt_type in ("router", "end"):
                                logger.debug(
                                    f"Skipping non-actionable next step '{to_step}' of type '{nxt_type}'"
                                )
                                continue

                            # Merge transition with_params into the step config as inputs
                            step_cfg = (
                                json.loads(next_def["raw_config"])
                                if isinstance(next_def.get("raw_config"), str)
                                else (next_def.get("raw_config") or {})
                            )
                            try:
                                with_params = row.get("with_params") or {}
                                if isinstance(step_cfg, dict) and isinstance(
                                    with_params, dict
                                ):
                                    # Normalize into 'args' to be read by worker
                                    args = (
                                        step_cfg.get("args")
                                        if isinstance(step_cfg.get("args"), dict)
                                        else {}
                                    )
                                    step_cfg["args"] = {**args, **with_params}
                            except Exception:
                                logger.exception(
                                    "Error merging with_params into step config"
                                )

                            # Expand workbook references before publishing
                            step_cfg = await expand_workbook_reference(
                                step_cfg, catalog_id
                            )

                            # Publish the actionable next step
                            qid = await QueuePublisher.publish_step(
                                execution_id=execution_id,
                                catalog_id=catalog_id,
                                step_name=to_step,
                                step_config=step_cfg,
                                step_type=nxt_type,
                                parent_event_id=parent_event_id,
                                context={
                                    "workload": (context or {}).get("workload", {})
                                },
                                priority=90,  # just below start's 100, but urgent
                                metadata=metadata,
                            )
                            queue_ids.append(qid)

                        # Done with router; do not enqueue router itself
                        logger.info(
                            f"Router step '{step_name}' resolved to {len(next_rows)} next steps"
                        )
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

                    # Render step args with available context (workload for initial steps)
                    # IMPORTANT: For iterator steps, DO NOT render the nested 'task' block
                    # because it contains templates like {{ item }} that only exist during iteration
                    if "args" in step_cfg and step_cfg["args"] and context:
                        from noetl.core.dsl.render import render_template
                        from jinja2 import BaseLoader, Environment
                        
                        try:
                            env = Environment(loader=BaseLoader())
                            step_cfg["args"] = render_template(
                                env, step_cfg["args"], context, rules=None, strict_keys=False
                            )
                        except Exception as e:
                            logger.warning(f"Failed to render args for step '{step_name}': {e}")
                    
                    # Preserve blocks that should not be rendered server-side:
                    # 1. For iterator steps (OLD format): nested 'task' block (contains {{ item }} templates)
                    # 2. For loop steps (NEW format): 'loop' block AND nested tool config (contains {{ item }} templates)
                    # 3. For all steps: 'sink' block (contains {{ result }} templates)
                    tool_raw = step_cfg.get("tool") or ""
                    if isinstance(tool_raw, dict):
                        step_tool = (tool_raw.get("kind") or tool_raw.get("type") or "").lower()
                    else:
                        step_tool = tool_raw.lower() if isinstance(tool_raw, str) else str(tool_raw).lower()
                    is_iterator_old = step_tool == "iterator"
                    has_loop_new = "loop" in step_cfg
                    
                    # Always preserve sink block (regardless of step type)
                    sink_block = step_cfg.pop("sink", None)
                    if sink_block is not None:
                        logger.critical(f"PUBLISHER: Extracted sink block for step '{step_name}': {sink_block}")
                    
                    # Check for loop block - handle via server-side iteration instead of queue
                    loop_block = step_cfg.pop("loop", None)
                    if loop_block is not None:
                        logger.info(f"PUBLISHER.publish_initial_steps: Step '{step_name}' has loop attribute, initiating server-side iteration")
                        
                        # Emit iterator_started event (server-side only)
                        from noetl.server.api.broker.schema import EventEmitRequest
                        from noetl.server.api.broker.service import EventService
                        
                        # Build iterator context with collection metadata
                        # Render the collection template if it's a string (Jinja2 template)
                        from noetl.core.dsl.render import render_template
                        from jinja2 import BaseLoader, Environment
                        
                        collection_raw = loop_block.get("collection", [])
                        if isinstance(collection_raw, str):
                            # Build full render context with step results for collection template
                            from noetl.server.api.run.orchestrator import OrchestratorQueries
                            render_ctx = {"workload": (context or {}).get("workload", {})}
                            
                            logger.critical(f"PUBLISHER.publish_initial_steps: About to fetch step results for execution {execution_id}")
                            # Fetch all step results for this execution
                            result_rows = await OrchestratorQueries.get_step_results(int(execution_id))
                            logger.critical(f"PUBLISHER.publish_initial_steps: Fetched {len(result_rows)} step results")
                            for res_row in result_rows:
                                if res_row["node_name"] and res_row["result"]:
                                    # Normalize result: if it has 'data' field, use that instead of the envelope
                                    result_value = res_row["result"]
                                    if isinstance(result_value, dict) and "data" in result_value:
                                        result_value = result_value["data"]
                                    render_ctx[res_row["node_name"]] = result_value
                                    logger.critical(f"PUBLISHER.publish_initial_steps: Added '{res_row['node_name']}' to context")
                            
                            logger.critical(f"PUBLISHER.publish_initial_steps: About to render template '{collection_raw}'")
                            logger.critical(f"PUBLISHER.publish_initial_steps: Render context keys: {list(render_ctx.keys())}")
                            # Render the template with full context (workload + step results)
                            env = Environment(loader=BaseLoader())
                            collection = render_template(env, collection_raw, render_ctx)
                            logger.critical(f"PUBLISHER.publish_initial_steps: Rendered collection type={type(collection).__name__}, len={len(collection) if isinstance(collection, (list, str)) else 'N/A'}")
                        else:
                            collection = collection_raw
                        
                        # CRITICAL: Restore sink to nested_task BEFORE passing to iterator
                        # Sink needs to execute per iteration in the worker
                        if sink_block is not None:
                            step_cfg["sink"] = sink_block
                            logger.critical(f"PUBLISHER: Restored sink to nested_task for iterator step '{step_name}'")
                        
                        iterator_context = {
                            "collection": collection,
                            "iterator_name": loop_block.get("element", "item"),
                            "mode": loop_block.get("mode", "sequential"),
                            "nested_task": step_cfg,  # The actual task config to execute per iteration
                            "total_count": len(collection) if isinstance(collection, list) else 0
                        }
                        
                        iterator_started_request = EventEmitRequest(
                            execution_id=str(execution_id),
                            catalog_id=catalog_id,
                            event_type="iterator_started",
                            status="RUNNING",
                            node_id=step_name,
                            node_name="iterator",
                            node_type="iterator",
                            parent_event_id=parent_event_id,
                            context=iterator_context
                        )
                        
                        try:
                            result = await EventService.emit_event(iterator_started_request)
                            iterator_event_id = result.event_id
                            logger.info(f"Emitted iterator_started for '{step_name}', event_id={iterator_event_id}")
                            
                            # Process iterator_started to enqueue iteration jobs
                            # Import here to avoid circular dependency
                            from noetl.server.api.run.orchestrator import _process_iterator_started
                            event_obj = {
                                'context': iterator_context,
                                'catalog_id': catalog_id,
                                'node_id': step_name,
                                'node_name': step_name,
                                'event_id': iterator_event_id
                            }
                            await _process_iterator_started(int(execution_id), event_obj)
                            
                            # Skip normal queue publishing - iteration jobs already enqueued
                            queue_ids.append(str(iterator_event_id))
                            continue
                            
                        except Exception as e:
                            logger.exception(f"Error emitting iterator_started for step '{step_name}'")
                            raise
                    
                    if is_iterator_old and context:
                        from noetl.core.dsl.render import render_template
                        from jinja2 import BaseLoader, Environment
                        
                        try:
                            env = Environment(loader=BaseLoader())
                            # Save the task block before rendering (OLD format)
                            task_block = step_cfg.get("task")
                            
                            # Remove task block temporarily to prevent rendering
                            if task_block:
                                step_cfg_without_task = {k: v for k, v in step_cfg.items() if k != "task"}
                            else:
                                step_cfg_without_task = step_cfg
                            
                            # Render iterator config (collection, element, mode, etc.)
                            # This will render {{ workload.items }} in collection
                            step_cfg_rendered = render_template(
                                env, step_cfg_without_task, context, rules=None, strict_keys=False
                            )
                            
                            # Restore the task block unrendered
                            if task_block:
                                step_cfg_rendered["task"] = task_block
                            
                            step_cfg = step_cfg_rendered
                        except Exception as e:
                            logger.warning(f"Failed to render iterator config for step '{step_name}': {e}")
                    
                    # Restore loop block after rendering (worker will render it with item context)
                    if loop_block is not None:
                        step_cfg["loop"] = loop_block
                        logger.critical(f"PUBLISHER: Restored loop block for step '{step_name}'")
                    
                    # Restore sink block after rendering (worker will render it with result context)
                    if sink_block is not None:
                        step_cfg["sink"] = sink_block
                        logger.critical(f"PUBLISHER: Restored sink block for step '{step_name}'")

                    # Encode step config for queue
                    encoded_step_cfg = encode_task_for_queue(step_cfg)

                    task_context = {
                        "execution_id": execution_id,
                        "step_name": step_name,
                        "step_type": step_def["step_type"],
                        "step_config": encoded_step_cfg,
                    }
                    if context:
                        task_context["workload"] = context.get("workload", {})

                    action = json.dumps(
                        encoded_step_cfg
                    )  # Use encoded config for action
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
                        parent_execution_id=parent_execution_id,
                        event_id=None,
                        queue_id=queue_id,
                        status="queued",
                        metadata=metadata,
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
        metadata: Optional[Dict[str, Any]] = None,
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
        # CRITICAL: Preserve blocks that should NOT be rendered server-side
        # These blocks contain templates ({{ item }}, {{ result }}) that must be
        # rendered worker-side AFTER task execution completes
        
        # Make a copy to avoid mutating the original config
        step_config_copy = dict(step_config)
        
        # DEBUG: Log incoming step_config keys
        logger.critical(f"PUBLISHER.publish_step ENTRY: step='{step_name}', keys={list(step_config.keys())}, has_loop={'loop' in step_config}")
        
        # 1. Always preserve sink block (contains {{ result }} templates)
        sink_block = step_config_copy.pop("sink", None)
        if sink_block is not None:
            logger.critical(f"PUBLISHER.publish_step: Extracted sink block for step '{step_name}': {sink_block}")
        
        # 2. Check for loop block - handle via server-side iteration instead of queue
        loop_block = step_config_copy.pop("loop", None)
        if loop_block is not None:
            logger.info(f"PUBLISHER: Step '{step_name}' has loop attribute, initiating server-side iteration")
            
            # Emit iterator_started event (server-side only)
            from noetl.server.api.broker.schema import EventEmitRequest
            from noetl.server.api.broker.service import EventService
            
            # Build iterator context with collection metadata
            # Render the collection template if it's a string (Jinja2 template)
            from noetl.core.dsl.render import render_template
            from jinja2 import BaseLoader, Environment
            
            # Support BOTH old format (in/iterator) and new format (collection/element)
            collection_raw = loop_block.get("collection") or loop_block.get("in", [])
            iterator_name = loop_block.get("element") or loop_block.get("iterator", "item")
            
            logger.critical(f"PUBLISHER.publish_step: collection_raw = {collection_raw}, type = {type(collection_raw).__name__}")
            if isinstance(collection_raw, str):
                try:
                    # Build full render context with step results for collection template
                    from noetl.server.api.run.orchestrator import OrchestratorQueries
                    render_ctx = {"workload": (context or {}).get("workload", {})}
                    
                    # Fetch all step results for this execution
                    result_rows = await OrchestratorQueries.get_step_results(int(execution_id))
                    logger.critical(f"PUBLISHER.publish_step: Fetched {len(result_rows)} step results")
                    for res_row in result_rows:
                        if res_row["node_name"] and res_row["result"]:
                            # Normalize result: if it has 'data' field, use that
                            result_value = res_row["result"]
                            if isinstance(result_value, dict) and "data" in result_value:
                                result_value = result_value["data"]
                            render_ctx[res_row["node_name"]] = result_value
                            logger.critical(f"PUBLISHER.publish_step: Added '{res_row['node_name']}' to context")
                    
                    # Render the template with full context (workload + step results)
                    logger.critical(f"PUBLISHER.publish_step: Rendering template '{collection_raw}'")
                    logger.critical(f"PUBLISHER.publish_step: Context keys: {list(render_ctx.keys())}")
                    env = Environment(loader=BaseLoader())
                    collection = render_template(env, collection_raw, render_ctx)
                    logger.critical(f"PUBLISHER.publish_step: Rendered! Type={type(collection).__name__}, len={len(collection) if isinstance(collection, (list, str)) else 'N/A'}")
                except Exception as e:
                    logger.critical(f"PUBLISHER.publish_step: EXCEPTION during rendering: {e}")
                    logger.exception("Full traceback:")
                    collection = collection_raw  # Fall back to raw template
            else:
                collection = collection_raw
            
            # CRITICAL: Restore sink to nested_task BEFORE passing to iterator
            # Sink needs to execute per iteration in the worker
            if sink_block is not None:
                step_config_copy["sink"] = sink_block
                logger.critical(f"PUBLISHER.publish_step: Restored sink to nested_task for iterator step '{step_name}'")
            
            iterator_context = {
                "collection": collection,
                "iterator_name": iterator_name,
                "mode": loop_block.get("mode", "sequential"),
                "nested_task": step_config_copy,  # The actual task config to execute per iteration
                "total_count": len(collection) if isinstance(collection, list) else 0
            }
            
            iterator_started_request = EventEmitRequest(
                execution_id=str(execution_id),
                catalog_id=catalog_id,
                event_type="iterator_started",
                status="RUNNING",
                node_id=step_name,
                node_name="iterator",
                node_type="iterator",
                parent_event_id=parent_event_id,
                context=iterator_context
            )
            
            try:
                result = await EventService.emit_event(iterator_started_request)
                iterator_event_id = result.event_id
                logger.info(f"Emitted iterator_started for '{step_name}', event_id={iterator_event_id}")
                
                # Process iterator_started to enqueue iteration jobs
                # Import here to avoid circular dependency
                from noetl.server.api.run.orchestrator import _process_iterator_started
                event_obj = {
                    'context': iterator_context,
                    'catalog_id': catalog_id,
                    'node_id': step_name,
                    'node_name': step_name,
                    'event_id': iterator_event_id
                }
                await _process_iterator_started(int(execution_id), event_obj)
                
                # Return a placeholder queue_id (no actual queue job created)
                return str(iterator_event_id)
                
            except Exception as e:
                logger.exception(f"Error emitting iterator_started for step '{step_name}'")
                raise
        
        #3. For OLD iterator format: preserve nested 'task' block
        tool_raw = step_config_copy.get("tool") or ""
        if isinstance(tool_raw, dict):
            step_tool = (tool_raw.get("kind") or tool_raw.get("type") or "").lower()
        else:
            step_tool = tool_raw.lower() if isinstance(tool_raw, str) else str(tool_raw).lower()
        task_block = None
        if step_tool == "iterator":
            task_block = step_config_copy.pop("task", None)
            if task_block is not None:
                logger.critical(f"PUBLISHER.publish_step: Extracted task block for iterator step '{step_name}'")
        
        # Generate queue_id from database
        queue_id = await get_snowflake_id()

        # Encode task config for queue (base64 encode code/command fields)
        # Use the config with preserved blocks removed
        encoded_step_config = encode_task_for_queue(step_config_copy)
        
        # Restore preserved blocks AFTER encoding but BEFORE queue insertion
        # This ensures they bypass server-side rendering but get passed to worker
        if sink_block is not None:
            encoded_step_config["sink"] = sink_block
            logger.critical(f"PUBLISHER.publish_step: Restored sink block for step '{step_name}'")
        
        if loop_block is not None:
            encoded_step_config["loop"] = loop_block
            logger.critical(f"PUBLISHER.publish_step: Restored loop block for step '{step_name}'")
        
        if task_block is not None:
            encoded_step_config["task"] = task_block
            logger.critical(f"PUBLISHER.publish_step: Restored task block for iterator step '{step_name}'")

        # Build task context
        task_context = {
            "execution_id": execution_id,
            "step_name": step_name,
            "step_type": step_type,
            "step_config": encoded_step_config,
        }

        if context:
            task_context.update(context)

        # Make available after delay (use UTC timezone-aware datetime)
        available_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)

        # Lazy import to avoid circular dependency
        from noetl.server.api.queue.service import QueueService

        # Extract parent_execution_id from context if available
        parent_execution_id = context.get("parent_execution_id") if context else None
        
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
            parent_execution_id=parent_execution_id,
            event_id=None,
            queue_id=queue_id,
            status="queued",
            metadata=metadata,
        )

        logger.info(
            f"Published step '{step_name}' to queue: "
            f"execution_id={execution_id}, queue_id={response.id}, priority={priority}"
        )

        # Emit step_started event when step is enqueued
        try:
            from noetl.server.api.broker.schema import EventEmitRequest
            from noetl.server.api.broker.service import EventService

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
                meta={"emitter": "publisher", "queue_id": str(response.id)},
            )

            step_started_result = await EventService.emit_event(step_started_request)
            logger.debug(
                f"Emitted step_started event for '{step_name}', event_id={step_started_result.event_id}"
            )
            
            # Update queue entry with event_id
            async with get_pool_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "UPDATE noetl.queue SET event_id = %s WHERE queue_id = %s",
                        (step_started_result.event_id, response.id)
                    )
                    await conn.commit()
                    
        except Exception as e:
            logger.warning(
                f"Failed to emit step_started event for step '{step_name}': {e}",
                exc_info=True,
            )

        return response.id
