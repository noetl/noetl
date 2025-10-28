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

from typing import Optional, Dict, Any
from jinja2 import Environment, TemplateSyntaxError, UndefinedError
from noetl.core.db.pool import get_pool_connection
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


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


async def _check_execution_completion(execution_id: str, workflow_steps: Dict[str, Dict]) -> None:
    """
    Check if all workflow steps are complete and finalize execution if needed.
    
    Args:
        execution_id: Execution ID
        workflow_steps: Dictionary of step_name -> step_definition
    """
    import json
    from datetime import datetime, timezone
    from noetl.core.db.pool import get_snowflake_id
    
    # Count actionable steps (exclude router and end steps)
    actionable_steps = [
        name for name, step_def in workflow_steps.items()
        if step_def.get("type", "").lower() not in ("router", "end", "")
    ]
    
    if not actionable_steps:
        logger.info(f"No actionable steps in workflow for execution {execution_id}")
        return
    
    async with get_pool_connection() as conn:
        async with conn.cursor() as cur:
            # Count completed steps
            await cur.execute(
                """
                SELECT COUNT(DISTINCT node_name) as count
                FROM noetl.event
                WHERE execution_id = %(execution_id)s
                  AND event_type = 'step_completed'
                """,
                {"execution_id": int(execution_id)}
            )
            result = await cur.fetchone()
            completed_count = result['count'] if result else 0
            
            logger.info(f"Execution {execution_id}: {completed_count}/{len(actionable_steps)} steps completed")
            
            # If all actionable steps are complete, emit completion events
            if completed_count >= len(actionable_steps):
                logger.info(f"All steps completed for execution {execution_id}, finalizing")
                
                # Get catalog_id and catalog path from execution_started event
                await cur.execute(
                    """
                    SELECT catalog_id, node_name as catalog_path
                    FROM noetl.event
                    WHERE execution_id = %(execution_id)s
                      AND event_type = 'execution_started'
                    LIMIT 1
                    """,
                    {"execution_id": int(execution_id)}
                )
                row = await cur.fetchone()
                if not row:
                    logger.warning(f"No execution_started event found for {execution_id}")
                    return
                
                catalog_id = row['catalog_id']
                catalog_path = row['catalog_path']
                
                # Get parent_event_id from workflow_initialized event
                await cur.execute(
                    """
                    SELECT event_id as parent_event_id
                    FROM noetl.event
                    WHERE execution_id = %(execution_id)s
                      AND event_type = 'workflow_initialized'
                    LIMIT 1
                    """,
                    {"execution_id": int(execution_id)}
                )
                row = await cur.fetchone()
                parent_event_id = row['parent_event_id'] if row else None
                
                now = datetime.now(timezone.utc)
                meta = {
                    "emitted_at": now.isoformat(),
                    "emitter": "orchestrator"
                }
                
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
                            "created_at": now
                        }
                    )
                    logger.info(f"Emitted workflow_completed event_id={workflow_event_id} for execution {execution_id}")
                    
                    # Then emit execution_completed event
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
                            "event_type": "execution_completed",
                            "node_id": "playbook",
                            "node_name": catalog_path,
                            "node_type": "execution",
                            "status": "COMPLETED",
                            "meta": json.dumps(meta),
                            "created_at": now
                        }
                    )
                    logger.info(f"Emitted execution_completed event_id={execution_event_id} for execution {execution_id}")
                    
                except Exception as e:
                    logger.exception(f"Error emitting completion events for {execution_id}")


