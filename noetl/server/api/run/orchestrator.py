"""
Execution Orchestrator - Event-driven workflow coordination.

Architecture:
1. Worker executes task → Reports result as EVENT via /api/v1/event/emit
2. Event endpoint triggers orchestrator.evaluate_execution()
3. Orchestrator reconstructs state from events
4. Orchestrator publishes next actionable tasks to QUEUE
5. Workers pick up tasks from queue and repeat cycle

Flow:
- Initial: Dispatch first workflow step to queue
- In Progress: Analyze events, evaluate transitions, publish next steps to queue
- Completed: Mark execution finished

Pure event sourcing - NO business logic in events, orchestrator decides everything.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import yaml
from jinja2 import Environment, TemplateSyntaxError, UndefinedError
from psycopg.rows import dict_row

from noetl.core.db.pool import get_pool_connection, get_snowflake_id
from noetl.core.logger import setup_logger
from noetl.server.api.broker.service import EventService
from noetl.server.api.catalog.service import CatalogService
from noetl.server.api.run.publisher import QueuePublisher
from noetl.server.api.run.queries import OrchestratorQueries

logger = setup_logger(__name__, include_location=True)


def _render_with_params(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Render with_params (args from next transitions) with Jinja2 templates.

    Args:
        params: Parameters dict that may contain Jinja2 templates
        context: Execution context with step results for rendering

    Returns:
        Rendered parameters dict
    """
    try:
        from noetl.core.dsl.render import render_template
        from jinja2 import BaseLoader, Environment
        
        env = Environment(loader=BaseLoader())
        rendered = render_template(env, params, context, rules=None, strict_keys=False)
        logger.debug(f"Rendered with_params: {params} -> {rendered}")
        return rendered if isinstance(rendered, dict) else params
    except Exception as e:
        logger.warning(f"Failed to render with_params: {e}, using original params")
        return params


def _evaluate_jinja_condition(condition: str, context: Dict[str, Any]) -> bool:
    """
    Evaluate a Jinja2 condition expression.

    Args:
        condition: Jinja2 expression (without {{ }})
        context: Dictionary with variables for evaluation

    Returns:
        True if condition evaluates to truthy value
    """
    try:
        env = Environment()
        # Wrap condition in {{ }} if not already wrapped
        expr = condition.strip()
        if not (expr.startswith("{{") and expr.endswith("}}")):
            expr = f"{{{{ {expr} }}}}"

        template = env.from_string(expr)
        result = template.render(**context)

        # Convert string result to boolean
        if isinstance(result, str):
            result = result.strip().lower()
            return result not in ("false", "0", "", "none", "null")

        return bool(result)
    except (TemplateSyntaxError, UndefinedError) as e:
        logger.warning(f"Failed to evaluate condition '{condition}': {e}")
        return False
    except Exception as e:
        logger.exception(f"Error evaluating condition '{condition}'")
        return False


