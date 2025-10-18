"""
Transition evaluation and execution.

Handles step completion and routing to next steps based on 'next' transitions.
"""

from typing import Dict, Any, List, Tuple
from noetl.core.common import get_async_db_connection, snowflake_id_to_int
from noetl.core.logger import setup_logger
from .context import load_playbook_context, build_evaluation_context
from .events import emit_step_completed, emit_step_started
from .queue import enqueue_task

logger = setup_logger(__name__, include_location=True)


async def process_completed_steps(execution_id: str, trigger_event_id: str = None) -> None:
    """
    Process completed steps and evaluate transitions to enqueue next steps.
    
    Finds steps that have action_completed but no step_completed yet,
    then evaluates their 'next' transitions and enqueues appropriate steps.
    
    Args:
        execution_id: Execution ID
        trigger_event_id: Event ID of the triggering event (action_completed or step_result)
                         Used as parent_event_id for step_completed events
    """
    logger.info(f"TRANSITIONS: Processing completed steps for {execution_id}")
    logger.info(f"TRANSITIONS: ===== NEW CODE VERSION WITH DETAILED LOGGING =====")
    
    async with get_async_db_connection() as conn:
        async with conn.cursor() as cur:
            logger.info(f"TRANSITIONS: About to execute query for execution {execution_id}")
            # Find completed steps without step_completed event
            try:
                await cur.execute(
                    """
                    SELECT DISTINCT node_name
                    FROM noetl.event
                    WHERE execution_id = %s
                      AND event_type IN ('action_completed', 'step_result')
                      AND node_name NOT IN (
                          SELECT node_name FROM noetl.event
                          WHERE execution_id = %s AND event_type = 'step_completed'
                      )
                    """,
                    (execution_id, execution_id)
                )
                logger.info(f"TRANSITIONS: Query execution completed, about to fetch")
            except Exception as query_error:
                logger.error(f"TRANSITIONS: QUERY EXECUTION FAILED: {query_error}", exc_info=True)
                return
                
            logger.info(f"TRANSITIONS: Query executed, fetching results")
            try:
                rows = await cur.fetchall()
                logger.info(f"TRANSITIONS: Fetched {len(rows)} rows")
            except Exception as fetch_error:
                logger.error(f"TRANSITIONS: FETCHALL FAILED: {fetch_error}", exc_info=True)
                return
            
            completed_steps = [r[0] for r in rows]
            
            logger.info(f"TRANSITIONS: Query returned {len(rows)} rows: {rows}")
            
            if not completed_steps:
                logger.debug(f"TRANSITIONS: No new completed steps found")
                return
            
            logger.info(f"TRANSITIONS: Found {len(completed_steps)} completed steps: {completed_steps}")
            
            # Load playbook
            playbook, pb_path, pb_ver, workload = await load_playbook_context(cur, execution_id)
            
            if not playbook:
                logger.warning(f"TRANSITIONS: No playbook found")
                return
            
            # Build step index
            steps = playbook.get('workflow') or playbook.get('steps') or []
            by_name = {}
            for s in steps:
                name = s.get('step') or s.get('name')
                if name:
                    by_name[name] = s
            
            # Build evaluation context
            eval_ctx = await build_evaluation_context(execution_id)
            
            # Get catalog_id
            await cur.execute(
                "SELECT catalog_id FROM noetl.event WHERE execution_id = %s ORDER BY created_at LIMIT 1",
                (snowflake_id_to_int(execution_id),)
            )
            row = await cur.fetchone()
            catalog_id = row[0] if row else None
            
            if not catalog_id:
                logger.error(f"TRANSITIONS: No catalog_id found")
                return
            
            # Process each completed step
            for step_name in completed_steps:
                logger.info(f"TRANSITIONS: Processing completed step '{step_name}'")
                
                step_def = by_name.get(step_name)
                if not step_def:
                    logger.warning(f"TRANSITIONS: Step '{step_name}' not in playbook")
                    continue
                
                logger.info(f"TRANSITIONS: Found step_def for '{step_name}', evaluating transitions")
                
                # Add current step's result as 'result' for condition evaluation
                if step_name in eval_ctx:
                    eval_ctx['result'] = eval_ctx[step_name]
                    logger.info(f"TRANSITIONS: Added 'result' to context: {eval_ctx['result']}")
                
                # Emit step_completed FIRST and capture its event_id
                # Use trigger_event_id as parent if available (for action_completed or step_result)
                step_completed_event_id = await emit_step_completed(
                    execution_id, step_name, parent_event_id=trigger_event_id
                )
                logger.info(f"TRANSITIONS: Emitted step_completed for '{step_name}', event_id={step_completed_event_id}")
                
                # Evaluate and enqueue transitions AFTER emitting step_completed
                # Pass step_completed_event_id as parent for next steps' step_started events
                try:
                    await _evaluate_transitions(
                        cur, conn, execution_id, step_name, step_def,
                        by_name, eval_ctx, catalog_id, pb_path, pb_ver,
                        parent_event_id_for_next_steps=step_completed_event_id
                    )
                    logger.info(f"TRANSITIONS: Successfully evaluated transitions for '{step_name}'")
                except Exception as e:
                    logger.error(f"TRANSITIONS: Failed to evaluate transitions for '{step_name}': {e}", exc_info=True)
                    continue