async def evaluate_execution(
    execution_id: str,
    trigger_event_type: Optional[str] = None,
    trigger_event_id: Optional[str] = None
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
    if trigger_event_type in ('step_started', 'step_running'):
        logger.debug(f"ORCHESTRATOR: Ignoring progress marker event {trigger_event_type}")
        return
    
    try:
        # Check for failure states
        if await _has_failed(exec_id):
            logger.info(f"ORCHESTRATOR: Execution {exec_id} has failed, stopping orchestration")
            return
        
        # Reconstruct execution state from events
        state = await _get_execution_state(exec_id)
        logger.debug(f"ORCHESTRATOR: Execution {exec_id} state={state}")
        
        if state == 'initial':
            # No progress yet - dispatch first workflow step
            logger.info(f"ORCHESTRATOR: Dispatching initial step for execution {exec_id}")
            await _dispatch_first_step(exec_id)
            
        elif state == 'in_progress':
            # Steps are running - process completions and transitions
            # Process transitions for worker-reported completions
            if trigger_event_type in ('action_completed', 'step_result', 'step_end', 'step_completed'):
                logger.info(f"ORCHESTRATOR: Processing transitions for execution {exec_id}")
                await _process_transitions(exec_id)
            else:
                logger.debug(f"ORCHESTRATOR: No transition processing needed for {trigger_event_type}")
            
            # Check for iterator completions (child executions)
            if trigger_event_type in ('execution_complete', 'execution_end', 'action_completed'):
                logger.debug(f"ORCHESTRATOR: Checking iterator completions for execution {exec_id}")
                await _check_iterator_completions(exec_id)
        
        elif state == 'completed':
            logger.debug(f"ORCHESTRATOR: Execution {exec_id} already completed, no action needed")
        
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
    async with get_pool_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT 1 FROM noetl.event
                WHERE execution_id = %(execution_id)s
                  AND (
                    LOWER(status) LIKE '%%failed%%'
                    OR LOWER(status) LIKE '%%error%%'
                    OR event_type = 'error'
                  )
                LIMIT 1
                """,
                {"execution_id": execution_id}
            )
            return await cur.fetchone() is not None


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
                  AND event_type IN ('execution_complete', 'execution_end')
                LIMIT 1
                """,
                {"execution_id": execution_id}
            )
            if await cur.fetchone():
                return 'completed'
            
            # Check for any completed actions
            await cur.execute(
                """
                SELECT 1 FROM noetl.event
                WHERE execution_id = %(execution_id)s
                  AND event_type IN ('action_completed', 'step_end')
                LIMIT 1
                """,
                {"execution_id": execution_id}
            )
            if await cur.fetchone():
                return 'in_progress'
            
            # Check for active queue items
            await cur.execute(
                """
                SELECT 1 FROM noetl.queue
                WHERE execution_id = %(execution_id)s
                  AND status IN ('queued', 'leased')
                LIMIT 1
                """,
                {"execution_id": execution_id}
            )
            if await cur.fetchone():
                return 'in_progress'
            
            return 'initial'


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