async def _check_execution_completion(
    execution_id: str, workflow_steps: Dict[str, Dict]
) -> None:
    """
    Check if execution should be finalized by checking for pending/running actions.
    
    Completion criteria:
    - No actions are currently running (action_started without action_completed)
    - No steps are queued and pending execution
    - Workflow has reached an end state (no more transitions to process)
    
    This approach correctly handles:
    - Unreachable workflow branches (they never start, so don't block completion)
    - Dynamic workflows where not all defined steps execute
    - Workflows that reach 'end' step naturally

    Args:
        execution_id: Execution ID
        workflow_steps: Dictionary of step_name -> step_definition (unused but kept for API compatibility)
    """
    async with get_pool_connection() as conn:
        async with conn.cursor() as cur:
            # Check for any running actions (action_started without corresponding action_completed)
            await cur.execute(
                """
                SELECT COUNT(*) as running_count
                FROM (
                    SELECT node_name
                    FROM noetl.event
                    WHERE execution_id = %(execution_id)s
                      AND event_type = 'action_started'
                    EXCEPT
                    SELECT node_name
                    FROM noetl.event
                    WHERE execution_id = %(execution_id)s
                      AND event_type = 'action_completed'
                ) AS running_actions
                """,
                {"execution_id": int(execution_id)},
            )
            row = await cur.fetchone()
            running_count = row["running_count"] if row else 0

            # Check for any pending jobs in the queue
            await cur.execute(
                """
                SELECT COUNT(*) as pending_count
                FROM noetl.queue
                WHERE execution_id = %(execution_id)s
                  AND status IN ('pending', 'running')
                """,
                {"execution_id": int(execution_id)},
            )
            row = await cur.fetchone()
            pending_count = row["pending_count"] if row else 0
            
            # Also check for steps that are started but not completed
            await cur.execute(
                """
                SELECT COUNT(*) as incomplete_steps
                FROM (
                    SELECT node_name
                    FROM noetl.event
                    WHERE execution_id = %(execution_id)s
                      AND event_type = 'step_started'
                    EXCEPT
                    SELECT node_name
                    FROM noetl.event
                    WHERE execution_id = %(execution_id)s
                      AND event_type IN ('step_completed', 'step_failed')
                ) AS incomplete
                """,
                {"execution_id": int(execution_id)},
            )
            row = await cur.fetchone()
            incomplete_steps = row["incomplete_steps"] if row else 0

            logger.info(
                f"Execution {execution_id}: running_actions={running_count}, pending_jobs={pending_count}, incomplete_steps={incomplete_steps}"
            )

            # If there are any running actions, pending jobs, or incomplete steps, execution is not complete
            if running_count > 0 or pending_count > 0 or incomplete_steps > 0:
                logger.debug(
                    f"Execution {execution_id} not complete: {running_count} running, {pending_count} pending"
                )
                return

            # No pending work - execution is complete, emit completion events
            logger.info(f"All active work completed for execution {execution_id}, finalizing")

            # Get catalog_id and catalog path from playbook_started event
            await cur.execute(
                """
                SELECT catalog_id, node_name as catalog_path
                FROM noetl.event
                WHERE execution_id = %(execution_id)s
                  AND event_type = 'playbook_started'
                LIMIT 1
                """,
                {"execution_id": int(execution_id)},
            )
            row = await cur.fetchone()
            if not row:
                logger.warning(
                    f"No playbook_started event found for {execution_id}"
                )
                return

            catalog_id = row["catalog_id"]
            catalog_path = row["catalog_path"]

            # Get parent_event_id from workflow_initialized event
            await cur.execute(
                """
                SELECT event_id as parent_event_id
                FROM noetl.event
                WHERE execution_id = %(execution_id)s
                  AND event_type = 'workflow_initialized'
                LIMIT 1
                """,
                {"execution_id": int(execution_id)},
            )
            row = await cur.fetchone()
            parent_event_id = row["parent_event_id"] if row else None

            now = datetime.now(timezone.utc)
            meta = {"emitted_at": now.isoformat(), "emitter": "orchestrator"}

            try:
                # Emit workflow_completed event first
                workflow_event_id = await get_snowflake_id()
                await cur.execute(
                    """
                    INSERT INTO noetl.event (
                        execution_id,
                        catalog_id,
                        event_id,
                        parent_event_id,
                        event_type,
                        node_id,
                        node_name,
                        node_type,
                        status,
                        meta,
                        created_at
                    ) VALUES (
                        %(execution_id)s,
                        %(catalog_id)s,
                        %(event_id)s,
                        %(parent_event_id)s,
                        %(event_type)s,
                        %(node_id)s,
                        %(node_name)s,
                        %(node_type)s,
                        %(status)s,
                        %(meta)s,
                        %(created_at)s
                    )
                    """,
                    {
                        "execution_id": int(execution_id),
                        "catalog_id": catalog_id,
                        "event_id": workflow_event_id,
                        "parent_event_id": parent_event_id,
                        "event_type": "workflow_completed",
                        "node_id": "workflow",
                        "node_name": "workflow",
                        "node_type": "workflow",
                        "status": "COMPLETED",
                        "meta": json.dumps(meta),
                        "created_at": now,
                    },
                )
                logger.info(
                    f"Emitted workflow_completed event_id={workflow_event_id} for execution {execution_id}"
                )

                # Then emit playbook_completed event
                execution_event_id = await get_snowflake_id()
                await cur.execute(
                    """
                    INSERT INTO noetl.event (
                        execution_id,
                        catalog_id,
                        event_id,
                        parent_event_id,
                        event_type,
                        node_id,
                        node_name,
                        node_type,
                        status,
                        meta,
                        created_at
                    ) VALUES (
                        %(execution_id)s,
                        %(catalog_id)s,
                        %(event_id)s,
                        %(parent_event_id)s,
                        %(event_type)s,
                        %(node_id)s,
                        %(node_name)s,
                        %(node_type)s,
                        %(status)s,
                        %(meta)s,
                        %(created_at)s
                    )
                    """,
                    {
                        "execution_id": int(execution_id),
                        "catalog_id": catalog_id,
                        "event_id": execution_event_id,
                        "parent_event_id": workflow_event_id,
                        "event_type": "playbook_completed",
                        "node_id": "playbook",
                        "node_name": catalog_path,
                        "node_type": "execution",
                        "status": "COMPLETED",
                        "meta": json.dumps(meta),
                        "created_at": now,
                    },
                )
                logger.info(
                    f"Emitted playbook_completed event_id={execution_event_id} for execution {execution_id}"
                )
                await conn.commit()

            except Exception:
                await conn.rollback()
                logger.exception(
                    f"Error emitting completion events for {execution_id}"
                )


