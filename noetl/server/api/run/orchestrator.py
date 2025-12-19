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
from psycopg.types.json import Json

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
            # Acquire advisory lock to ensure only ONE completion check runs at a time for this execution
            # This prevents race conditions between multiple command.completed triggers
            await cur.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%(lock_key)s))",
                {"lock_key": f"completion_check_{execution_id}"}
            )
            logger.debug(f"Acquired advisory lock for completion check of execution {execution_id}")
            
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
            
            # Check for parent iterators that have completed iterations but no iterator_completed yet
            # This prevents premature completion when iterations finish but iterator aggregation pending
            await cur.execute(
                """
                SELECT COUNT(*) as pending_parents
                FROM noetl.event e1
                WHERE e1.execution_id = %(execution_id)s
                  AND e1.event_type = 'iterator_started'
                  AND NOT EXISTS (
                      SELECT 1 FROM noetl.event e2
                      WHERE e2.execution_id = e1.execution_id
                        AND e2.event_type = 'iterator_completed'
                  )
                """,
                {"execution_id": int(execution_id)},
            )
            row = await cur.fetchone()
            pending_parents = row["pending_parents"] if row else 0
            
            logger.info(f"DEBUG_PENDING_PARENTS: query returned {pending_parents} for execution {execution_id}")

            logger.info(
                f"Execution {execution_id}: running_actions={running_count}, pending_jobs={pending_count}, incomplete_steps={incomplete_steps}, pending_parents={pending_parents}"
            )

            # If there are any running actions, pending jobs, incomplete steps, or pending parent aggregations, execution is not complete
            if running_count > 0 or pending_count > 0 or incomplete_steps > 0 or pending_parents > 0:
                logger.debug(
                    f"Execution {execution_id} not complete: {running_count} running, {pending_count} pending, {pending_parents} parents awaiting aggregation"
                )
                return

            # Check if 'end' step has a command that's still running
            # This prevents completing the workflow between step.exit and command.completed
            await cur.execute(
                """
                SELECT COUNT(*) as end_command_running
                FROM noetl.event
                WHERE execution_id = %(execution_id)s
                  AND node_name = 'end'
                  AND event_type IN ('command.claimed', 'command.started', 'call.done')
                  AND NOT EXISTS (
                      SELECT 1 FROM noetl.event e2
                      WHERE e2.execution_id = %(execution_id)s
                        AND e2.node_name = 'end'
                        AND e2.event_type = 'command.completed'
                  )
                """,
                {"execution_id": int(execution_id)},
            )
            row = await cur.fetchone()
            end_command_running = row["end_command_running"] if row else 0
            
            if end_command_running > 0:
                logger.debug(
                    f"Execution {execution_id}: 'end' step command still running, waiting for command.completed"
                )
                return

            # No pending work - check if 'end' step has completed
            logger.info(f"All active work completed for execution {execution_id}, checking for 'end' step")

            # Check if 'end' step evaluation has completed (step.exit)
            await cur.execute(
                """
                SELECT COUNT(*) as end_exit
                FROM noetl.event
                WHERE execution_id = %(execution_id)s
                  AND node_name = 'end'
                  AND event_type = 'step.exit'
                  AND status = 'COMPLETED'
                """,
                {"execution_id": int(execution_id)},
            )
            row = await cur.fetchone()
            end_exit = row["end_exit"] if row else 0

            if end_exit == 0:
                logger.debug(
                    f"Execution {execution_id}: 'end' step not yet evaluated, waiting"
                )
                return

            # If we reach here, end step has completed its evaluation (step.exit exists)
            # and if it had a command, command.completed also exists (checked earlier)
            logger.info(
                f"Execution {execution_id}: 'end' step fully completed, evaluating final status"
            )

            # Get catalog info
            await cur.execute(
                """
                SELECT catalog_id, node_name as catalog_path, parent_execution_id, payload
                FROM noetl.event e
                JOIN noetl.catalog c ON e.catalog_id = c.catalog_id
                WHERE e.execution_id = %(execution_id)s
                  AND e.event_type = 'playbook_started'
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

            # Evaluate all step results to determine final status
            await cur.execute(
                """
                SELECT node_name, status, error
                FROM noetl.event
                WHERE execution_id = %(execution_id)s
                  AND event_type IN ('step.exit', 'step_failed')
                  AND node_name != 'end'
                ORDER BY event_id
                """,
                {"execution_id": int(execution_id)},
            )
            step_results = await cur.fetchall()

            # Check if any steps failed
            failed_steps = [s for s in step_results if s["status"] == "FAILED"]
            has_failures = len(failed_steps) > 0

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
            meta = {
                "emitted_at": now.isoformat(),
                "emitter": "orchestrator",
                "evaluated_by_end_step": True,
                "total_steps": len(step_results),
                "failed_steps_count": len(failed_steps)
            }

            try:
                if has_failures:
                    # Emit workflow_failed
                    logger.info(
                        f"Execution {execution_id}: {len(failed_steps)} step(s) failed, emitting workflow_failed"
                    )
                    
                    workflow_event_id = await get_snowflake_id()
                    failed_step_names = [s["node_name"] for s in failed_steps]
                    error_messages = [s.get("error", "Unknown error") for s in failed_steps]
                    
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
                            "execution_id": int(execution_id),
                            "catalog_id": catalog_id,
                            "event_id": workflow_event_id,
                            "parent_event_id": parent_event_id,
                            "event_type": "workflow_failed",
                            "node_id": "workflow",
                            "node_name": "workflow",
                            "node_type": "workflow",
                            "status": "FAILED",
                            "error": f"Workflow failed at steps: {', '.join(failed_step_names)}",
                            "meta": json.dumps(meta),
                            "created_at": now,
                        },
                    )
                    
                    # Emit playbook_failed
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
                            error,
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
                            %(error)s,
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
                            "event_type": "playbook_failed",
                            "node_id": "playbook",
                            "node_name": catalog_path,
                            "node_type": "execution",
                            "status": "FAILED",
                            "error": f"Playbook failed: {', '.join(failed_step_names[:3])}",
                            "meta": json.dumps(meta),
                            "created_at": now,
                        },
                    )
                    logger.info(
                        f"Emitted playbook_failed event_id={execution_event_id} for execution {execution_id}"
                    )
                else:
                    # Emit workflow_completed
                    logger.info(
                        f"Execution {execution_id}: All steps succeeded, emitting workflow_completed"
                    )
                    
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
                    
                    # Emit playbook_completed
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
        f">>> EVALUATE_EXECUTION CALLED: exec_id={exec_id}, "
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
        # Worker emits this event after analyzing collection
        if trigger_event_type == "iterator_started":
            logger.info(
                f"ORCHESTRATOR: Detected iterator_started, enqueueing iterations for execution {exec_id}"
            )
            # Get the event details - iterator metadata is in context column
            async with get_pool_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT context, catalog_id, node_id, node_name, event_id FROM noetl.event WHERE event_id = %s",
                        (trigger_event_id,)
                    )
                    event_row = await cur.fetchone()
                    if event_row:
                        context_data = event_row['context'] if 'context' in event_row.keys() else event_row[0]
                        event_obj = {
                            'context': context_data if isinstance(context_data, dict) else json.loads(context_data or '{}'),
                            'catalog_id': event_row['catalog_id'] if 'catalog_id' in event_row.keys() else event_row[1],
                            'node_id': event_row['node_id'] if 'node_id' in event_row.keys() else event_row[2],
                            'node_name': event_row['node_name'] if 'node_name' in event_row.keys() else event_row[3],
                            'event_id': event_row['event_id'] if 'event_id' in event_row.keys() else event_row[4]
                        }
                        await _process_iterator_started(exec_id, event_obj)
            return
        
        # Handle iteration_completed - track progress and aggregate when done
        if trigger_event_type == "iteration_completed":
            logger.info(
                f"ORCHESTRATOR: Detected iteration_completed for execution {exec_id}"
            )
            async with get_pool_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT result, parent_execution_id FROM noetl.event WHERE event_id = %s",
                        (trigger_event_id,)
                    )
                    event_row = await cur.fetchone()
                if event_row:
                    result_col = event_row['result'] if 'result' in event_row.keys() else event_row[0]
                    event_obj = {
                        'data': result_col if isinstance(result_col, dict) else json.loads(result_col or '{}'),
                        'parent_execution_id': event_row['parent_execution_id'] if 'parent_execution_id' in event_row.keys() else event_row[1],
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
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT result FROM noetl.event WHERE event_id = %s",
                        (trigger_event_id,)
                    )
                    event_row = await cur.fetchone()
                if event_row:
                    result_data = event_row['result'] if 'result' in event_row.keys() else event_row[0]
                    event_obj = {
                        'event_type': 'action_failed',
                        'data': result_data if isinstance(result_data, dict) else json.loads(result_data or '{}'),
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
        logger.info(f">>> EVALUATE_EXECUTION STATE: {state} for exec_id={exec_id}")

        if state == "initial":
            # No progress yet - dispatch first workflow step
            logger.info(
                f"ORCHESTRATOR: Dispatching initial step for execution {exec_id}"
            )
            await _dispatch_first_step(exec_id)

        elif state == "in_progress":
            logger.info(f">>> EVALUATE_EXECUTION: STATE IS IN_PROGRESS, will process transitions")
            # Steps are running - process completions and transitions
            # Check retry on_success for completed actions
            if trigger_event_type in (
                "action_completed",
                "step_result",
                "step_end",
                "step_completed",
                "iterator_completed",  # Allow loop completion to trigger workflow continuation
            ):
                # First check if success retry should happen
                async with get_pool_connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            "SELECT result FROM noetl.event WHERE event_id = %s",
                            (trigger_event_id,)
                        )
                        event_row = await cur.fetchone()
                    if event_row:
                        result_data = event_row['result'] if hasattr(event_row, '__getitem__') else event_row[0]
                        event_obj = {
                            'event_type': trigger_event_type,
                            'data': result_data if isinstance(result_data, dict) else json.loads(result_data or '{}'),
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
    Handle action failure by routing to 'end' step for aggregation.
    
    New failure handling flow:
    1. Emit step_failed - Mark the step as failed
    2. Route execution to 'end' step - Let end step aggregate and evaluate
    3. Do NOT emit workflow_failed/playbook_failed yet - wait for end evaluation
    
    Args:
        execution_id: Execution ID
        action_failed_event_id: Event ID of the action_failed event
    """
    logger.info(f"ORCHESTRATOR: Handling action failure for execution {execution_id}, routing to 'end' step")
    
    # Get the failed action details and catalog info
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            # Get action_failed event details
            await cur.execute(
                """
                SELECT e.node_name, e.node_type, e.error, e.stack_trace, e.result, e.catalog_id,
                       c.path as catalog_path, c.payload
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
    playbook_payload = failed_action.get("payload", {})
    
    logger.info(
        f"ORCHESTRATOR: Step '{step_name}' failed in execution {execution_id}, emitting step_failed"
    )
    
    # Emit step_failed event only (not workflow_failed/playbook_failed)
    async with get_pool_connection() as conn:
        async with conn.cursor() as cur:
            try:
                now = datetime.now(timezone.utc)
                meta = {
                    "failed_at": now.isoformat(),
                    "routed_to_end": True,  # Mark that this failure routes to end
                    "failure_reason": error_message
                }
                
                # Emit step_failed event
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
                
                await conn.commit()
                
            except Exception:
                await conn.rollback()
                logger.exception(
                    f"Error emitting step_failed event for {execution_id}"
                )
                return
    
    # Route to 'end' step for aggregation
    logger.info(f"ORCHESTRATOR: Routing execution {execution_id} to 'end' step after failure")
    
    # Check if 'end' step exists in workflow (it should, due to implicit injection)
    workflow = playbook_payload.get("workflow", [])
    end_step = next((s for s in workflow if s.get("step", "").lower() == "end"), None)
    
    if not end_step:
        logger.error(
            f"ORCHESTRATOR: No 'end' step found in workflow for {execution_id}, "
            f"falling back to immediate failure"
        )
        # Fallback: emit workflow_failed and playbook_failed
        await _emit_immediate_failure(execution_id, catalog_id, catalog_path, step_name, error_message, step_failed_event_id)
        return
    
    # Enqueue 'end' step for execution
    try:
        from noetl.server.api.run.publisher import QueuePublisher
        from noetl.server.api.context.service import ContextService
        
        # Load execution context for end step
        context = await ContextService.load_execution_context(str(execution_id), str(catalog_id))
        
        # Emit step_started for end step
        from noetl.server.api.broker.schema import EventEmitRequest
        end_step_started_request = EventEmitRequest(
            execution_id=str(execution_id),
            catalog_id=catalog_id,
            event_type="step_started",
            status="STARTED",
            node_id="end",
            node_name="end",
            node_type="step",
            parent_event_id=step_failed_event_id,
        )
        from noetl.server.api.broker.service import EventService
        end_started_result = await EventService.emit_event(end_step_started_request)
        
        # Special handling for "end" step - only enqueue once all other steps are complete
        async with await get_db_connection() as conn:
            async with conn.cursor() as cur:
                # Acquire advisory lock to prevent duplicate "end" enqueues
                await cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%(lock_key)s))",
                    {"lock_key": f"end_publish_{execution_id}"}
                )
                logger.info(f"Acquired advisory lock for 'end' step publishing in execution {execution_id}")
                
                logger.info(f"Checking if 'end' step should be enqueued for execution {execution_id}")
                
                # Check if there are any non-end steps still running or pending
                await cur.execute(
                    """
                    SELECT COUNT(*) as active_count
                    FROM noetl.queue
                    WHERE execution_id = %(execution_id)s
                      AND node_name != 'end'
                      AND status IN ('pending', 'running')
                    """,
                    {"execution_id": int(execution_id)}
                )
                active_row = await cur.fetchone()
                active_count = active_row["active_count"] if active_row else 0
                
                if active_count > 0:
                    logger.info(
                        f"'end' step enqueue deferred: {active_count} other steps still active. "
                        f"Will retry when those complete."
                    )
                    return  # Skip enqueuing end for now
                
                # Check if end step is already in queue (prevent duplicate enqueues)
                await cur.execute(
                    """
                    SELECT COUNT(*) as end_queued
                    FROM noetl.queue
                    WHERE execution_id = %(execution_id)s
                      AND node_name = 'end'
                      AND status IN ('pending', 'running', 'completed')
                    """,
                    {"execution_id": int(execution_id)}
                )
                end_queued_row = await cur.fetchone()
                end_queued = end_queued_row["end_queued"] if end_queued_row else 0
                
                if end_queued > 0:
                    logger.info(f"'end' step already enqueued/running/completed, skipping duplicate")
                    return
                
                logger.info(f"All other steps complete, enqueuing 'end' step for execution {execution_id}")
        
        # Publish end step to queue
        await QueuePublisher.publish_step(
            step_name="end",
            step_config=end_step,
            execution_id=str(execution_id),
            catalog_id=catalog_id,
            context=context,
            parent_event_id=end_started_result.event_id
        )
        
        logger.info(
            f"ORCHESTRATOR: Successfully routed execution {execution_id} to 'end' step"
        )
        
    except Exception as e:
        logger.exception(
            f"ORCHESTRATOR: Failed to route to 'end' step for {execution_id}: {e}"
        )
        # Fallback: emit workflow_failed and playbook_failed
        await _emit_immediate_failure(execution_id, catalog_id, catalog_path, step_name, error_message, step_failed_event_id)


async def _emit_immediate_failure(
    execution_id: int,
    catalog_id: int,
    catalog_path: str,
    step_name: str,
    error_message: str,
    step_failed_event_id: int
) -> None:
    """
    Fallback: Emit workflow_failed and playbook_failed immediately.
    Used when routing to 'end' step is not possible.
    """
    logger.warning(
        f"ORCHESTRATOR: Emitting immediate failure for execution {execution_id} (fallback)"
    )
    
    async with get_pool_connection() as conn:
        async with conn.cursor() as cur:
            try:
                now = datetime.now(timezone.utc)
                meta = {"failed_at": now.isoformat(), "fallback": True}
                
                # Emit workflow_failed event
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
                
                # Emit playbook_failed event
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

    Note: V2 DSL implementation handles workflow initialization differently.
    The V2 system automatically dispatches the 'start' step via the execute API
    and uses NATS messaging for worker coordination. This function is kept for
    backward compatibility but is not used in V2 playbook execution.
    
    For V2 playbooks:
    1. Execute API creates workflow_initialized event
    2. Orchestrator evaluates next steps from workflow definition
    3. QueuePublisher publishes steps to queue
    4. Workers receive commands via NATS and execute
    5. Workers report back via v2/events endpoint
    """
    logger.info(f"Dispatching first step for execution {execution_id} (V1 compatibility mode)")
    # V2 DSL handles this through evaluate_execution flow
    pass


async def _process_step_vars(
    execution_id: int,
    step_name: str,
    step_def: Dict[str, Any],
    eval_ctx: Dict[str, Any]
) -> None:
    """
    Process vars block from step definition after step completes.
    
    If step has a 'vars' block, render the templates and store in transient.
    
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
    logger.info(f"[VARS_DEBUG] _process_step_vars called for step '{step_name}', step_def keys: {list(step_def.keys())}, vars_block: {vars_block}")
    if not vars_block or not isinstance(vars_block, dict):
        logger.info(f"[VARS_DEBUG] No vars block or not dict for step '{step_name}' - returning early")
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
        
        # Store vars in transient using worker's TransientVars class
        from noetl.worker.transient import TransientVars
        
        count = await TransientVars.set_multiple(
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
    logger.info(f">>> PROCESS_TRANSITIONS called for execution {execution_id}")

    # Find completed steps without step_completed event using async executor
    completed_steps = (
        await OrchestratorQueries.get_completed_steps_without_step_completed(
            execution_id
        )
    )

    logger.info(f">>> PROCESS_TRANSITIONS completed_steps={completed_steps}")

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
            # Check for parent steps with completed iterations (fix for loop completion bug)
            # When a step has loop attribute, server expands into _iter_N jobs
            # After all iterations complete, we need to emit action_completed for parent step
            logger.debug(f"Checking for parent steps with completed iterations, completed_steps={completed_steps}")
            parent_steps_to_process = []  # Track parents we emit action_completed for
            iteration_steps = [s for s in completed_steps if '_iter_' in s]
            logger.debug(f"Found {len(iteration_steps)} iteration steps: {iteration_steps}")
            if iteration_steps:
                # Group by parent step name (remove _iter_N suffix)
                parent_steps = {}
                for iter_step in iteration_steps:
                    # Extract parent name: "fetch_all_endpoints_iter_0" -> "fetch_all_endpoints"
                    parent_name = iter_step.rsplit('_iter_', 1)[0]
                    if parent_name not in parent_steps:
                        parent_steps[parent_name] = []
                    parent_steps[parent_name].append(iter_step)
                
                # For each parent, check if all iterations are complete
                for parent_name, iterations in parent_steps.items():
                    # Check if parent step exists in workflow and has loop attribute
                    parent_def = by_name.get(parent_name)
                    if not parent_def or not parent_def.get("loop"):
                        continue
                    
                    # Get expected iteration count from iterator_started event
                    logger.debug(f"Looking for iterator_started: execution_id={execution_id}, node_id={parent_name}")
                    await cur.execute(
                        """
                        SELECT context FROM noetl.event
                        WHERE execution_id = %s
                          AND node_id = %s
                          AND event_type = 'iterator_started'
                        ORDER BY created_at DESC
                        LIMIT 1
                        """,
                        (execution_id, parent_name)
                    )
                    iterator_row = await cur.fetchone()
                    logger.debug(f"iterator_started query result for '{parent_name}': {iterator_row is not None}")
                    expected_count = None
                    if iterator_row and iterator_row['context']:
                        context_data = iterator_row['context']
                        if isinstance(context_data, dict):
                            expected_count = context_data.get('total_count')
                    
                    logger.info(f"Parent '{parent_name}': expected_count={expected_count}, actual={len(iterations)}")
                    
                    if expected_count is None:
                        logger.warning(
                            f"Could not determine expected iteration count for '{parent_name}', skipping"
                        )
                        continue
                    
                    # Check how many iterations have actually completed
                    actual_completed = len(iterations)
                    
                    if actual_completed < expected_count:
                        logger.info(
                            f"Parent step '{parent_name}' expects {expected_count} iterations, "
                            f"only {actual_completed} completed so far, SKIPPING parent completion"
                        )
                        continue
                    
                    # CRITICAL: Also check for step_result events to ensure all results are available
                    # Parent aggregation needs to wait for ALL step_result events, not just action_completed
                    await cur.execute(
                        """
                        SELECT COUNT(*) as step_result_count
                        FROM noetl.event
                        WHERE execution_id = %s
                          AND node_name LIKE %s
                          AND event_type = 'step_result'
                        """,
                        (execution_id, f"{parent_name}_iter_%")
                    )
                    step_result_row = await cur.fetchone()
                    step_result_count = step_result_row['step_result_count'] if step_result_row else 0
                    
                    if step_result_count < expected_count:
                        logger.info(
                            f"Parent step '{parent_name}' expects {expected_count} step_result events, "
                            f"only {step_result_count} available so far, SKIPPING parent completion"
                        )
                        continue
                    
                    # Check if there are any pending iteration jobs
                    await cur.execute(
                        """
                        SELECT COUNT(*) as pending_count
                        FROM noetl.queue
                        WHERE execution_id = %s
                          AND node_name LIKE %s
                          AND status IN ('pending', 'running')
                        """,
                        (execution_id, f"{parent_name}_iter_%")
                    )
                    pending_row = await cur.fetchone()
                    pending_count = pending_row['pending_count'] if pending_row else 0
                    
                    if pending_count > 0:
                        logger.debug(
                            f"Parent step '{parent_name}' has {pending_count} pending iterations, skipping"
                        )
                        continue
                    
                    # Check if parent already has action_completed
                    await cur.execute(
                        """
                        SELECT COUNT(*) as count
                        FROM noetl.event
                        WHERE execution_id = %s
                          AND node_name = %s
                          AND event_type = 'action_completed'
                        """,
                        (execution_id, parent_name)
                    )
                    existing_row = await cur.fetchone()
                    if existing_row and existing_row['count'] > 0:
                        logger.debug(f"Parent step '{parent_name}' already has action_completed")
                        continue
                    
                    logger.info(
                        f"All {expected_count} iterations complete for parent '{parent_name}', "
                        f"emitting action_completed"
                    )
                    
                    # Aggregate results from all iterations
                    await cur.execute(
                        """
                        SELECT result
                        FROM noetl.event
                        WHERE execution_id = %s
                          AND node_name LIKE %s
                          AND event_type = 'step_result'
                        ORDER BY node_name
                        """,
                        (execution_id, f"{parent_name}_iter_%")
                    )
                    
                    aggregated_results = []
                    async for row in cur:
                        if row['result']:
                            result_data = row['result'] if isinstance(row['result'], dict) else json.loads(row['result'] or '{}')
                            # Extract the actual result value - step_result wraps in {"value": ...}
                            if isinstance(result_data, dict) and 'value' in result_data:
                                result_value = result_data['value']
                            else:
                                result_value = result_data
                            aggregated_results.append(result_value)
                    
                    # Get parent_event_id from iterator_started event
                    await cur.execute(
                        """
                        SELECT event_id
                        FROM noetl.event
                        WHERE execution_id = %s
                          AND node_id = %s
                          AND event_type = 'iterator_started'
                        ORDER BY created_at DESC
                        LIMIT 1
                        """,
                        (execution_id, parent_name)
                    )
                    iterator_event_row = await cur.fetchone()
                    parent_event_id = iterator_event_row['event_id'] if iterator_event_row else None
                    
                    # Emit action_completed for parent step
                    from noetl.server.api.broker.schema import EventEmitRequest
                    
                    parent_tool = parent_def.get("tool", "iterator")
                    # Result is array of results from all iterations
                    # Users can access as: {{ step_name }} (array of iteration results)
                    # Or {{ step_name | length }} for count, etc.
                    action_completed_request = EventEmitRequest(
                        execution_id=str(execution_id),
                        catalog_id=catalog_id,
                        event_type="action_completed",
                        status="COMPLETED",
                        node_id=parent_name,
                        node_name=parent_name,
                        node_type="iterator",
                        parent_event_id=parent_event_id,
                        result=aggregated_results  # Direct array (schema now supports Union[Dict, List])
                    )
                    
                    try:
                        result = await EventService.emit_event(action_completed_request)
                        logger.info(
                            f"Emitted action_completed for parent step '{parent_name}', "
                            f"event_id={result.event_id}, aggregated {len(aggregated_results)} iteration results"
                        )
                        
                        # CRITICAL: Trigger orchestration for the parent action_completed event
                        # This ensures the workflow can progress after parent aggregation
                        logger.info(f"Triggering orchestration for parent step '{parent_name}' completion")
                        await evaluate_execution(
                            execution_id=str(execution_id),
                            trigger_event_type="action_completed",
                            trigger_event_id=result.event_id
                        )
                        
                        # Add aggregated result to eval_ctx so it's available for condition evaluation
                        # Users access as: {{ step_name }} (array of iteration results)
                        # Or {{ step_name | length }} for count, etc.
                        eval_ctx[parent_name] = aggregated_results
                        logger.debug(
                            f"Added {len(aggregated_results)} aggregated results to eval_ctx for parent step '{parent_name}'"
                        )
                        
                        # Emit step_result event for consistency with other steps
                        step_result_request = EventEmitRequest(
                            execution_id=str(execution_id),
                            catalog_id=catalog_id,
                            event_type="step_result",
                            status="COMPLETED",
                            node_id=parent_name,
                            node_name=parent_name,
                            node_type="iterator",
                            parent_event_id=result.event_id,
                            result={"value": aggregated_results}
                        )
                        step_result_response = await EventService.emit_event(step_result_request)
                        logger.info(
                            f"Emitted step_result for parent step '{parent_name}', event_id={step_result_response.event_id}"
                        )
                        
                        # Add parent to list for processing
                        parent_steps_to_process.append(parent_name)
                        
                        # Trigger new orchestration cycle for parent step processing
                        # Must be done AFTER this function completes to avoid recursion
                        logger.info(
                            f"Scheduling re-evaluation for parent step '{parent_name}' completion"
                        )
                    except Exception as e:
                        logger.exception(
                            f"Error emitting events for parent step '{parent_name}'"
                        )
            
            # Process parent steps immediately after emitting their events
            # Add them to completed_steps list so they get processed in the loop below
            if parent_steps_to_process:
                logger.info(
                    f"Adding {len(parent_steps_to_process)} parent steps to processing queue: "
                    f"{parent_steps_to_process}"
                )
                # Add parents to completed_steps - they now have action_completed events
                completed_steps.extend(parent_steps_to_process)
                logger.info(f"Extended completed_steps to {len(completed_steps)} items")
            
            # Process each completed step
            for step_name in completed_steps:
                # Skip iteration steps (they were already handled in parent step emission above)
                if '_iter_' in step_name:
                    logger.debug(f"Skipping iteration step '{step_name}' - handled via parent step")
                    continue
                
                logger.info(f"Processing transitions for completed step '{step_name}'")

                # Get step definition first
                step_def = by_name.get(step_name, {})
                
                # Check if this step has a loop attribute - if so, check for pending iterations
                if step_def.get("loop"):
                    logger.info(f"Step '{step_name}' has loop attribute, checking for pending iterations")
                    # Check if there are pending iteration jobs
                    await cur.execute(
                        """
                        SELECT COUNT(*) as pending_count
                        FROM noetl.queue
                        WHERE parent_execution_id = %s
                          AND node_name = %s
                          AND status IN ('pending', 'running')
                        """,
                        (execution_id, step_name)
                    )
                    pending_row = await cur.fetchone()
                    pending_count = pending_row['pending_count'] if pending_row else 0
                    
                    if pending_count > 0:
                        logger.info(
                            f"Step '{step_name}' has {pending_count} pending iteration jobs, "
                            f"skipping transition processing until iterations complete"
                        )
                        continue  # Skip this step for now
                    else:
                        logger.info(f"All iterations complete for step '{step_name}', proceeding with transitions")

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
                logger.info(f"[VARS_DEBUG] About to process vars for step '{step_name}', step_def keys: {list(step_def.keys())}, has 'vars': {'vars' in step_def}")
                if 'vars' in step_def:
                    logger.info(f"[VARS_DEBUG] step_def['vars'] = {step_def['vars']}")
                await _process_step_vars(execution_id, step_name, step_def, eval_ctx)

                # Get transitions for this step
                step_transitions = transitions_by_step.get(step_name, [])

                if not step_transitions:
                    # No explicit transitions - check if this is 'end' step
                    if step_name.lower() == 'end':
                        logger.info(f"Step '{step_name}' is 'end' step with no transitions - workflow terminating normally")
                        continue
                    
                    # Not 'end' step and no transitions - implicitly route to 'end' for universal convergence
                    logger.info(f"No transitions found for step '{step_name}' - implicitly routing to 'end'")
                    
                    # Check if workflow has 'end' step
                    end_step_def = by_name.get('end')
                    if not end_step_def:
                        logger.warning(f"No 'end' step found in workflow - cannot route '{step_name}'")
                        continue
                    
                    # Create implicit transition to 'end'
                    step_transitions = [{
                        "to_step": "end",
                        "condition": None,
                        "with_params": {}
                    }]
                    logger.info(f"Created implicit transition: {step_name} → end")

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

                    # Check if step has a tool definition (dict or string)
                    has_tool = next_step_def.get("tool") is not None
                    
                    # If it's an "end" step WITHOUT a tool, emit step_completed and skip enqueue
                    # If it HAS a tool, treat it like any other actionable step
                    if next_step_type == "end" and not has_tool:
                        logger.info(
                            f"Next step '{to_step}' is end step, emitting step_completed and skipping enqueue"
                        )
                        
                        # Emit step_completed for the end step so workflow knows it terminated
                        from noetl.server.api.broker.schema import EventEmitRequest
                        
                        end_step_request = EventEmitRequest(
                            execution_id=str(execution_id),
                            catalog_id=catalog_id,
                            event_type="step_completed",
                            status="COMPLETED",
                            node_id=to_step,
                            node_name=to_step,
                            node_type="end",
                            parent_event_id=step_completed_event_id,
                        )
                        try:
                            await EventService.emit_event(end_step_request)
                            logger.info(
                                f"Emitted step_completed for end step '{to_step}'"
                            )
                        except Exception as e:
                            logger.exception(
                                f"Error emitting step_completed for end step '{to_step}': {e}"
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
                            
                            # Check if step has tool definition
                            router_has_tool = router_next_def.get("tool") is not None
                            
                            # Skip only control flow steps: routers and end steps WITHOUT tools
                            if router_next_type == "router" or (router_next_type == "end" and not router_has_tool):
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

                            # Special handling for "end" step - only enqueue once all other steps are complete
                            if router_next_step.lower() == "end":
                                # Acquire advisory lock to prevent duplicate "end" enqueues
                                await cur.execute(
                                    "SELECT pg_advisory_xact_lock(hashtext(%(lock_key)s))",
                                    {"lock_key": f"end_publish_{execution_id}"}
                                )
                                logger.info(f"Acquired advisory lock for 'end' step publishing in execution {execution_id}")
                                
                                logger.info(f"Checking if 'end' step should be enqueued for execution {execution_id}")
                                
                                # Check if there are any non-end steps still running or pending
                                await cur.execute(
                                    """
                                    SELECT COUNT(*) as active_count
                                    FROM noetl.queue
                                    WHERE execution_id = %(execution_id)s
                                      AND node_name != 'end'
                                      AND status IN ('pending', 'running')
                                    """,
                                    {"execution_id": int(execution_id)}
                                )
                                active_row = await cur.fetchone()
                                active_count = active_row["active_count"] if active_row else 0
                                
                                if active_count > 0:
                                    logger.info(
                                        f"'end' step enqueue deferred: {active_count} other steps still active. "
                                        f"Will retry when those complete."
                                    )
                                    continue  # Skip enqueuing end for now
                                
                                # Check if end step is already in queue (prevent duplicate enqueues)
                                await cur.execute(
                                    """
                                    SELECT COUNT(*) as end_queued
                                    FROM noetl.queue
                                    WHERE execution_id = %(execution_id)s
                                      AND node_name = 'end'
                                      AND status IN ('pending', 'running', 'completed')
                                    """,
                                    {"execution_id": int(execution_id)}
                                )
                                end_queued_row = await cur.fetchone()
                                end_queued = end_queued_row["end_queued"] if end_queued_row else 0
                                
                                if end_queued > 0:
                                    logger.info(f"'end' step already enqueued/running/completed, skipping duplicate")
                                    continue
                                
                                logger.info(f"All other steps complete, enqueuing 'end' step for execution {execution_id}")

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

                        # Check if this is a loop step - handle via iterator pattern instead of queue
                        if loop_block is not None:
                            logger.info(f"ORCHESTRATOR: Step '{to_step}' has loop attribute, initiating server-side iteration")
                            
                            # CRITICAL: Restore sink to step_config BEFORE passing to nested_task
                            # Sink needs to execute per iteration in the worker
                            if sink_block is not None:
                                step_config["sink"] = sink_block
                                logger.critical(f"ORCHESTRATOR: Restored sink to nested_task for iterator step '{to_step}'")
                            
                            # Emit iterator_started event (server-side only, not from worker)
                            from noetl.server.api.broker.schema import EventEmitRequest
                            
                            # Render collection template if it's a string (Jinja2 template)
                            collection_raw = loop_block.get("collection", [])
                            if isinstance(collection_raw, str):
                                from noetl.core.dsl.render import render_template
                                from jinja2 import BaseLoader, Environment
                                
                                # Build full render context with step results
                                render_ctx = {"workload": eval_ctx.get("workload", {})}
                                
                                # Add all step results to render context
                                result_rows = await OrchestratorQueries.get_step_results(int(execution_id))
                                for res_row in result_rows:
                                    if res_row["node_name"] and res_row["result"]:
                                        result_value = res_row["result"]
                                        if isinstance(result_value, dict) and "data" in result_value:
                                            result_value = result_value["data"]
                                        render_ctx[res_row["node_name"]] = result_value
                                
                                logger.critical(f"ORCHESTRATOR: Rendering collection template '{collection_raw}' with context keys: {list(render_ctx.keys())}")
                                env = Environment(loader=BaseLoader())
                                collection = render_template(env, collection_raw, render_ctx)
                                logger.critical(f"ORCHESTRATOR: Rendered collection type={type(collection).__name__}, length={len(collection) if isinstance(collection, (list, str)) else 'N/A'}")
                            else:
                                collection = collection_raw
                            
                            # Build iterator context with collection metadata
                            iterator_context = {
                                "collection": collection,
                                "iterator_name": loop_block.get("element", "item"),
                                "mode": loop_block.get("mode", "sequential"),
                                "nested_task": step_config,  # The actual task config to execute per iteration
                                "total_count": len(collection) if isinstance(collection, list) else 0
                            }
                            
                            iterator_started_request = EventEmitRequest(
                                execution_id=str(execution_id),
                                catalog_id=catalog_id,
                                event_type="iterator_started",
                                status="RUNNING",
                                node_id=to_step,
                                node_name="iterator",
                                node_type="iterator",
                                parent_event_id=step_completed_event_id,
                                context=iterator_context
                            )
                            
                            try:
                                result = await EventService.emit_event(iterator_started_request)
                                iterator_event_id = result.event_id
                                logger.info(f"Emitted iterator_started for '{to_step}', event_id={iterator_event_id}")
                                
                                # Process iterator_started to enqueue iteration jobs
                                event_obj = {
                                    'context': iterator_context,
                                    'catalog_id': catalog_id,
                                    'node_id': to_step,
                                    'node_name': to_step,
                                    'event_id': iterator_event_id
                                }
                                await _process_iterator_started(execution_id, event_obj)
                                
                            except Exception as e:
                                logger.exception(f"Error emitting iterator_started for step '{to_step}'")
                            
                            continue  # Skip queue publishing for loop steps
                        
                        # Restore preserved blocks (worker will render them with proper context)
                        if sink_block is not None:
                            step_config["sink"] = sink_block
                            logger.critical(f"ORCHESTRATOR: Restored sink block for step '{to_step}'")

                        # Build context for next step
                        context_data = {"workload": workload}
                        # Include all step results for template rendering
                        context_data.update(
                            {k: v for k, v in eval_ctx.items() if k != "workload"}
                        )

                        # Special handling for "end" step - only enqueue once all other steps are complete
                        if to_step.lower() == "end":
                            # Acquire advisory lock to prevent duplicate "end" enqueues
                            await cur.execute(
                                "SELECT pg_advisory_xact_lock(hashtext(%(lock_key)s))",
                                {"lock_key": f"end_publish_{execution_id}"}
                            )
                            logger.info(f"Acquired advisory lock for 'end' step publishing in execution {execution_id}")
                            
                            logger.info(f"Checking if 'end' step should be enqueued for execution {execution_id}")
                            
                            # Check if there are any non-end steps still running or pending
                            await cur.execute(
                                """
                                SELECT COUNT(*) as active_count
                                FROM noetl.queue
                                WHERE execution_id = %(execution_id)s
                                  AND node_name != 'end'
                                  AND status IN ('pending', 'running')
                                """,
                                {"execution_id": int(execution_id)}
                            )
                            active_row = await cur.fetchone()
                            active_count = active_row["active_count"] if active_row else 0
                            
                            if active_count > 0:
                                logger.info(
                                    f"'end' step enqueue deferred: {active_count} other steps still active. "
                                    f"Will retry when those complete."
                                )
                                continue  # Skip enqueuing end for now
                            
                            # Check if end step is already in queue (prevent duplicate enqueues)
                            await cur.execute(
                                """
                                SELECT COUNT(*) as end_queued
                                FROM noetl.queue
                                WHERE execution_id = %(execution_id)s
                                  AND node_name = 'end'
                                  AND status IN ('pending', 'running', 'completed')
                                """,
                                {"execution_id": int(execution_id)}
                            )
                            end_queued_row = await cur.fetchone()
                            end_queued = end_queued_row["end_queued"] if end_queued_row else 0
                            
                            if end_queued > 0:
                                logger.info(f"'end' step already enqueued/running/completed, skipping duplicate")
                                continue
                            
                            logger.info(f"All other steps complete, enqueuing 'end' step for execution {execution_id}")

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
    
    # Extract iterator configuration from event context
    event_context = event.get('context', {})
    iterator_name = event_context.get('iterator_name')
    collection = event_context.get('collection', [])
    nested_task = event_context.get('nested_task', {})
    mode = event_context.get('mode', 'sequential')
    chunk_size = event_context.get('chunk_size')
    
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
    
    # Get workload from parent execution for iteration context
    parent_workload = {}
    try:
        async with get_pool_connection() as conn:
            result = await conn.execute(
                "SELECT data FROM noetl.workload WHERE execution_id = %s",
                (execution_id,)
            )
            workload_row = await result.fetchone()
            logger.critical(f"ORCHESTRATOR: Raw workload_row type: {type(workload_row)}, value: {workload_row}")
            
            if workload_row:
                # fetchone returns a dict-like Row object with 'data' key
                if isinstance(workload_row, dict) and 'data' in workload_row:
                    workload_data = workload_row['data']
                else:
                    # Fallback: try index access for tuple-like results
                    workload_data = workload_row[0] if len(workload_row) > 0 else {}
                    
                logger.critical(f"ORCHESTRATOR: Extracted workload_data type: {type(workload_data)}, keys: {list(workload_data.keys()) if isinstance(workload_data, dict) else 'not a dict'}")
                
                # CRITICAL: Extract nested 'workload' key if present
                if isinstance(workload_data, dict) and 'workload' in workload_data and isinstance(workload_data['workload'], dict):
                    parent_workload = workload_data['workload']
                    logger.critical(f"ORCHESTRATOR: Extracted nested workload with keys: {list(parent_workload.keys())}")
                elif isinstance(workload_data, dict):
                    parent_workload = workload_data
                    logger.critical(f"ORCHESTRATOR: Using workload_data directly with keys: {list(parent_workload.keys())}")
                else:
                    logger.warning(f"ORCHESTRATOR: workload_data is not a dict: {type(workload_data)}")
            else:
                logger.warning(f"ORCHESTRATOR: No workload found for execution {execution_id}")
                
            logger.critical(f"ORCHESTRATOR: Final parent_workload keys: {list(parent_workload.keys()) if isinstance(parent_workload, dict) else type(parent_workload)}")
    except Exception as e:
        logger.error(f"ORCHESTRATOR: Failed to fetch workload for execution {execution_id}: {e}", exc_info=True)
        parent_workload = {}
    
    # Enqueue iteration jobs
    queue_ids = []
    for batch in batches:
        # Build context with element data accessible via iterator variable name
        # For example, if iterator_name='endpoint', templates can use {{ endpoint.name }}
        # CRITICAL: Include workload so sink templates can access {{ workload.* }}
        iteration_context = {
            iterator_name: batch.get('element'),  # Single element for non-chunked
            '_iteration_index': batch['index'],
            '_iterator_name': iterator_name,
            '_total_iterations': len(batches),
            'workload': parent_workload  # Include workload for sink templates
        }
        
        # Build iteration task config - inject element into nested_task
        iteration_task = dict(nested_task)
        
        # CRITICAL: Render ALL templates in iteration_task with iteration_context
        # This ensures params like {{ city.lat }} are resolved before sending to worker
        from noetl.core.dsl.render import render_template
        from jinja2 import BaseLoader, Environment
        
        try:
            env = Environment(loader=BaseLoader())
            iteration_task = render_template(env, iteration_task, iteration_context)
            logger.info(
                f"ORCHESTRATOR: Rendered iteration task for batch {batch['index']}, "
                f"element={batch.get('element')}"
            )
        except Exception as e:
            logger.error(
                f"ORCHESTRATOR: Failed to render iteration task templates: {e}",
                exc_info=True
            )
        
        # If chunked, provide elements array
        if 'elements' in batch:
            iteration_context[f'{iterator_name}s'] = batch['elements']
            iteration_context['_chunk_size'] = len(batch['elements'])
        
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
        
        # Enqueue job - all iterations share the parent execution_id
        # Database will auto-generate queue_id for each iteration
        response = await QueueService.enqueue_job(
            execution_id=execution_id,  # All iterations share parent execution_id
            catalog_id=event.get('catalog_id'),
            node_id=f"{event.get('node_id')}_iter_{batch['index']}",
            node_name=f"{event.get('node_name')}_iter_{batch['index']}",
            node_type='iteration',
            action=json.dumps(iteration_task),
            context=iteration_context,  # Element data injected here
            parent_execution_id=execution_id,
            priority=0,
            metadata=iteration_meta
        )
        queue_ids.append(response.id)
    
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
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT COUNT(*) as total
                FROM noetl.queue
                WHERE parent_execution_id = %s
                """,
                (parent_execution_id,)
            )
            row = await cur.fetchone()
            total_iterations = row['total'] if row else 0
            
            # Check how many have completed
            await cur.execute(
                """
                SELECT COUNT(*) as completed
                FROM noetl.event
                WHERE parent_execution_id = %s
                AND event_type = 'iteration_completed'
                AND status = 'COMPLETED'
                """,
                (parent_execution_id,)
            )
            row = await cur.fetchone()
            completed_iterations = row['completed'] if row else 0
        
        logger.info(
            f"ORCHESTRATOR: Iterator progress - {completed_iterations}/{total_iterations} iterations"
        )
        
        # If all iterations complete, emit iterator_completed
        if completed_iterations >= total_iterations and total_iterations > 0:
            logger.info(f"ORCHESTRATOR: All iterations complete for parent {parent_execution_id}")
            
            async with conn.cursor() as cur:
                # Gather results from all iterations in order
                await cur.execute(
                    """
                    SELECT result, meta
                    FROM noetl.event
                    WHERE parent_execution_id = %s
                    AND event_type = 'iteration_completed'
                    ORDER BY (meta->>'iteration_index')::int
                    """,
                    (parent_execution_id,)
                )
                
                results = []
                async for row in cur:
                    result_col = row['result']
                    result_data = result_col if isinstance(result_col, dict) else json.loads(result_col or '{}')
                    results.append(result_data)
                
            # Emit iterator_completed event
            async with conn.cursor() as cur:
                now = datetime.now(timezone.utc)
                completed_event_id = await get_snowflake_id()
                
                # Get parent event details
                await cur.execute(
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
                parent_event = await cur.fetchone()
            
                if parent_event:
                    # Build comprehensive metadata for iterator completion
                    completion_meta = {
                        'total_iterations': total_iterations,
                        'completed_iterations': completed_iterations,
                        'success_rate': completed_iterations / total_iterations if total_iterations > 0 else 0,
                        'completed_at': now.isoformat()
                    }
                    
                    # Insert iterator_completed event
                    await cur.execute(
                        """
                        INSERT INTO noetl.event (
                            event_id, execution_id, catalog_id, parent_event_id,
                            event_type, node_id, node_name, node_type,
                            status, context, result, meta, created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            completed_event_id,
                            parent_execution_id,
                            parent_event['catalog_id'],
                            parent_event['event_id'],  # parent iterator_started event_id
                            'iterator_completed',
                            parent_event['node_id'],
                            parent_event['node_name'],
                            'iterator',
                            'COMPLETED',
                            Json({}),
                            Json({'results': results}),
                            Json(completion_meta),
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
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT task_config, with_params, catalog_id, step_name
                    FROM noetl.queue
                    WHERE execution_id = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (execution_id,)
                )
                queue_row = await cur.fetchone()
            
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
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT task_config, with_params, catalog_id, step_name
                    FROM noetl.queue
                    WHERE execution_id = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (execution_id,)
                )
                queue_row = await cur.fetchone()
            
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