async def _process_transitions(execution_id: str) -> None:
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
    
    from psycopg.rows import dict_row
    from noetl.core.db.pool import get_pool_connection
    from noetl.server.api.broker.service import EventService
    from noetl.server.api.catalog.service import CatalogService
    
    # Lazy import to avoid circular dependency
    from noetl.server.api.run.publisher import QueuePublisher
    
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            # Find completed steps without step_completed event
            await cur.execute(
                """
                SELECT DISTINCT node_name
                FROM noetl.event
                WHERE execution_id = %(execution_id)s
                  AND event_type IN ('action_completed', 'step_result')
                  AND node_name NOT IN (
                      SELECT node_name FROM noetl.event
                      WHERE execution_id = %(execution_id)s AND event_type = 'step_completed'
                  )
                """,
                {"execution_id": int(execution_id)}
            )
            rows = await cur.fetchall()
            completed_steps = [r["node_name"] for r in rows]
            
            if not completed_steps:
                logger.debug(f"No new completed steps found for execution {execution_id}")
                return
            
            logger.info(f"Found {len(completed_steps)} completed steps: {completed_steps}")
            
            # Get catalog_id
            catalog_id = await EventService.get_catalog_id_from_execution(execution_id)
            
            # Get execution metadata to find playbook path/version
            await cur.execute(
                """
                SELECT meta FROM noetl.event
                WHERE execution_id = %(execution_id)s
                  AND event_type = 'execution_started'
                ORDER BY created_at LIMIT 1
                """,
                {"execution_id": int(execution_id)}
            )
            exec_row = await cur.fetchone()
            if not exec_row or not exec_row["meta"]:
                logger.warning(f"No execution metadata found for {execution_id}")
                return
            
            metadata = exec_row["meta"]
            pb_path = metadata.get("path")
            pb_version = metadata.get("version", "latest")
            
            # Load playbook from catalog
            catalog_entry = await CatalogService.fetch_entry(catalog_id=catalog_id)
            if not catalog_entry or not catalog_entry.content:
                logger.warning(f"No playbook content found for catalog_id {catalog_id}")
                return
            
            import yaml
            playbook = yaml.safe_load(catalog_entry.content)
            workload = playbook.get("workload", {})
            
            # Build step index
            workflow_steps = playbook.get("workflow", [])
            by_name = {}
            for step_def in workflow_steps:
                step_name = step_def.get("step")
                if step_name:
                    by_name[step_name] = step_def
            
            # Query all transitions for this execution
            await cur.execute(
                """
                SELECT from_step, to_step, condition, with_params
                FROM noetl.transition
                WHERE execution_id = %(execution_id)s
                """,
                {"execution_id": int(execution_id)}
            )
            transition_rows = await cur.fetchall()
            
            # Group transitions by from_step
            transitions_by_step = {}
            for tr in transition_rows:
                from_step = tr["from_step"]
                if from_step not in transitions_by_step:
                    transitions_by_step[from_step] = []
                transitions_by_step[from_step].append(tr)
            
            # Build evaluation context with all step results
            eval_ctx = {"workload": workload}
            await cur.execute(
                """
                SELECT node_name, result
                FROM noetl.event
                WHERE execution_id = %(execution_id)s
                  AND event_type IN ('action_completed', 'step_result')
                  AND result IS NOT NULL
                ORDER BY created_at
                """,
                {"execution_id": int(execution_id)}
            )
            result_rows = await cur.fetchall()
            for res_row in result_rows:
                if res_row["node_name"] and res_row["result"]:
                    eval_ctx[res_row["node_name"]] = res_row["result"]
            
            # Process each completed step
            for step_name in completed_steps:
                logger.info(f"Processing transitions for completed step '{step_name}'")
                
                # Add current step result as 'result' for condition evaluation
                if step_name in eval_ctx:
                    eval_ctx["result"] = eval_ctx[step_name]
                
                # Get step definition to extract node_type
                step_def = by_name.get(step_name, {})
                step_type = step_def.get("type", "step")
                
                # Emit step_completed event - use EventService directly (not HTTP)
                from noetl.server.api.broker.schema import EventEmitRequest
                
                step_completed_request = EventEmitRequest(
                    execution_id=str(execution_id),
                    catalog_id=catalog_id,
                    event_type="step_completed",
                    status="COMPLETED",
                    node_id=step_name,
                    node_name=step_name,
                    node_type=step_type
                )
                
                step_completed_event_id = None
                try:
                    result = await EventService.emit_event(step_completed_request)
                    step_completed_event_id = result.event_id
                    logger.info(f"Emitted step_completed for '{step_name}', event_id={step_completed_event_id}")
                except Exception as e:
                    logger.exception(f"Error emitting step_completed for step '{step_name}'")
                
                # Get transitions for this step
                step_transitions = transitions_by_step.get(step_name, [])
                
                if not step_transitions:
                    logger.info(f"No transitions found for step '{step_name}'")
                    # Check if execution should be finalized
                    await _check_execution_completion(execution_id, by_name)
                    continue
                
                logger.info(f"Evaluating {len(step_transitions)} transitions for '{step_name}'")
                
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
                        if not _evaluate_jinja_condition(condition, eval_ctx):
                            logger.debug(f"Condition not met for {step_name} -> {to_step}")
                            continue
                        logger.info(f"Condition met for {step_name} -> {to_step}")
                    
                    # Get next step definition
                    next_step_def = by_name.get(to_step)
                    if not next_step_def:
                        logger.warning(f"Next step '{to_step}' not found in workflow")
                        continue
                    
                    # Check if step has actionable type (not router/end)
                    next_step_type = next_step_def.get("type", "").lower()
                    if next_step_type in ("router", "end", ""):
                        logger.info(f"Next step '{to_step}' is control flow type '{next_step_type}', skipping enqueue")
                        continue
                    
                    # Publish next step to queue
                    try:
                        # Use the step definition directly as the config
                        step_config = dict(next_step_def)
                        
                        # Merge with_params into step config data field
                        if with_params:
                            if "data" not in step_config:
                                step_config["data"] = {}
                            step_config["data"].update(with_params)
                        
                        # Build context for next step
                        context_data = {"workload": workload}
                        # Include all step results for template rendering
                        context_data.update({k: v for k, v in eval_ctx.items() if k != "workload"})
                        
                        queue_id = await QueuePublisher.publish_step(
                            execution_id=str(execution_id),
                            catalog_id=catalog_id,
                            step_name=to_step,
                            step_config=step_config,
                            step_type=next_step_type,
                            parent_event_id=step_completed_event_id,
                            context=context_data,
                            priority=50
                        )
                        
                        logger.info(f"Published next step '{to_step}' to queue, queue_id={queue_id}")
                    except Exception as e:
                        logger.exception(f"Failed to publish step '{to_step}'")
                
                # After processing all transitions, check if execution should be finalized
                await _check_execution_completion(execution_id, by_name)


async def _check_iterator_completions(execution_id: str) -> None:
    """
    Aggregate child execution results and continue parent workflow.
    
    Process:
    1. Find parent iterator execution relationships
    2. Count completed child executions vs total expected
    3. When all children complete, aggregate results
    4. Publish parent's next step to queue
    5. Worker executes parent continuation and reports via events
    
    TODO: Implement child execution aggregation and parent continuation
    """
    logger.info(f"Checking iterator completions for execution {execution_id}")
    # TODO: Find iterator parent-child relationships
    # TODO: Count child execution completions
    # TODO: Aggregate results when all children done
    # TODO: Publish parent next step to queue
    # Workers will execute parent continuation and report via /api/v1/event/emit
    pass


__all__ = ["evaluate_execution"]