async def evaluate_execution(
    execution_id: str,
    trigger_event_type: Optional[str] = None,
    trigger_event_id: Optional[str] = None,
) -> None:
    """
    Main orchestrator - analyzes events and publishes actionable tasks to queue.

    Called by:
    - /api/v1/event/emit endpoint after worker reports results
    - Initial execution start (from /api/v1/run)

    Workflow:
    1. Read all events for execution_id from event table
    2. Reconstruct current execution state
    3. Determine what tasks are needed next
    4. Publish tasks to queue table for workers

    Args:
        execution_id: Execution to orchestrate
        trigger_event_type: Event type that triggered this call
        trigger_event_id: Event ID that triggered this call

    Event triggers:
        - execution_start: Publish first step to queue
        - step_end/action_completed: Analyze results, publish next steps
        - error/failed: Handle failures
    """
    # Convert execution_id to int for database queries
    try:
        exec_id = int(execution_id)
    except (ValueError, TypeError):
        logger.error(f"Invalid execution_id format: {execution_id}")
        return

    logger.info(
        f"ORCHESTRATOR: Evaluating execution_id={exec_id}, "
        f"trigger={trigger_event_type}, event_id={trigger_event_id}"
    )

    # Ignore progress marker events - they don't trigger orchestration
    if trigger_event_type in ("step_started", "step_running"):
        logger.debug(
            f"ORCHESTRATOR: Ignoring progress marker event {trigger_event_type}"
        )
        return

    try:
        # Handle action failures - emit step_failed, workflow_failed, playbook_failed
        if trigger_event_type == "action_failed":
            logger.info(
                f"ORCHESTRATOR: Detected action_failed, emitting failure events for execution {exec_id}"
            )
            await _handle_action_failure(exec_id, trigger_event_id)
            return

        # Check for failure states
        if await _has_failed(exec_id):
            logger.info(
                f"ORCHESTRATOR: Execution {exec_id} has failed, stopping orchestration"
            )
            return

        # Reconstruct execution state from events
        state = await _get_execution_state(exec_id)
        logger.debug(f"ORCHESTRATOR: Execution {exec_id} state={state}")

        if state == "initial":
            # No progress yet - dispatch first workflow step
            logger.info(
                f"ORCHESTRATOR: Dispatching initial step for execution {exec_id}"
            )
            await _dispatch_first_step(exec_id)

        elif state == "in_progress":
            # Steps are running - process completions and transitions
            # Process transitions for worker-reported completions
            if trigger_event_type in (
                "action_completed",
                "step_result",
                "step_end",
                "step_completed",
            ):
                logger.info(
                    f"ORCHESTRATOR: Processing transitions for execution {exec_id}"
                )
                await _process_transitions(exec_id)
            else:
                logger.debug(
                    f"ORCHESTRATOR: No transition processing needed for {trigger_event_type}"
                )

            # Check for iterator completions (child executions)
            # When a child execution completes, check if all siblings are done
            if trigger_event_type in (
                "playbook_completed",
                "execution_complete",
                "execution_end",
            ):
                logger.debug(
                    f"ORCHESTRATOR: Checking iterator completions for execution {exec_id}"
                )
                await _check_iterator_completions(exec_id)

        elif state == "completed":
            logger.debug(
                f"ORCHESTRATOR: Execution {exec_id} already completed, no action needed"
            )

        logger.debug(f"ORCHESTRATOR: Evaluation complete for execution {exec_id}")

    except Exception as e:
        logger.exception(f"ORCHESTRATOR: Error evaluating execution {exec_id}")
        # Don't re-raise - orchestrator errors shouldn't break the system


async def _has_failed(execution_id: int) -> bool:
    """
    Check if execution has encountered failure by examining event log.

    Args:
        execution_id: Execution to check

    Returns:
        True if any failure/error events exist
    """
    return await OrchestratorQueries.has_execution_failed(execution_id)