async def _evaluate_transitions(
    cur, conn, execution_id: str, step_name: str, step_def: Dict[str, Any],
    by_name: Dict[str, Dict], eval_ctx: Dict[str, Any], catalog_id: int,
    pb_path: str, pb_ver: str, parent_event_id_for_next_steps: str = None
) -> None:
    """
    Evaluate step transitions and enqueue next steps.
    
    Args:
        parent_event_id_for_next_steps: Parent event_id to use for step_started events of next steps.
                                        If provided, all next steps will use this as their parent.
                                        Typically the step_completed event_id of the current step.
    """
    
    next_transitions = step_def.get('next', [])
    
    if not next_transitions:
        logger.info(f"TRANSITIONS: No next transitions for '{step_name}'")
        
        # Check if this is the end step
        if str(step_name).strip().lower() == 'end':
            from .finalize import finalize_execution
            await finalize_execution(execution_id, step_name, step_def, eval_ctx)
        
        return
    
    # Ensure list
    if not isinstance(next_transitions, list):
        next_transitions = [next_transitions]
    
    logger.info(f"TRANSITIONS: Evaluating {len(next_transitions)} transitions for '{step_name}'")
    
    # Evaluate each transition
    for transition in next_transitions:
        next_step_name, condition, transition_data = _parse_transition(transition)
        
        if not next_step_name:
            continue
        
        # Evaluate condition if present
        if condition:
            logger.info(f"TRANSITIONS: Evaluating condition '{condition}' for {step_name} -> {next_step_name}")
            logger.info(f"TRANSITIONS: Context keys: {list(eval_ctx.keys())}")
            logger.info(f"TRANSITIONS: Step result for '{step_name}': {eval_ctx.get(step_name)}")
            if not _evaluate_condition(condition, eval_ctx):
                logger.debug(f"TRANSITIONS: Condition not met for {step_name} -> {next_step_name}")
                continue
            logger.info(f"TRANSITIONS: Condition MET for {step_name} -> {next_step_name}")
        
        # Get next step definition
        next_step_def = by_name.get(next_step_name)
        if not next_step_def:
            logger.warning(f"TRANSITIONS: Next step '{next_step_name}' not found")
            continue
        
        # Check if actionable
        if not _is_actionable(next_step_def):
            logger.info(f"TRANSITIONS: Next step '{next_step_name}' is control flow")
            from .finalize import finalize_control_step
            await finalize_control_step(
                cur, conn, execution_id, next_step_name, next_step_def, eval_ctx,
                by_name, catalog_id, pb_path, pb_ver
            )
            continue
        
        # Build context
        ctx = {
            'workload': eval_ctx.get('workload', {}),
            'step_name': next_step_name,
            'path': pb_path,
            'version': pb_ver,
            'catalog_id': catalog_id,
        }
        if transition_data:
            ctx.update(transition_data)
        
        # Emit step_started with explicit parent_event_id (if provided)
        step_started_event_id = await emit_step_started(
            execution_id, next_step_name, ctx, parent_event_id=parent_event_id_for_next_steps
        )
        
        # Pass step_started event_id as parent for action_started via noetl_meta
        # Worker extracts parent_event_id from context['noetl_meta']['parent_event_id']
        if step_started_event_id:
            if 'noetl_meta' not in ctx:
                ctx['noetl_meta'] = {}
            ctx['noetl_meta']['parent_event_id'] = step_started_event_id
        
        # Build and enqueue task
        task = _build_task(next_step_def, next_step_name, transition_data)
        await enqueue_task(cur, conn, execution_id, next_step_name, task, ctx, catalog_id)
        
        logger.info(f"TRANSITIONS: Enqueued {step_name} -> {next_step_name}")


