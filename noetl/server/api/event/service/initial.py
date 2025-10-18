"""
Initial dispatch - handles first step execution.

Responsible for starting a new playbook execution.
"""

import json
import yaml
from typing import Dict, Any, Tuple, Optional
from noetl.core.common import get_async_db_connection, snowflake_id_to_int
from noetl.core.logger import setup_logger
from .context import load_playbook_context, build_evaluation_context
from .queue import enqueue_task
from .events import emit_step_started

logger = setup_logger(__name__, include_location=True)


async def dispatch_first_step(execution_id: str) -> None:
    """
    Dispatch the first actionable step of a playbook.
    
    Steps:
    1. Load playbook and context
    2. Find 'start' step
    3. Determine first actionable step
    4. Emit step_started
    5. Enqueue task
    """
    logger.info(f"INITIAL: ===== DISPATCH START for {execution_id} =====")
    
    async with get_async_db_connection() as conn:
        async with conn.cursor() as cur:
            # Load playbook and context
            logger.info(f"INITIAL: Loading playbook context")
            playbook, pb_path, pb_ver, workload = await load_playbook_context(
                cur, execution_id
            )
            
            if not playbook:
                logger.error(f"INITIAL: EARLY EXIT - No playbook found for {execution_id}")
                return
            logger.info(f"INITIAL: Playbook loaded: path={pb_path}, version={pb_ver}")
            
            # Get workflow steps
            steps = playbook.get('workflow') or playbook.get('steps') or []
            if not steps:
                logger.error(f"INITIAL: EARLY EXIT - No steps found in playbook")
                return
            logger.info(f"INITIAL: Found {len(steps)} steps in workflow")
            
            # Build step index by name
            by_name = {}
            for s in steps:
                name = s.get('step') or s.get('name')
                if name:
                    by_name[name] = s
            logger.info(f"INITIAL: Built step index with {len(by_name)} named steps: {list(by_name.keys())}")
            
            # Populate workflow tables for tracking
            try:
                from .workflow import populate_workflow_tables
                await populate_workflow_tables(cur, execution_id, pb_path, playbook)
                logger.info(f"INITIAL: Workflow tables populated")
            except Exception as e:
                logger.warning(f"INITIAL: Failed to populate workflow tables: {e}")
            
            # Find start step
            start_step = by_name.get('start')
            if not start_step:
                logger.error(f"INITIAL: EARLY EXIT - No 'start' step found in playbook. Available steps: {list(by_name.keys())}")
                return
            logger.info(f"INITIAL: Found start step: {start_step}")
            
            # Determine first actionable step
            logger.info(f"INITIAL: Finding first actionable step from start")
            first_step_name, transition_data = _find_first_actionable(
                start_step, by_name
            )
            
            if not first_step_name:
                logger.error(f"INITIAL: EARLY EXIT - No actionable step found from start")
                return
            logger.info(f"INITIAL: First actionable step: '{first_step_name}'")
            
            step_def = by_name.get(first_step_name)
            if not step_def:
                logger.error(f"INITIAL: EARLY EXIT - Step '{first_step_name}' not found in by_name index")
                return
            logger.info(f"INITIAL: Step definition found for '{first_step_name}': type={step_def.get('type')}")
            
            # Check if actionable
            is_actionable = _is_actionable(step_def)
            logger.info(f"INITIAL: Checking if step '{first_step_name}' is actionable: {is_actionable}")
            if not is_actionable:
                logger.info(f"INITIAL: EARLY EXIT - Step '{first_step_name}' is control flow only, finalizing")
                await _finalize_control_step(
                    cur, conn, execution_id, first_step_name, step_def, {}
                )
                return
            logger.info(f"INITIAL: Step '{first_step_name}' is actionable, continuing")
            
            # Get catalog_id and requestor_info from execution_start event
            await cur.execute(
                "SELECT catalog_id, meta FROM noetl.event WHERE execution_id = %s AND event_type = 'execution_start' ORDER BY created_at LIMIT 1",
                (snowflake_id_to_int(execution_id),)
            )
            row = await cur.fetchone()
            catalog_id = row[0] if row else None
            meta = row[1] if row and len(row) > 1 else None
            
            if not catalog_id:
                raise ValueError(f"No catalog_id found for execution {execution_id}")
            
            # Extract requestor_info from meta
            requestor_info = None
            if meta and isinstance(meta, dict):
                requestor_info = meta.get('requestor')
            
            # Build context
            ctx = {
                'workload': (workload.get('workload') if isinstance(workload, dict) else None) or {},
                'step_name': first_step_name,
                'path': pb_path,
                'version': pb_ver or 'latest',
                'catalog_id': catalog_id,
            }
            if transition_data:
                ctx.update(transition_data)
            
            # Add requestor info to context metadata
            if requestor_info:
                if 'noetl_meta' not in ctx:
                    ctx['noetl_meta'] = {}
                ctx['noetl_meta']['requestor'] = requestor_info
            
            # Emit step_started
            logger.info(f"INITIAL: About to emit step_started for '{first_step_name}'")
            await emit_step_started(execution_id, first_step_name, ctx)
            logger.info(f"INITIAL: Emitted step_started for '{first_step_name}'")
            
            # Build and enqueue task
            logger.info(f"INITIAL: Building task for '{first_step_name}'")
            task = _build_task(step_def, first_step_name, transition_data)
            logger.info(f"INITIAL: Built task: {json.dumps(task, indent=2)}")
            
            logger.info(f"INITIAL: About to call enqueue_task for '{first_step_name}'")
            try:
                await enqueue_task(
                    cur, conn, execution_id, first_step_name, task, ctx, catalog_id
                )
                logger.info(f"INITIAL: Successfully called enqueue_task for '{first_step_name}'")
            except Exception as e:
                logger.error(f"INITIAL: enqueue_task FAILED for '{first_step_name}': {e}", exc_info=True)
                raise
            
            logger.info(f"INITIAL: Enqueued first step '{first_step_name}'")