async def _handle_action_failure(execution_id: int, action_failed_event_id: Optional[str]) -> None:
    """
    Handle action failure by emitting step_failed, workflow_failed, and playbook_failed events.
    
    When a worker reports action_failed, the orchestrator must emit:
    1. step_failed - Mark the step as failed
    2. workflow_failed - Mark the workflow as failed
    3. playbook_failed - Mark the playbook execution as failed
    
    Args:
        execution_id: Execution ID
        action_failed_event_id: Event ID of the action_failed event
    """
    logger.info(f"ORCHESTRATOR: Handling action failure for execution {execution_id}")
    
    # Get the failed action details and catalog info
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            # Get action_failed event details
            await cur.execute(
                """
                SELECT e.node_name, e.node_type, e.error, e.stack_trace, e.result, e.catalog_id,
                       c.path as catalog_path
                FROM noetl.event e
                JOIN noetl.catalog c ON e.catalog_id = c.catalog_id
                WHERE e.execution_id = %(execution_id)s
                  AND e.event_type = 'action_failed'
                  AND e.event_id = %(event_id)s
                LIMIT 1
                """,
                {"execution_id": execution_id, "event_id": action_failed_event_id},
            )
            failed_action = await cur.fetchone()
    
    if not failed_action:
        logger.error(
            f"ORCHESTRATOR: Could not find action_failed event {action_failed_event_id} "
            f"for execution {execution_id}"
        )
        return
    
    step_name = failed_action["node_name"]
    error_message = failed_action.get("error", "Unknown error")
    catalog_id = failed_action["catalog_id"]
    catalog_path = failed_action["catalog_path"]
    
    logger.info(
        f"ORCHESTRATOR: Emitting failure events for step '{step_name}' "
        f"in execution {execution_id}"
    )
    
    # Emit events in a single transaction
    async with get_pool_connection() as conn:
        async with conn.cursor() as cur:
            try:
                now = datetime.now(timezone.utc)
                meta = {"failed_at": now.isoformat()}
                
                # 1. Emit step_failed event
                step_failed_event_id = await get_snowflake_id()
                await cur.execute(
                    """
                    INSERT INTO noetl.event (
                        execution_id,
                        catalog_id,
                        event_id,
                        parent_event_id,
                        event_type,
                        node_id,
                        node_name,
                        node_type,
                        status,
                        error,
                        meta,
                        created_at
                    ) VALUES (
                        %(execution_id)s,
                        %(catalog_id)s,
                        %(event_id)s,
                        %(parent_event_id)s,
                        %(event_type)s,
                        %(node_id)s,
                        %(node_name)s,
                        %(node_type)s,
                        %(status)s,
                        %(error)s,
                        %(meta)s,
                        %(created_at)s
                    )
                    """,
                    {
                        "execution_id": execution_id,
                        "catalog_id": catalog_id,
                        "event_id": step_failed_event_id,
                        "parent_event_id": int(action_failed_event_id) if action_failed_event_id else None,
                        "event_type": "step_failed",
                        "node_id": step_name,
                        "node_name": step_name,
                        "node_type": "step",
                        "status": "FAILED",
                        "error": error_message,
                        "meta": json.dumps(meta),
                        "created_at": now,
                    },
                )
                logger.info(
                    f"Emitted step_failed event_id={step_failed_event_id} for execution {execution_id}"
                )
                
                # 2. Emit workflow_failed event
                workflow_failed_event_id = await get_snowflake_id()
                await cur.execute(
                    """
                    INSERT INTO noetl.event (
                        execution_id,
                        catalog_id,
                        event_id,
                        parent_event_id,
                        event_type,
                        node_id,
                        node_name,
                        node_type,
                        status,
                        error,
                        meta,
                        created_at
                    ) VALUES (
                        %(execution_id)s,
                        %(catalog_id)s,
                        %(event_id)s,
                        %(parent_event_id)s,
                        %(event_type)s,
                        %(node_id)s,
                        %(node_name)s,
                        %(node_type)s,
                        %(status)s,
                        %(error)s,
                        %(meta)s,
                        %(created_at)s
                    )
                    """,
                    {
                        "execution_id": execution_id,
                        "catalog_id": catalog_id,
                        "event_id": workflow_failed_event_id,
                        "parent_event_id": step_failed_event_id,
                        "event_type": "workflow_failed",
                        "node_id": "workflow",
                        "node_name": "workflow",
                        "node_type": "workflow",
                        "status": "FAILED",
                        "error": f"Workflow failed at step '{step_name}': {error_message}",
                        "meta": json.dumps(meta),
                        "created_at": now,
                    },
                )
                logger.info(
                    f"Emitted workflow_failed event_id={workflow_failed_event_id} for execution {execution_id}"
                )
                
                # 3. Emit playbook_failed event
                playbook_failed_event_id = await get_snowflake_id()
                await cur.execute(
                    """
                    INSERT INTO noetl.event (
                        execution_id,
                        catalog_id,
                        event_id,
                        parent_event_id,
                        event_type,
                        node_id,
                        node_name,
                        node_type,
                        status,
                        error,
                        meta,
                        created_at
                    ) VALUES (
                        %(execution_id)s,
                        %(catalog_id)s,
                        %(event_id)s,
                        %(parent_event_id)s,
                        %(event_type)s,
                        %(node_id)s,
                        %(node_name)s,
                        %(node_type)s,
                        %(status)s,
                        %(error)s,
                        %(meta)s,
                        %(created_at)s
                    )
                    """,
                    {
                        "execution_id": execution_id,
                        "catalog_id": catalog_id,
                        "event_id": playbook_failed_event_id,
                        "parent_event_id": workflow_failed_event_id,
                        "event_type": "playbook_failed",
                        "node_id": "playbook",
                        "node_name": catalog_path,
                        "node_type": "execution",
                        "status": "FAILED",
                        "error": f"Playbook failed at step '{step_name}': {error_message}",
                        "meta": json.dumps(meta),
                        "created_at": now,
                    },
                )
                logger.info(
                    f"Emitted playbook_failed event_id={playbook_failed_event_id} for execution {execution_id}"
                )
                
                await conn.commit()
                
            except Exception:
                await conn.rollback()
                logger.exception(
                    f"Error emitting failure events for {execution_id}"
                )
    
    logger.info(
        f"ORCHESTRATOR: Successfully emitted failure events for execution {execution_id}"
    )