def _parse_transition(
    transition: Any
) -> Tuple[str, str, Dict[str, Any]]:
    """
    Parse transition definition.
    
    Returns: (step_name, condition, data)
    """
    if isinstance(transition, str):
        return transition, None, {}
    
    elif isinstance(transition, dict):
        step_name = transition.get('step') or transition.get('name')
        condition = transition.get('when')
        
        # Extract transition data
        data = {}
        for key in ['with', 'payload', 'input']:
            val = transition.get(key)
            if isinstance(val, dict):
                data.update(val)
        
        if 'data' in transition and isinstance(transition['data'], dict):
            data['data'] = transition['data']
        
        return step_name, condition, data
    
    return None, None, {}


def _evaluate_condition(condition: str, ctx: Dict[str, Any]) -> bool:
    """Evaluate Jinja2 condition."""
    try:
        from jinja2 import Environment, StrictUndefined, BaseLoader
        from noetl.core.dsl.render import render_template
        
        env = Environment(loader=BaseLoader(), undefined=StrictUndefined)
        
        # Wrap if not already
        if not condition.strip().startswith('{{'):
            condition = f"{{{{ {condition} }}}}"
        
        result = render_template(env, condition, ctx, rules=None, strict_keys=False)
        
        # Convert to boolean
        if isinstance(result, bool):
            return result
        if isinstance(result, str):
            return result.lower() in ('true', '1', 'yes')
        return bool(result)
    except Exception as e:
        logger.warning(f"TRANSITIONS: Failed to evaluate condition '{condition}': {e}")
        return False


def _build_task(
    step_def: Dict[str, Any],
    step_name: str,
    transition_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Build task from step definition."""
    
    # For workbook steps, use the workbook action name; otherwise use step name
    action_name = step_name
    if step_def.get('type') == 'workbook' and step_def.get('name'):
        action_name = step_def.get('name')
    
    task = {
        'name': action_name,
        'type': step_def.get('type') or 'python',
    }
    
    # Copy step fields
    for field in (
        'task', 'run', 'code', 'command', 'commands', 'sql',
        'url', 'endpoint', 'method', 'headers', 'params',
        'collection', 'element', 'mode', 'concurrency', 'enumerate',
        'where', 'limit', 'chunk', 'order_by',
        'input', 'payload', 'with', 'auth', 'data',
        'resource_path', 'content', 'path', 'iterator', 'save',
        'credential', 'credentials', 'retry'
    ):
        if step_def.get(field) is not None:
            task[field] = step_def.get(field)
    
    # Merge transition data
    if transition_data:
        if 'data' in transition_data:
            base_data = task.get('data', {})
            if isinstance(base_data, dict) and isinstance(transition_data['data'], dict):
                base_data.update(transition_data['data'])
                task['data'] = base_data
        
        existing_with = task.get('with', {})
        if isinstance(existing_with, dict):
            merged_with = {**existing_with, **{k: v for k, v in transition_data.items() if k != 'data'}}
            task['with'] = merged_with
    
    # Normalize
    try:
        from noetl.core.dsl.normalize import normalize_step
        task = normalize_step(task)
    except Exception:
        pass
    
    return task


def _is_actionable(step_def: Dict[str, Any]) -> bool:
    """Check if step is actionable."""
    
    if not step_def:
        return False
    
    step_type = str(step_def.get('type') or '').lower()
    
    if not step_type:
        return False
    
    if step_type in {'start', 'end', 'route'}:
        return False
    
    if step_def.get('save'):
        return True
    
    if step_type in {
        'http', 'python', 'duckdb', 'postgres', 'snowflake',
        'secrets', 'workbook', 'playbook', 'save', 'iterator'
    }:
        if step_type == 'python':
            code = step_def.get('code') or step_def.get('code_b64') or step_def.get('code_base64')
            return bool(code)
        return True
    
    return False