def _find_first_actionable(
    start_step: Dict[str, Any],
    by_name: Dict[str, Dict]
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Find first actionable step from start step."""
    
    # If start itself is actionable, use it
    if _is_actionable(start_step):
        return 'start', {}
    
    # Otherwise check start's next transitions
    next_list = start_step.get('next') or []
    if not isinstance(next_list, list):
        next_list = [next_list] if next_list else []
    
    if not next_list:
        return None, {}
    
    # Take first transition (conditions evaluated later if needed)
    first = next_list[0]
    
    if isinstance(first, str):
        return first, {}
    elif isinstance(first, dict):
        step_name = first.get('step') or first.get('name')
        transition_data = _extract_transition_data(first)
        return step_name, transition_data
    
    return None, {}


def _extract_transition_data(transition: Dict[str, Any]) -> Dict[str, Any]:
    """Extract data to pass from transition."""
    merged = {}
    
    for key in ['with', 'payload', 'input']:
        val = transition.get(key)
        if isinstance(val, dict):
            merged.update(val)
    
    if 'data' in transition and isinstance(transition['data'], dict):
        merged['data'] = transition['data']
    
    return merged


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
    
    # Normalize aliases
    try:
        from noetl.core.dsl.normalize import normalize_step
        task = normalize_step(task)
    except Exception:
        pass
    
    return task


def _is_actionable(step_def: Dict[str, Any]) -> bool:
    """Check if step should be executed by worker."""
    
    if not step_def:
        return False
    
    step_type = str(step_def.get('type') or '').lower()
    
    if not step_type:
        return False
    
    # Control flow types
    if step_type in {'start', 'end', 'route'}:
        return False
    
    # Save blocks make step actionable
    if step_def.get('save'):
        return True
    
    # Action types
    if step_type in {
        'http', 'python', 'duckdb', 'postgres', 'snowflake',
        'secrets', 'workbook', 'playbook', 'save', 'iterator'
    }:
        if step_type == 'python':
            code = step_def.get('code') or step_def.get('code_b64') or step_def.get('code_base64')
            return bool(code)
        return True
    
    return False


async def _finalize_control_step(
    cur, conn, execution_id: str, step_name: str,
    step_def: Dict[str, Any], ctx: Dict[str, Any]
) -> None:
    """Handle non-actionable control step."""
    logger.info(f"INITIAL: Finalizing control step '{step_name}'")
    
    if str(step_name).strip().lower() == 'end':
        from .finalize import finalize_execution
        await finalize_execution(execution_id, step_name, step_def, ctx)
    else:
        from .events import emit_step_completed
        await emit_step_completed(execution_id, step_name)
