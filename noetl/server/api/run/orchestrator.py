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
from datetime import datetime, timezone, timedelta
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

            # Get catalog_id, catalog path, and parent_execution_id from playbook_started event
            await cur.execute(
                """
                SELECT catalog_id, node_name as catalog_path, parent_execution_id
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
            parent_execution_id = row["parent_execution_id"]

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
                        parent_execution_id,
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
                        %(parent_execution_id)s,
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
                        "parent_execution_id": int(parent_execution_id) if parent_execution_id else None,
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
        # Handle iterator_started - enqueue iteration jobs
        if trigger_event_type == "iterator_started":
            logger.info(
                f"ORCHESTRATOR: Detected iterator_started, enqueueing iterations for execution {exec_id}"
            )
            # Get the event details
            async with get_pool_connection() as conn:
                cursor = await conn.execute(
                    "SELECT data, catalog_id, node_id, node_name, event_id FROM noetl.event WHERE event_id = %s",
                    (trigger_event_id,)
                )
                event_row = await cursor.fetchone()
                if event_row:
                    event_obj = {
                        'data': event_row[0] if isinstance(event_row[0], dict) else json.loads(event_row[0] or '{}'),
                        'catalog_id': event_row[1],
                        'node_id': event_row[2],
                        'node_name': event_row[3],
                        'event_id': event_row[4]
                    }
                    await _process_iterator_started(exec_id, event_obj)
            return
        
        # Handle iteration_completed - track progress and aggregate when done
        if trigger_event_type == "iteration_completed":
            logger.info(
                f"ORCHESTRATOR: Detected iteration_completed for execution {exec_id}"
            )
            async with get_pool_connection() as conn:
                cursor = await conn.execute(
                    "SELECT data, parent_execution_id FROM noetl.event WHERE event_id = %s",
                    (trigger_event_id,)
                )
                event_row = await cursor.fetchone()
                if event_row:
                    event_obj = {
                        'data': event_row[0] if isinstance(event_row[0], dict) else json.loads(event_row[0] or '{}'),
                        'parent_execution_id': event_row[1],
                        'event_id': trigger_event_id
                    }
                    await _process_iteration_completed(exec_id, event_obj)
            return
        
        # Handle action_failed - check retry on_error and emit failure events
        if trigger_event_type == "action_failed":
            logger.info(
                f"ORCHESTRATOR: Detected action_failed for execution {exec_id}"
            )
            # First check if retry should happen
            async with get_pool_connection() as conn:
                cursor = await conn.execute(
                    "SELECT data FROM noetl.event WHERE event_id = %s",
                    (trigger_event_id,)
                )
                event_row = await cursor.fetchone()
                if event_row:
                    event_obj = {
                        'event_type': 'action_failed',
                        'data': event_row[0] if isinstance(event_row[0], dict) else json.loads(event_row[0] or '{}'),
                        'event_id': trigger_event_id
                    }
                    await _process_retry_eligible_event(exec_id, event_obj)
            
            # Then handle failure propagation
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
            # Check retry on_success for completed actions
            if trigger_event_type in (
                "action_completed",
                "step_result",
                "step_end",
                "step_completed",
            ):
                # First check if success retry should happen
                async with get_pool_connection() as conn:
                    cursor = await conn.execute(
                        "SELECT data FROM noetl.event WHERE event_id = %s",
                        (trigger_event_id,)
                    )
                    event_row = await cursor.fetchone()
                    if event_row:
                        event_obj = {
                            'event_type': trigger_event_type,
                            'data': event_row[0] if isinstance(event_row[0], dict) else json.loads(event_row[0] or '{}'),
                            'event_id': trigger_event_id
                        }
                        await _process_retry_eligible_event(exec_id, event_obj)
                
                # Then process transitions
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


async def _process_step_vars(
    execution_id: int,
    step_name: str,
    step_def: Dict[str, Any],
    eval_ctx: Dict[str, Any]
) -> None:
    """
    Process vars block from step definition after step completes.
    
    If step has a 'vars' block, render the templates and store in vars_cache.
    
    Example step definition:
        - step: fetch_data
          tool: postgres
          query: "SELECT user_id, email FROM users LIMIT 1"
          vars:
            user_id: "{{ STEP.fetch_data.data[0].user_id }}"
            email: "{{ STEP.fetch_data.data[0].email }}"
    
    Args:
        execution_id: Execution ID
        step_name: Name of the step that completed
        step_def: Step definition dict from playbook
        eval_ctx: Evaluation context with step results
    """
    vars_block = step_def.get("vars")
    if not vars_block or not isinstance(vars_block, dict):
        logger.debug(f"No vars block found for step '{step_name}'")
        return
    
    logger.info(f"Processing vars block for step '{step_name}': {list(vars_block.keys())}")
    
    try:
        # Render vars templates using Jinja2
        from noetl.core.dsl.render import render_template
        from jinja2 import BaseLoader, Environment
        
        # eval_ctx contains:
        # - 'result': current step's result (normalized, 'data' field extracted if present)
        # - step names: previous steps' results
        # Templates can use: {{ result.field }} for current step or {{ other_step.field }} for previous steps
        
        env = Environment(loader=BaseLoader())
        rendered_vars = {}
        
        for var_name, var_template in vars_block.items():
            try:
                # Render the template
                if isinstance(var_template, str):
                    template = env.from_string(var_template)
                    rendered_value = template.render(eval_ctx)
                    # Try to parse as JSON if it looks like JSON
                    if rendered_value.strip().startswith(("{", "[")):
                        try:
                            import json
                            rendered_value = json.loads(rendered_value)
                        except:
                            pass  # Keep as string
                else:
                    # Non-string values pass through
                    rendered_value = var_template
                
                rendered_vars[var_name] = rendered_value
                logger.debug(f"Rendered var '{var_name}' = {rendered_value}")
            except Exception as e:
                logger.warning(f"Failed to render var '{var_name}': {e}")
                continue
        
        if not rendered_vars:
            logger.debug(f"No vars successfully rendered for step '{step_name}'")
            return
        
        # Store vars in vars_cache using worker's VarsCache class
        from noetl.worker.vars_cache import VarsCache
        
        count = await VarsCache.set_multiple(
            variables=rendered_vars,
            execution_id=execution_id,
            var_type="step_result",
            source_step=step_name
        )
        
        logger.info(f"Stored {count} variables from step '{step_name}' vars block")
        
    except Exception as e:
        logger.exception(f"Error processing vars block for step '{step_name}': {e}")


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

                # Process vars block if present in step definition
                await _process_step_vars(execution_id, step_name, step_def, eval_ctx)

                # Get transitions for this step
                step_transitions = transitions_by_step.get(step_name, [])

                if not step_transitions:
                    logger.info(f"No transitions found for step '{step_name}'")
                    # Don't check completion here - do it once after ALL steps processed
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

                            # CRITICAL: Preserve blocks that should not be rendered server-side
                            # - sink block: contains {{ result }} templates
                            # - loop block: contains {{ item }} templates and collection config
                            sink_block = router_step_config.pop("sink", None)
                            if sink_block is not None:
                                logger.critical(f"ORCHESTRATOR-ROUTER: Extracted sink block for step '{router_next_step}'")
                            
                            loop_block = router_step_config.pop("loop", None)
                            if loop_block is not None:
                                logger.critical(f"ORCHESTRATOR-ROUTER: Extracted loop block for step '{router_next_step}'")

                            # Render router step's existing args with current execution context
                            if "args" in router_step_config and router_step_config["args"]:
                                router_step_config["args"] = _render_with_params(
                                    router_step_config["args"], eval_ctx
                                )

                            # Restore preserved blocks (worker will render them with proper context)
                            if loop_block is not None:
                                router_step_config["loop"] = loop_block
                                logger.critical(f"ORCHESTRATOR-ROUTER: Restored loop block for step '{router_next_step}'")
                            
                            if sink_block is not None:
                                router_step_config["sink"] = sink_block
                                logger.critical(f"ORCHESTRATOR-ROUTER: Restored sink block for step '{router_next_step}'")

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
                        
                        logger.critical(f"ORCHESTRATOR_DEBUG: step '{to_step}' step_config keys BEFORE processing: {list(step_config.keys())}")
                        logger.critical(f"ORCHESTRATOR_DEBUG: step '{to_step}' has 'loop': {'loop' in step_config}")
                        if 'loop' in step_config:
                            logger.critical(f"ORCHESTRATOR_DEBUG: loop value: {step_config['loop']}")

                        # Expand workbook references - resolve the workbook action definition
                        # so the worker doesn't need to fetch from catalog
                        from noetl.server.api.run.publisher import (
                            expand_workbook_reference,
                        )

                        step_config = await expand_workbook_reference(
                            step_config, catalog_id
                        )

                        # CRITICAL: Preserve blocks that should not be rendered server-side
                        # - sink block: contains {{ result }} templates
                        # - loop block: contains {{ item }} templates and collection config
                        sink_block = step_config.pop("sink", None)
                        if sink_block is not None:
                            try:
                                import json
                                sink_str = json.dumps(sink_block)
                            except Exception:
                                sink_str = str(sink_block)
                            logger.critical(f"ORCHESTRATOR: Extracted sink block for step '{to_step}': {sink_str}")
                        
                        loop_block = step_config.pop("loop", None)
                        if loop_block is not None:
                            logger.critical(f"ORCHESTRATOR: Extracted loop block for step '{to_step}'")

                        # DO NOT render step's existing args here - they need to be rendered worker-side
                        # where the full context (including previous step results) is available.
                        # The orchestrator only merges args from next blocks into step_config["args"]
                        # but leaves template rendering for the worker to handle with complete context.
                        
                        # Merge with_params (args from next) into step args WITHOUT rendering
                        # Worker will render all args together with full execution context
                        if with_params:
                            # DO NOT render with_params here either - pass templates through
                            # with_params = _render_with_params(with_params, eval_ctx)  # REMOVED
                            if "args" not in step_config:
                                step_config["args"] = {}
                            step_config["args"].update(with_params)

                        # Restore preserved blocks (worker will render them with proper context)
                        if loop_block is not None:
                            step_config["loop"] = loop_block
                            logger.critical(f"ORCHESTRATOR: Restored loop block for step '{to_step}'")
                        
                        if sink_block is not None:
                            step_config["sink"] = sink_block
                            logger.critical(f"ORCHESTRATOR: Restored sink block for step '{to_step}'")

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

                # DO NOT check completion here - it creates a race condition where
                # we mark the workflow complete before all steps have had their
                # transitions fully processed and published to the queue.
                # Completion will be checked once after ALL steps are processed.

    # After ALL completed steps have been processed, check if execution should be finalized
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


async def _process_iterator_started(
    execution_id: int,
    event: Dict[str, Any]
) -> None:
    """
    Process iterator_started event - enqueue iteration jobs.
    
    Creates N queue entries (one per iteration/batch) with:
    - parent_execution_id linking to loop
    - iteration_index and element/batch data
    
    Args:
        execution_id: Loop execution ID
        event: iterator_started event with collection metadata
    """
    from noetl.server.api.queue.service import QueueService
    
    logger.info(f"ORCHESTRATOR: Processing iterator_started for execution {execution_id}")
    
    # Extract iterator configuration from event
    event_data = event.get('data', {})
    iterator_name = event_data.get('iterator_name')
    collection = event_data.get('collection', [])
    nested_task = event_data.get('nested_task', {})
    mode = event_data.get('mode', 'sequential')
    chunk_size = event_data.get('chunk_size')
    
    if not collection:
        logger.warning(f"ORCHESTRATOR: Empty collection for iterator in execution {execution_id}")
        # Emit iterator_completed immediately
        async with get_pool_connection() as conn:
            now = datetime.now(timezone.utc)
            completed_event_id = get_snowflake_id()
            
            await conn.execute(
                """
                INSERT INTO noetl.event (
                    event_id, execution_id, catalog_id, parent_event_id,
                    event_type, node_id, node_name, node_type,
                    status, context, meta, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    completed_event_id,
                    execution_id,
                    event.get('catalog_id'),
                    event.get('event_id'),
                    'iterator_completed',
                    event.get('node_id'),
                    event.get('node_name'),
                    'iterator',
                    'COMPLETED',
                    json.dumps({}),
                    json.dumps({'total_iterations': 0, 'results': []}),
                    now
                )
            )
        return
    
    # Create batches if chunking enabled
    if chunk_size and chunk_size > 1:
        batches = []
        for i in range(0, len(collection), chunk_size):
            batches.append({
                'index': len(batches),
                'elements': collection[i:i+chunk_size]
            })
    else:
        # One job per element
        batches = [{'index': i, 'element': elem} for i, elem in enumerate(collection)]
    
    logger.info(f"ORCHESTRATOR: Enqueueing {len(batches)} iteration jobs for execution {execution_id}")
    
    # Enqueue iteration jobs
    queue_ids = []
    for batch in batches:
        # Build iteration task config
        iteration_task = dict(nested_task)
        iteration_task['_iteration_index'] = batch['index']
        iteration_task['_iterator_name'] = iterator_name
        
        # Build metadata for tracking
        iteration_meta = {
            'iterator': {
                'parent_execution_id': execution_id,
                'iteration_index': batch['index'],
                'total_iterations': len(batches),
                'iterator_name': iterator_name,
                'mode': mode
            }
        }
        
        # Enqueue job with parent_execution_id
        # Generate new execution_id for this iteration
        iter_execution_id = get_snowflake_id()
        
        response = await QueueService.enqueue_job(
            execution_id=iter_execution_id,
            catalog_id=event.get('catalog_id'),
            node_id=f"{event.get('node_id')}_iter_{batch['index']}",
            node_name=f"{event.get('node_name')}_iter_{batch['index']}",
            node_type='iteration',
            action=json.dumps(iteration_task),
            context={'_iteration_data': batch},
            parent_execution_id=execution_id,
            priority=0,
            metadata=iteration_meta
        )
        queue_ids.append(response.queue_id)
    
    logger.info(
        f"ORCHESTRATOR: Enqueued {len(queue_ids)} iteration jobs for execution {execution_id}"
    )


