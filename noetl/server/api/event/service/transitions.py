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


async def process_completed_steps(execution_id: str) -> None:
    """
    Process completed steps and evaluate transitions to enqueue next steps.
    
    Finds steps that have action_completed but no step_completed yet,
    then evaluates their 'next' transitions and enqueues appropriate steps.
    """
    logger.info(f"TRANSITIONS: Processing completed steps for {execution_id}")
    
    async with get_async_db_connection() as conn:
        async with conn.cursor() as cur:
            # Find completed steps without step_completed event
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
            rows = await cur.fetchall()
            completed_steps = [r[0] for r in rows]
            
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
                # Emit step_completed
                await emit_step_completed(execution_id, step_name)
                
                step_def = by_name.get(step_name)
                if not step_def:
                    logger.warning(f"TRANSITIONS: Step '{step_name}' not in playbook")
                    continue
                
                # Evaluate and enqueue transitions
                await _evaluate_transitions(
                    cur, conn, execution_id, step_name, step_def,
                    by_name, eval_ctx, catalog_id, pb_path, pb_ver
                )


async def _evaluate_transitions(
    cur, conn, execution_id: str, step_name: str, step_def: Dict[str, Any],
    by_name: Dict[str, Dict], eval_ctx: Dict[str, Any], catalog_id: int,
    pb_path: str, pb_ver: str
) -> None:
    """Evaluate step transitions and enqueue next steps."""
    
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
            if not _evaluate_condition(condition, eval_ctx):
                logger.debug(f"TRANSITIONS: Condition not met for {step_name} -> {next_step_name}")
                continue
        
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
                cur, conn, execution_id, next_step_name, next_step_def, eval_ctx
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
        
        # Emit step_started
        await emit_step_started(execution_id, next_step_name, ctx)
        
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
    
    task = {
        'name': step_name,
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