async def _get_execution_state(execution_id: int) -> str:
    """
    Reconstruct execution state from event log.

    State reconstruction logic:
    1. Check for execution_complete/execution_end events -> 'completed'
    2. Check for any action_completed events -> 'in_progress'
    3. Check for queued/leased jobs -> 'in_progress'
    4. Otherwise -> 'initial'

    Args:
        execution_id: Execution to check

    Returns:
        State: 'initial', 'in_progress', or 'completed'
    """
    async with get_pool_connection() as conn:
        async with conn.cursor() as cur:
            # Check for completion
            await cur.execute(
                """
                SELECT 1 FROM noetl.event
                WHERE execution_id = %(execution_id)s
                  AND event_type IN ('playbook_completed', 'execution_complete', 'execution_end')
                LIMIT 1
                """,
                {"execution_id": execution_id},
            )
            if await cur.fetchone():
                return "completed"

            # Check for any completed actions
            await cur.execute(
                """
                SELECT 1 FROM noetl.event
                WHERE execution_id = %(execution_id)s
                  AND event_type IN ('action_completed', 'step_end')
                LIMIT 1
                """,
                {"execution_id": execution_id},
            )
            if await cur.fetchone():
                return "in_progress"

            # Check for active queue items using query executor
            if await OrchestratorQueries.has_pending_queue_jobs(execution_id):
                return "in_progress"

            return "initial"


async def _dispatch_first_step(execution_id: str) -> None:
    """
    Publish first workflow step to queue for worker execution.

    Process:
    1. Query workflow table for step where step_name = 'start'
    2. Create actionable task (job) in queue table
    3. Worker will pick it up, execute, and report result via event endpoint

    TODO: Implement workflow query and queue publishing
    """
    logger.info(f"Dispatching first step for execution {execution_id}")
    # TODO: Query workflow table to find 'start' step
    # TODO: Use QueuePublisher to publish step to queue
    # Workers will execute and report results back via /api/v1/event/emit
    pass