async def _process_iteration_completed(
    execution_id: int,
    event: Dict[str, Any]
) -> None:
    """
    Track iteration completion, check if all done.
    
    When all iterations complete, emit iterator_completed and continue workflow.
    
    Args:
        execution_id: Iteration execution ID (child)
        event: iteration_completed event
    """
    logger.info(f"ORCHESTRATOR: Processing iteration_completed for execution {execution_id}")
    
    # Get parent execution ID from event context
    parent_execution_id = event.get('parent_execution_id')
    if not parent_execution_id:
        logger.warning(f"ORCHESTRATOR: No parent_execution_id for iteration {execution_id}")
        return
    
    # Count total and completed iterations for parent
    async with get_pool_connection() as conn:
        # Check how many iteration jobs exist for this parent
        cursor = await conn.execute(
            """
            SELECT COUNT(*) as total
            FROM noetl.queue
            WHERE parent_execution_id = %s
            """,
            (parent_execution_id,)
        )
        row = await cursor.fetchone()
        total_iterations = row[0] if row else 0
        
        # Check how many have completed
        cursor = await conn.execute(
            """
            SELECT COUNT(DISTINCT execution_id) as completed
            FROM noetl.event
            WHERE parent_execution_id = %s
            AND event_type = 'iteration_completed'
            AND status = 'COMPLETED'
            """,
            (parent_execution_id,)
        )
        row = await cursor.fetchone()
        completed_iterations = row[0] if row else 0
        
        logger.info(
            f"ORCHESTRATOR: Iterator progress - {completed_iterations}/{total_iterations} iterations"
        )
        
        # If all iterations complete, emit iterator_completed
        if completed_iterations >= total_iterations and total_iterations > 0:
            logger.info(f"ORCHESTRATOR: All iterations complete for parent {parent_execution_id}")
            
            # Gather results from all iterations in order
            cursor = await conn.execute(
                """
                SELECT data, meta
                FROM noetl.event
                WHERE parent_execution_id = %s
                AND event_type = 'iteration_completed'
                ORDER BY (meta->>'iteration_index')::int
                """,
                (parent_execution_id,)
            )
            
            results = []
            async for row in cursor:
                event_data = row[0] if isinstance(row[0], dict) else json.loads(row[0] or '{}')
                results.append(event_data.get('result'))
            
            # Emit iterator_completed event
            now = datetime.now(timezone.utc)
            completed_event_id = get_snowflake_id()
            
            # Get parent event details
            cursor = await conn.execute(
                """
                SELECT catalog_id, node_id, node_name, event_id
                FROM noetl.event
                WHERE execution_id = %s
                AND event_type = 'iterator_started'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (parent_execution_id,)
            )
            parent_event = await cursor.fetchone()
            
            if parent_event:
                # Build comprehensive metadata for iterator completion
                completion_meta = {
                    'total_iterations': total_iterations,
                    'completed_iterations': completed_iterations,
                    'success_rate': completed_iterations / total_iterations if total_iterations > 0 else 0,
                    'completed_at': now.isoformat()
                }
                
                await conn.execute(
                    """
                    INSERT INTO noetl.event (
                        event_id, execution_id, catalog_id, parent_event_id,
                        event_type, node_id, node_name, node_type,
                        status, context, data, meta, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        completed_event_id,
                        parent_execution_id,
                        parent_event[0],  # catalog_id
                        parent_event[3],  # parent iterator_started event_id
                        'iterator_completed',
                        parent_event[1],  # node_id
                        parent_event[2],  # node_name
                        'iterator',
                        'COMPLETED',
                        json.dumps({}),
                        json.dumps({'results': results}),
                        json.dumps(completion_meta),
                        now
                    )
                )
                
                logger.info(
                    f"ORCHESTRATOR: Emitted iterator_completed for parent {parent_execution_id}"
                )
                
                # Trigger orchestration for parent to continue workflow
                await evaluate_execution(
                    str(parent_execution_id),
                    'iterator_completed',
                    str(completed_event_id)
                )


