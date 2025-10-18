"""
Execution finalization.

Handles end steps and execution completion.
"""

from typing import Dict, Any
from noetl.core.logger import setup_logger
from .events import emit_execution_complete, emit_step_completed

logger = setup_logger(__name__, include_location=True)


def _is_actionable(step_def: Dict[str, Any]) -> bool:
    """Check if step is actionable (requires worker execution)."""
    if not step_def:
        return False
    
    step_type = str(step_def.get('type') or '').lower()
    
    if not step_type:
        return False
    
    if step_type in {'start', 'end', 'route'}:
        return False
    
    return True


async def finalize_execution(
    execution_id: str,
    step_name: str,
    step_def: Dict[str, Any],
    ctx: Dict[str, Any]
) -> None:
    """
    Finalize execution by computing final result and emitting execution_complete.
    
    Args:
        execution_id: Execution ID
        step_name: Terminal step name (usually 'end')
        step_def: Step definition
        ctx: Evaluation context with all step results
    """
    logger.info(f"FINALIZE: Finalizing execution {execution_id} at step '{step_name}'")
    
    try:
        from jinja2 import Environment, StrictUndefined, BaseLoader
        from noetl.core.dsl.render import render_template
        
        # Try to compute result from result mapping
        result_mapping = step_def.get('result')
        final_result = None
        
        if isinstance(result_mapping, dict):
            env = Environment(loader=BaseLoader(), undefined=StrictUndefined)
            try:
                final_result = render_template(
                    env, result_mapping, ctx, rules=None, strict_keys=False
                )
            except Exception as e:
                logger.warning(f"FINALIZE: Failed to render result mapping: {e}")
                final_result = result_mapping
        
        # Emit execution_complete
        await emit_execution_complete(execution_id, step_name, final_result)
        
    except Exception as e:
        logger.error(f"FINALIZE: Failed to finalize execution: {e}", exc_info=True)


async def finalize_control_step(
    cur, conn, execution_id: str, step_name: str,
    step_def: Dict[str, Any], ctx: Dict[str, Any], 
    by_name: Dict[str, Any] = None, catalog_id: str = None,
    pb_path: str = None, pb_ver: str = None
) -> None:
    """
    Handle non-actionable control step.
    
    Control steps don't execute on workers but may trigger execution completion.
    For control steps with next transitions, we need to evaluate them.
    For 'end' step, wait for all actionable steps to complete before finalizing.
    """
    logger.info(f"FINALIZE: Finalizing control step '{step_name}'")
    
    if str(step_name).strip().lower() == 'end':
        # 'end' step is an aggregator - wait for all actionable steps to complete
        if by_name:
            # Count total actionable steps in workflow
            total_actionable = sum(1 for s in by_name.values() if _is_actionable(s))
            
            # Count completed steps
            from noetl.core.common import snowflake_id_to_int
            await cur.execute(
                """
                SELECT COUNT(DISTINCT node_name)
                FROM noetl.event
                WHERE execution_id = %s AND event_type = 'step_completed'
                """,
                (snowflake_id_to_int(execution_id),)
            )
            row = await cur.fetchone()
            completed_count = row[0] if row else 0
            
            logger.info(f"FINALIZE: 'end' step - completed {completed_count}/{total_actionable} actionable steps")
            
            # Only finalize if all actionable steps are complete
            if completed_count >= total_actionable:
                logger.info(f"FINALIZE: All actionable steps complete, finalizing execution")
                await finalize_execution(execution_id, step_name, step_def, ctx)
            else:
                logger.info(f"FINALIZE: 'end' step waiting for {total_actionable - completed_count} more steps")
        else:
            # No by_name provided, finalize immediately
            await finalize_execution(execution_id, step_name, step_def, ctx)
    else:
        # Emit step_completed and capture its event_id
        step_completed_event_id = await emit_step_completed(execution_id, step_name)
        
        # If this control step has next transitions, evaluate them NOW
        # This allows control flow steps like hot_path/cold_path to fan out to multiple next steps
        if step_def.get('next') and by_name and catalog_id:
            logger.info(f"FINALIZE: Control step '{step_name}' has next transitions, evaluating immediately")
            from .transitions import _evaluate_transitions
            await _evaluate_transitions(
                cur, conn, execution_id, step_name, step_def,
                by_name, ctx, catalog_id, pb_path, pb_ver,
                parent_event_id_for_next_steps=step_completed_event_id
            )