async def _process_transitions(execution_id: int) -> None:
    """
    Analyze completed steps and publish next actionable tasks to queue.

    Process:
    1. Query events to find steps with action_completed but no step_completed
    2. Query transition table for matching step completions
    3. Evaluate Jinja2 conditions in transitions
    4. Emit step_completed events
    5. Publish next steps to queue table as actionable tasks
    6. Workers execute and report results back via events
    """
    logger.info(f"Processing transitions for execution {execution_id}")

    # Find completed steps without step_completed event using async executor
    completed_steps = (
        await OrchestratorQueries.get_completed_steps_without_step_completed(
            execution_id
        )
    )

    if completed_steps:
        logger.info(f"Found {len(completed_steps)} completed steps: {completed_steps}")
    else:
        logger.debug(f"No new completed steps found for execution {execution_id}")

    # Get catalog_id
    catalog_id = await EventService.get_catalog_id_from_execution(execution_id)

    # Get execution metadata using async executor
    metadata = await OrchestratorQueries.get_execution_metadata(execution_id)
    if not metadata:
        logger.warning(f"No execution metadata found for {execution_id}")
        return

    pb_path = metadata.get("path")
    pb_version = metadata.get("version", "latest")

    # Load playbook from catalog
    catalog_entry = await CatalogService.fetch_entry(catalog_id=catalog_id)
    if not catalog_entry or not catalog_entry.content:
        logger.warning(f"No playbook content found for catalog_id {catalog_id}")
        return

    playbook = yaml.safe_load(catalog_entry.content)
    workload = playbook.get("workload", {})

    # Build step index
    workflow_steps = playbook.get("workflow", [])
    by_name = {}
    for step_def in workflow_steps:
        step_name = step_def.get("step")
        if step_name:
            by_name[step_name] = step_def

    if not completed_steps:
        await _check_execution_completion(execution_id, by_name)
        return

    # Query all transitions using async executor
    transition_rows = await OrchestratorQueries.get_transitions(execution_id)

    # Group transitions by from_step
    transitions_by_step = {}
    for tr in transition_rows:
        from_step = tr["from_step"]
        if from_step not in transitions_by_step:
            transitions_by_step[from_step] = []
        transitions_by_step[from_step].append(tr)

    # Build evaluation context with all step results using async executor
    eval_ctx = {"workload": workload}
    result_rows = await OrchestratorQueries.get_step_results(execution_id)
    for res_row in result_rows:
        if res_row["node_name"] and res_row["result"]:
            # Normalize result: if it has 'data' field, use that instead of the envelope
            result_value = res_row["result"]
            if isinstance(result_value, dict) and "data" in result_value:
                result_value = result_value["data"]
            eval_ctx[res_row["node_name"]] = result_value

    async with get_pool_connection() as conn:
        async with conn.cursor() as cur:
            # Process each completed step
            for step_name in completed_steps:
                logger.info(f"Processing transitions for completed step '{step_name}'")

                # Add current step result as 'result' for condition evaluation
                if step_name in eval_ctx:
                    eval_ctx["result"] = eval_ctx[step_name]
                    logger.debug(
                        f"Added result to eval_ctx for '{step_name}': {eval_ctx['result']}"
                    )
                else:
                    logger.warning(
                        f"No result found in eval_ctx for step '{step_name}'"
                    )

                # Get step definition to extract node_type
                step_def = by_name.get(step_name, {})
                tool_name = step_def.get("tool")
                if not isinstance(tool_name, str) or not tool_name.strip():
                    if step_name.lower() == "start":
                        step_type = "router"
                    else:
                        raise ValueError(
                            f"Workflow step '{step_name}' is missing required 'tool'"
                        )
                else:
                    step_type = tool_name.strip().lower()

                # Query action_completed event to get parent_event_id from queue_meta using async executor
                parent_event_id = None
                try:
                    action_meta = await OrchestratorQueries.get_action_completed_meta(
                        execution_id, step_name
                    )
                    if action_meta and isinstance(action_meta, dict):
                        queue_meta = action_meta.get("queue_meta", {})
                        if isinstance(queue_meta, dict):
                            parent_event_id = queue_meta.get("parent_event_id")
                            logger.debug(
                                f"Extracted parent_event_id={parent_event_id} from action_completed.meta.queue_meta for '{step_name}'"
                            )
                except Exception as e:
                    logger.warning(
                        f"Could not extract parent_event_id from action_completed for '{step_name}': {e}"
                    )

                # Emit step_completed event - use EventService directly (not HTTP)
                from noetl.server.api.broker.schema import EventEmitRequest

                step_completed_request = EventEmitRequest(
                    execution_id=str(execution_id),
                    catalog_id=catalog_id,
                    event_type="step_completed",
                    status="COMPLETED",
                    node_id=step_name,
                    node_name=step_name,
                    node_type=step_type,
                    parent_event_id=parent_event_id,
                )

                step_completed_event_id = None
                try:
                    result = await EventService.emit_event(step_completed_request)
                    step_completed_event_id = result.event_id
                    logger.info(
                        f"Emitted step_completed for '{step_name}', event_id={step_completed_event_id}"
                    )
                except Exception as e:
                    logger.exception(
                        f"Error emitting step_completed for step '{step_name}'"
                    )

                # Get transitions for this step
                step_transitions = transitions_by_step.get(step_name, [])

                if not step_transitions:
                    logger.info(f"No transitions found for step '{step_name}'")
                    # Check if execution should be finalized
                    await _check_execution_completion(execution_id, by_name)
                    continue

                logger.info(
                    f"Evaluating {len(step_transitions)} transitions for '{step_name}'"
                )

                # Evaluate each transition
                for transition in step_transitions:
                    to_step = transition["to_step"]
                    condition = transition["condition"]
                    with_params = transition.get("with_params") or {}

                    # Ensure with_params is a dict (could be string from DB)
                    if isinstance(with_params, str):
                        import json

                        try:
                            with_params = json.loads(with_params)
                        except:
                            with_params = {}
                    elif not isinstance(with_params, dict):
                        with_params = {}

                    # Evaluate condition if present
                    if condition:
                        result_val = _evaluate_jinja_condition(condition, eval_ctx)
                        logger.debug(
                            f"Condition '{condition}' evaluated to {result_val} with context keys: {list(eval_ctx.keys())}"
                        )
                        if not result_val:
                            logger.debug(
                                f"Condition not met for {step_name} -> {to_step}"
                            )
                            continue
                        logger.info(f"Condition met for {step_name} -> {to_step}")

                    # Get next step definition
                    next_step_def = by_name.get(to_step)
                    if not next_step_def:
                        logger.warning(f"Next step '{to_step}' not found in workflow")
                        continue

                    # Check if step has actionable type (not router/end)
                    next_step_tool = next_step_def.get("tool")
                    if (
                        not isinstance(next_step_tool, str)
                        or not next_step_tool.strip()
                    ):
                        if to_step.lower() == "end":
                            next_step_type = "end"
                        else:
                            next_step_type = "router"
                    else:
                        next_step_type = next_step_tool.strip().lower()

                    # If it's an "end" step, just emit step_completed and skip
                    if next_step_type == "end":
                        logger.info(
                            f"Next step '{to_step}' is end step, skipping enqueue"
                        )
                        continue

                    # If it's a router (no type or type="router"), emit step_completed and process its transitions
                    if next_step_type in ("router", ""):
                        logger.info(
                            f"Next step '{to_step}' is router step, emitting step_completed and processing its transitions"
                        )

                        # Use the current step's step_completed event_id as parent
                        router_parent_event_id = step_completed_event_id

                        # Emit step_completed for the router step
                        from noetl.server.api.broker.schema import EventEmitRequest

                        router_completed_request = EventEmitRequest(
                            execution_id=str(execution_id),
                            catalog_id=catalog_id,
                            event_type="step_completed",
                            status="COMPLETED",
                            node_id=to_step,
                            node_name=to_step,
                            node_type="router",
                            parent_event_id=router_parent_event_id,
                        )
                        try:
                            await EventService.emit_event(router_completed_request)
                            logger.info(
                                f"Emitted step_completed for router step '{to_step}'"
                            )
                        except Exception as e:
                            logger.exception(
                                f"Error emitting step_completed for router step '{to_step}'"
                            )

                        # Get router's transitions and publish its next steps
                        router_transitions = transitions_by_step.get(to_step, [])
                        for router_transition in router_transitions:
                            router_next_step = router_transition["to_step"]
                            router_next_def = by_name.get(router_next_step)
                            if not router_next_def:
                                logger.warning(
                                    f"Router next step '{router_next_step}' not found in workflow"
                                )
                                continue

                            router_next_tool = router_next_def.get("tool")
                            if (
                                not isinstance(router_next_tool, str)
                                or not router_next_tool.strip()
                            ):
                                router_next_type = (
                                    "end"
                                    if router_next_step.lower() == "end"
                                    else "router"
                                )
                            else:
                                router_next_type = router_next_tool.strip().lower()
                            if router_next_type in ("router", "end", ""):
                                logger.debug(
                                    f"Router next step '{router_next_step}' is control flow, skipping"
                                )
                                continue

                            # Publish the actionable step
                            router_step_config = dict(router_next_def)
                            from noetl.server.api.run.publisher import (
                                expand_workbook_reference,
                            )

                            router_step_config = await expand_workbook_reference(
                                router_step_config, catalog_id
                            )

                            # Build context for router next step
                            router_context_data = {"workload": workload}
                            router_context_data.update(
                                {k: v for k, v in eval_ctx.items() if k != "workload"}
                            )

                            queue_id = await QueuePublisher.publish_step(
                                execution_id=str(execution_id),
                                catalog_id=catalog_id,
                                step_name=router_next_step,
                                step_config=router_step_config,
                                step_type=router_next_type,
                                parent_event_id=step_completed_event_id,
                                context=router_context_data,
                                priority=50,
                            )
                            logger.info(
                                f"Published router next step '{router_next_step}' to queue, queue_id={queue_id}"
                            )

                        continue

                    # Actionable step - publish to queue
                    try:
                        # Use the step definition directly as the config
                        step_config = dict(next_step_def)

                        # Expand workbook references - resolve the workbook action definition
                        # so the worker doesn't need to fetch from catalog
                        from noetl.server.api.run.publisher import (
                            expand_workbook_reference,
                        )

                        step_config = await expand_workbook_reference(
                            step_config, catalog_id
                        )

                        # Render step's existing args with current execution context
                        if "args" in step_config and step_config["args"]:
                            step_config["args"] = _render_with_params(step_config["args"], eval_ctx)
                        
                        # Render with_params (args from next) with current execution context
                        # This ensures templates like {{ process_data.data.temp_table }} are resolved
                        if with_params:
                            with_params = _render_with_params(with_params, eval_ctx)
                            if "args" not in step_config:
                                step_config["args"] = {}
                            step_config["args"].update(with_params)

                        # Build context for next step
                        context_data = {"workload": workload}
                        # Include all step results for template rendering
                        context_data.update(
                            {k: v for k, v in eval_ctx.items() if k != "workload"}
                        )

                        queue_id = await QueuePublisher.publish_step(
                            execution_id=str(execution_id),
                            catalog_id=catalog_id,
                            step_name=to_step,
                            step_config=step_config,
                            step_type=next_step_type,
                            parent_event_id=step_completed_event_id,
                            context=context_data,
                            priority=50,
                        )

                        logger.info(
                            f"Published next step '{to_step}' to queue, queue_id={queue_id}"
                        )
                    except Exception as e:
                        logger.exception(f"Failed to publish step '{to_step}'")

                # After processing all transitions, check if execution should be finalized
                await _check_execution_completion(execution_id, by_name)