async def _process_retry_eligible_event(
    execution_id: int,
    event: Dict[str, Any]
) -> None:
    """
    Check if failed/completed action should be retried.
    
    For on_error: Check max_attempts, error matching, backoff
    For on_success: Evaluate while condition, apply next_call transforms
    
    If should retry, re-enqueue job with updated config.
    
    Args:
        execution_id: Current execution ID
        event: action_failed or action_completed event
    """
    from noetl.server.api.queue.service import QueueService
    from noetl.core.dsl.render import render_template
    from jinja2 import BaseLoader, Environment
    
    event_type = event.get('event_type')
    event_data = event.get('data', {})
    retry_config = event_data.get('retry_config')
    
    if not retry_config:
        return  # No retry configured
    
    attempt_number = event_data.get('attempt_number', 1)
    logger.info(
        f"ORCHESTRATOR: Checking retry for execution {execution_id}, "
        f"event_type={event_type}, attempt={attempt_number}"
    )
    
    # Determine retry type
    if event_type in ('action_failed', 'step_failed'):
        # Check on_error retry
        on_error_config = retry_config.get('on_error')
        if not on_error_config:
            return
        
        max_attempts = on_error_config.get('max_attempts', 1)
        if attempt_number >= max_attempts:
            logger.info(f"ORCHESTRATOR: Max retry attempts ({max_attempts}) reached")
            return
        
        # Calculate backoff delay
        backoff = on_error_config.get('backoff', 0)
        if isinstance(backoff, str) and backoff == 'exponential':
            delay_seconds = 2 ** (attempt_number - 1)  # 1, 2, 4, 8, ...
        elif isinstance(backoff, (int, float)):
            delay_seconds = backoff
        else:
            delay_seconds = 0
        
        # Re-enqueue with incremented attempt
        logger.info(
            f"ORCHESTRATOR: Retrying failed action (attempt {attempt_number + 1}/{max_attempts}), "
            f"backoff={delay_seconds}s"
        )
        
        # Get original task config from queue or event
        async with get_pool_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT task_config, with_params, catalog_id, step_name
                FROM noetl.queue
                WHERE execution_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (execution_id,)
            )
            queue_row = await cursor.fetchone()
            
            if queue_row:
                task_config = queue_row[0] if isinstance(queue_row[0], dict) else json.loads(queue_row[0] or '{}')
                with_params = queue_row[1] if isinstance(queue_row[1], dict) else json.loads(queue_row[1] or '{}')
                
                # Update retry metadata
                if 'retry' not in task_config:
                    task_config['retry'] = {}
                task_config['retry']['_attempt_number'] = attempt_number + 1
                task_config['retry']['_parent_event_id'] = event.get('event_id')
                
                # Build retry metadata for tracking
                retry_meta = {
                    'retry': {
                        'type': 'on_error',
                        'attempt_number': attempt_number + 1,
                        'max_attempts': max_attempts,
                        'parent_event_id': str(event.get('event_id')),
                        'backoff_seconds': delay_seconds,
                        'scheduled_at': (datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)).isoformat() if delay_seconds > 0 else None
                    }
                }
                
                # Re-enqueue
                response = await QueueService.enqueue_job(
                    execution_id=execution_id,
                    catalog_id=queue_row[2],
                    node_id=queue_row[3],
                    node_name=queue_row[3],
                    node_type='action',
                    action=json.dumps(task_config),
                    context=with_params,
                    parent_event_id=str(event.get('event_id')),
                    available_at=datetime.now(timezone.utc) + timedelta(seconds=delay_seconds) if delay_seconds > 0 else None,
                    metadata=retry_meta
                )
                
                logger.info(f"ORCHESTRATOR: Re-enqueued retry job, queue_id={response.queue_id}")
    
    elif event_type in ('action_completed', 'step_completed'):
        # Check on_success retry (pagination/polling)
        on_success_config = retry_config.get('on_success')
        if not on_success_config:
            return
        
        max_attempts = on_success_config.get('max_attempts', 100)
        if attempt_number >= max_attempts:
            logger.info(f"ORCHESTRATOR: Max success retry attempts ({max_attempts}) reached")
            return
        
        # Evaluate while condition
        while_condition = on_success_config.get('while')
        if not while_condition:
            logger.warning("ORCHESTRATOR: on_success retry without 'while' condition")
            return
        
        # Build evaluation context with response data
        response_data = event_data.get('result', {})
        eval_context = {
            'response': response_data,
            'page': response_data,
            'iteration': attempt_number,
            'attempt': attempt_number
        }
        
        # Evaluate condition
        try:
            env = Environment(loader=BaseLoader())
            template_str = while_condition.strip()
            if not (template_str.startswith("{{") and template_str.endswith("}}")):
                template_str = f"{{{{ {template_str} }}}}"
            
            template = env.from_string(template_str)
            result = template.render(**eval_context)
            should_continue = str(result).strip().lower() in ('true', '1', 'yes')
            
            logger.info(
                f"ORCHESTRATOR: Success retry condition evaluated to {should_continue} "
                f"(attempt {attempt_number})"
            )
            
            if not should_continue:
                # Store aggregated results if collect strategy specified
                await _aggregate_retry_results(execution_id, event.get('event_id'))
                return
        
        except Exception as e:
            logger.warning(f"ORCHESTRATOR: Failed to evaluate retry condition: {e}")
            return
        
        # Apply next_call transformations
        next_call = on_success_config.get('next_call', {})
        
        # Get original task config and apply updates
        async with get_pool_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT task_config, with_params, catalog_id, step_name
                FROM noetl.queue
                WHERE execution_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (execution_id,)
            )
            queue_row = await cursor.fetchone()
            
            if queue_row:
                task_config = queue_row[0] if isinstance(queue_row[0], dict) else json.loads(queue_row[0] or '{}')
                with_params = queue_row[1] if isinstance(queue_row[1], dict) else json.loads(queue_row[1] or '{}')
                
                # Apply next_call updates
                env = Environment(loader=BaseLoader())
                for key, update_spec in next_call.items():
                    if isinstance(update_spec, dict):
                        # Update nested config (e.g., params, headers)
                        if key not in task_config:
                            task_config[key] = {}
                        for sub_key, template_value in update_spec.items():
                            rendered = render_template(env, template_value, eval_context)
                            task_config[key][sub_key] = rendered
                    else:
                        # Direct update
                        rendered = render_template(env, update_spec, eval_context)
                        task_config[key] = rendered
                
                # Update retry metadata
                if 'retry' not in task_config:
                    task_config['retry'] = {}
                task_config['retry']['_attempt_number'] = attempt_number + 1
                task_config['retry']['_parent_event_id'] = event.get('event_id')
                
                # Build retry metadata for tracking (pagination/polling)
                retry_meta = {
                    'retry': {
                        'type': 'on_success',
                        'attempt_number': attempt_number + 1,
                        'max_attempts': max_attempts,
                        'parent_event_id': str(event.get('event_id')),
                        'continuation': 'pagination' if 'paging' in response_data else 'polling'
                    }
                }
                
                # Re-enqueue for next iteration
                response = await QueueService.enqueue_job(
                    execution_id=execution_id,
                    catalog_id=queue_row[2],
                    node_id=queue_row[3],
                    node_name=queue_row[3],
                    node_type='action',
                    action=json.dumps(task_config),
                    context=with_params,
                    parent_event_id=str(event.get('event_id')),
                    metadata=retry_meta
                )
                
                logger.info(
                    f"ORCHESTRATOR: Re-enqueued success retry job (attempt {attempt_number + 1}), "
                    f"queue_id={response.queue_id}"
                )


async def _aggregate_retry_results(
    execution_id: int,
    final_event_id: str
) -> None:
    """
    Aggregate results from retry sequence based on collect strategy.
    
    Strategies:
    - append: Concatenate arrays from each attempt
    - replace: Use latest result (default)
    - collect: Build array of all results
    
    Args:
        execution_id: Execution with retry sequence
        final_event_id: Last event in sequence
    """
    logger.info(f"ORCHESTRATOR: Aggregating retry results for execution {execution_id}")
    
    # For now, default behavior is to use final result
    # Future: Implement append/collect strategies by gathering all attempt results
    # and emitting a retry_sequence_completed event
    
    pass


__all__ = ["evaluate_execution"]