async def _check_iterator_completions(execution_id: str) -> None:
    """
    Aggregate child execution results and continue parent workflow.

    Process:
    1. Find parent iterator execution relationships via parent_execution_id
    2. Count completed child executions vs total expected
    3. When all children complete, aggregate results and emit step_completed
    4. Process transitions to continue parent workflow

    Note: This is triggered when a child execution completes (execution_completed event)
    """
    logger.info(f"Checking iterator completions for execution {execution_id}")

    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            # Find all child executions of this execution (this execution is a child that just completed)
            # We need to check if we are a child, and if so, check parent's completion status
            await cur.execute(
                """
                SELECT parent_execution_id
                FROM noetl.event
                WHERE execution_id = %(execution_id)s
                  AND parent_execution_id IS NOT NULL
                LIMIT 1
                """,
                {"execution_id": int(execution_id)},
            )
            parent_row = await cur.fetchone()

            if not parent_row:
                # This execution has no parent, nothing to check
                logger.debug(
                    f"Execution {execution_id} has no parent, skipping iterator completion check"
                )
                return

            parent_execution_id = parent_row["parent_execution_id"]
            logger.info(
                f"Execution {execution_id} is child of {parent_execution_id}, checking parent iterator status"
            )

            # Find the iterator step in the parent that spawned these child executions
            # The iterator step would have created multiple child executions
            await cur.execute(
                """
                SELECT
                    node_name as iterator_step,
                    COUNT(DISTINCT execution_id) as total_children
                FROM noetl.event
                WHERE parent_execution_id = %(parent_execution_id)s
                  AND event_type = 'playbook_started'
                GROUP BY node_name
                """,
                {"parent_execution_id": parent_execution_id},
            )
            iterator_info = await cur.fetchone()

            if not iterator_info:
                logger.warning(
                    f"No iterator step found for parent {parent_execution_id}"
                )
                return

            iterator_step = iterator_info["iterator_step"]
            total_children = iterator_info["total_children"]

            logger.info(
                f"Iterator step '{iterator_step}' in parent {parent_execution_id} has {total_children} child executions"
            )

            # Count how many child executions have completed
            await cur.execute(
                """
                SELECT COUNT(DISTINCT e.execution_id) as completed_count
                FROM noetl.event e
                WHERE e.parent_execution_id = %(parent_execution_id)s
                  AND e.event_type = 'playbook_completed'
                """,
                {"parent_execution_id": parent_execution_id},
            )
            completion_row = await cur.fetchone()
            completed_count = completion_row["completed_count"] if completion_row else 0

            logger.info(
                f"Iterator '{iterator_step}': {completed_count}/{total_children} children completed"
            )

            # Check if all children are complete
            if completed_count < total_children:
                logger.debug(
                    f"Iterator '{iterator_step}' still has {total_children - completed_count} children running"
                )
                return

            logger.info(
                f"All children completed for iterator '{iterator_step}' in parent {parent_execution_id}, aggregating results"
            )

            # Aggregate child execution results
            await cur.execute(
                """
                SELECT
                    e.execution_id,
                    e.node_name,
                    e.context
                FROM noetl.event e
                WHERE e.parent_execution_id = %(parent_execution_id)s
                  AND e.event_type = 'playbook_completed'
                ORDER BY e.event_id
                """,
                {"parent_execution_id": parent_execution_id},
            )
            child_results = await cur.fetchall()

            # Extract results from child executions
            aggregated_results = []
            for child in child_results:
                try:
                    context = child["context"]
                    if isinstance(context, dict):
                        # Extract the result from the child execution context
                        # The result is typically in the return_step data
                        aggregated_results.append(context)
                    else:
                        aggregated_results.append(
                            {"execution_id": child["execution_id"]}
                        )
                except Exception as e:
                    logger.warning(
                        f"Failed to extract result from child {child['execution_id']}: {e}"
                    )
                    aggregated_results.append(
                        {"execution_id": child["execution_id"], "error": str(e)}
                    )

            # Emit step_completed event for the iterator step in the parent
            step_completed_event_id = await get_snowflake_id()
            now = datetime.now(timezone.utc)

            # Get parent catalog_id
            await cur.execute(
                """
                SELECT catalog_id, event_id as workflow_event_id
                FROM noetl.event
                WHERE execution_id = %(parent_execution_id)s
                  AND event_type IN ('playbook_started', 'workflow_initialized')
                ORDER BY event_id
                LIMIT 1
                """,
                {"parent_execution_id": parent_execution_id},
            )
            parent_info = await cur.fetchone()
            parent_catalog_id = parent_info["catalog_id"] if parent_info else None
            parent_event_id = parent_info["workflow_event_id"] if parent_info else None

            # Create context with aggregated data
            step_context = {
                "data": aggregated_results,
                "iterator_step": iterator_step,
                "total_children": total_children,
                "completed_at": now.isoformat(),
            }

            meta = {
                "emitted_at": now.isoformat(),
                "emitter": "orchestrator",
                "aggregation_source": "iterator_completion",
            }

            await cur.execute(
                """
                INSERT INTO noetl.event (
                    execution_id,
                    catalog_id,
                    event_id,
                    parent_event_id,
                    event_type,
                    node_id,
                    node_name,
                    node_type,
                    status,
                    context,
                    meta,
                    created_at
                ) VALUES (
                    %(execution_id)s,
                    %(catalog_id)s,
                    %(event_id)s,
                    %(parent_event_id)s,
                    %(event_type)s,
                    %(node_id)s,
                    %(node_name)s,
                    %(node_type)s,
                    %(status)s,
                    %(context)s,
                    %(meta)s,
                    %(created_at)s
                )
                """,
                {
                    "execution_id": parent_execution_id,
                    "catalog_id": parent_catalog_id,
                    "event_id": step_completed_event_id,
                    "parent_event_id": parent_event_id,
                    "event_type": "step_completed",
                    "node_id": iterator_step,
                    "node_name": iterator_step,
                    "node_type": "iterator",
                    "status": "COMPLETED",
                    "context": json.dumps(step_context),
                    "meta": json.dumps(meta),
                    "created_at": now,
                },
            )

            logger.info(
                f"Emitted step_completed for iterator '{iterator_step}' "
                f"in parent {parent_execution_id}, event_id={step_completed_event_id}"
            )

            # The step_completed event will trigger the orchestrator to process
            # transitions and continue the parent workflow
            # No need to call evaluate_execution here, the event system will handle it


__all__ = ["evaluate_execution"]
