"""
Playbook action executor for NoETL jobs.
"""

import uuid
import datetime
import json
import importlib
import os
import yaml
from typing import Dict, Any, Optional, Callable
from jinja2 import Environment

from noetl.core.dsl.render import render_template
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def execute_playbook_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Dict[str, Any],
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute a playbook task.

    Args:
        task_config: The task configuration
        context: The context to use for rendering templates
        jinja_env: The Jinja2 environment for template rendering
        task_with: The rendered 'with' parameters dictionary
        log_event_callback: A callback function to log events

    Returns:
        A dictionary of the task result
    """
    logger.debug("=== PLAYBOOK.EXECUTE_PLAYBOOK_TASK: Function entry ===")
    logger.debug(f"PLAYBOOK.EXECUTE_PLAYBOOK_TASK: Parameters - task_config={task_config}, task_with={task_with}")

    task_id = str(uuid.uuid4())
    task_name = task_config.get('task', 'playbook_task')
    start_time = datetime.datetime.now()

    logger.debug(f"PLAYBOOK.EXECUTE_PLAYBOOK_TASK: Generated task_id={task_id}")
    logger.debug(f"PLAYBOOK.EXECUTE_PLAYBOOK_TASK: Task name={task_name}")
    logger.debug(f"PLAYBOOK.EXECUTE_PLAYBOOK_TASK: Start time={start_time.isoformat()}")

    try:
        # Debug: Log all available parameters in task_config
        logger.debug(f"PLAYBOOK.EXECUTE_PLAYBOOK_TASK: Available task_config keys: {list(task_config.keys())}")
        logger.debug(f"PLAYBOOK.EXECUTE_PLAYBOOK_TASK: Full task_config: {task_config}")
        
        # Get playbook path from task configuration - check multiple possible parameter names
        playbook_path = (task_config.get('resource_path') or 
                        task_config.get('playbook_path') or 
                        task_config.get('path'))
        
        playbook_content = (task_config.get('content') or 
                           task_config.get('playbook_content'))
        
        logger.debug(f"PLAYBOOK.EXECUTE_PLAYBOOK_TASK: Extracted playbook_path: {playbook_path}")
        logger.debug(f"PLAYBOOK.EXECUTE_PLAYBOOK_TASK: Extracted playbook_content: {playbook_content is not None}")
        
        # Check if this is a "playbooks" type task (referencing another playbook by path)
        if not playbook_path and not playbook_content:
            # If no explicit path/content, this might be a task referencing another playbook
            # Let's check for common patterns
            task_path = task_config.get('path')  # Common in multi-playbook scenarios
            if task_path:
                playbook_path = task_path
                logger.debug(f"PLAYBOOK.EXECUTE_PLAYBOOK_TASK: Using path parameter: {playbook_path}")
            else:
                # Maybe this is supposed to be a "workbook" type task instead?
                task_ref = task_config.get('task')
                if task_ref:
                    error_msg = f"Playbook task requires 'resource_path' or 'path' parameter to reference another playbook. If you want to execute a task from the workbook, use type 'workbook' instead of 'playbook'. Available parameters: {list(task_config.keys())}"
                    logger.error(f"PLAYBOOK.EXECUTE_PLAYBOOK_TASK: {error_msg}")
                    return {
                        'id': task_id,
                        'status': 'error', 
                        'error': error_msg
                    }
                else:
                    error_msg = f"Playbook task requires 'resource_path', 'path', or 'content' parameter. Available parameters: {list(task_config.keys())}"
                    logger.error(f"PLAYBOOK.EXECUTE_PLAYBOOK_TASK: {error_msg}")
                    return {
                        'id': task_id,
                        'status': 'error', 
                        'error': error_msg
                    }

        # If we have a path but no content, try to read the content
        if playbook_path and not playbook_content:
            try:
                # For path-based playbook execution, we need to load the playbook from the path
                logger.info(f"PLAYBOOK.EXECUTE_PLAYBOOK_TASK: Loading playbook from path: {playbook_path}")
                
                # Try to load playbook from file system (common pattern in examples)
                import os
                import yaml
                
                # Check common playbook file locations
                possible_paths = [
                    f"/Users/kadyapam/projects/noetl/noetl/examples/{playbook_path.replace('examples/', '')}.yaml",
                    f"/Users/kadyapam/projects/noetl/noetl/{playbook_path}.yaml",
                    f"{playbook_path}.yaml",
                    playbook_path
                ]
                
                content_loaded = False
                for file_path in possible_paths:
                    if os.path.exists(file_path):
                        logger.debug(f"PLAYBOOK.EXECUTE_PLAYBOOK_TASK: Found playbook file at: {file_path}")
                        with open(file_path, 'r') as f:
                            playbook_data = yaml.safe_load(f)
                            playbook_content = yaml.dump(playbook_data)
                            content_loaded = True
                            break
                
                if not content_loaded:
                    # If file not found, create a minimal playbook reference
                    # This allows the broker to handle the playbook resolution
                    logger.debug(f"PLAYBOOK.EXECUTE_PLAYBOOK_TASK: Playbook file not found locally, using path reference")
                    playbook_content = f"""
apiVersion: noetl.io/v1
kind: Playbook
name: {playbook_path.split('/')[-1]}
path: {playbook_path}
workload: {{}}
workflow:
  - step: start
    desc: "Placeholder for path-referenced playbook"
    next:
      - step: end
  - step: end
    desc: "End"
"""
                    
            except Exception as e:
                error_msg = f"Failed to load playbook from path {playbook_path}: {str(e)}"
                logger.error(f"PLAYBOOK.EXECUTE_PLAYBOOK_TASK: {error_msg}")
                return {
                    'id': task_id,
                    'status': 'error',
                    'error': error_msg
                }

        # Render playbook content if needed
        if playbook_content:
            try:
                # Render the playbook content with the current context
                rendered_content = render_template(jinja_env, playbook_content, context)
                logger.debug(f"PLAYBOOK.EXECUTE_PLAYBOOK_TASK: Rendered playbook content")
            except Exception as e:
                error_msg = f"Failed to render playbook content: {str(e)}"
                logger.error(f"PLAYBOOK.EXECUTE_PLAYBOOK_TASK: {error_msg}")
                return {
                    'id': task_id,
                    'status': 'error',
                    'error': error_msg
                }
        else:
            rendered_content = ""

        # Get playbook version
        playbook_version = task_config.get('version', 'latest')

        # Merge task_with parameters into context for the nested playbook
        nested_context = context.copy()
        if task_with:
            nested_context.update(task_with)

        # Get parent execution information for nested tracking
        parent_execution_id = context.get('execution_id')
        parent_event_id = context.get('event_id')
        parent_step = task_name

        logger.info(f"PLAYBOOK.EXECUTE_PLAYBOOK_TASK: Executing nested playbook - path={playbook_path}, version={playbook_version}")

        # Execute the playbook (support loop expansion when provided)
        try:
            # Dynamic import to avoid circular dependency
            from noetl.server.api.broker.execute import execute_playbook_via_broker

            loop_cfg = task_config.get('loop') if isinstance(task_config.get('loop'), dict) else None
            if loop_cfg and ('in' in loop_cfg):
                # Evaluate items expression
                items_expr = loop_cfg.get('in')
                try:
                    # Build a richer context for resolving loop items: merge context + work + workload + input + with
                    loop_ctx = dict(context) if isinstance(context, dict) else {}
                    try:
                        if isinstance(context, dict):
                            if isinstance(context.get('work'), dict):
                                for k, v in context['work'].items():
                                    loop_ctx.setdefault(k, v)
                            if isinstance(context.get('workload'), dict):
                                for k, v in context['workload'].items():
                                    loop_ctx.setdefault(k, v)
                            if isinstance(context.get('input'), dict):
                                for k, v in context['input'].items():
                                    loop_ctx.setdefault(k, v)
                    except Exception:
                        pass
                    try:
                        if isinstance(task_with, dict):
                            for k, v in task_with.items():
                                loop_ctx.setdefault(k, v)
                    except Exception:
                        pass
                    rendered_items = render_template(jinja_env, items_expr, loop_ctx) if isinstance(items_expr, str) else items_expr
                except Exception:
                    rendered_items = items_expr
                # Coerce rendered_items to Python list when possible
                items = []
                if isinstance(rendered_items, list):
                    items = rendered_items
                elif isinstance(rendered_items, str):
                    try:
                        import json as _json
                        items = _json.loads(rendered_items)
                    except Exception:
                        try:
                            import ast as _ast
                            items = _ast.literal_eval(rendered_items)
                        except Exception:
                            # Fallback: treat as single item string
                            items = [rendered_items]
                else:
                    items = [rendered_items]

                iterator_name = loop_cfg.get('iterator') or 'item'
                distribution = bool(loop_cfg.get('distribution'))

                results = []
                child_ids = []
                total = len(items or [])
                for idx, item in enumerate(items or []):
                    # Per-iteration render context
                    iter_ctx = dict(context)
                    try:
                        # ensure nested dicts are preserved (e.g., 'work')
                        if 'work' in context and isinstance(context['work'], dict):
                            iter_ctx['work'] = dict(context['work'])
                            iter_ctx['work'][iterator_name] = item
                        iter_ctx[iterator_name] = item
                        # Provide _loop metadata similar to server rendering
                        iter_ctx['_loop'] = {
                            'current_index': idx,
                            'index': idx,
                            'item': item,
                            'count': total,
                        }
                    except Exception:
                        iter_ctx[iterator_name] = item

                    # Re-render 'with' parameters against the iter context
                    per_with_raw = task_config.get('with') or {}
                    per_with: Dict[str, Any] = {}
                    for k, v in per_with_raw.items():
                        try:
                            per_with[k] = render_template(jinja_env, v, iter_ctx) if isinstance(v, str) else v
                        except Exception:
                            per_with[k] = v

                    # Build input payload for child playbook
                    iter_nested_ctx = dict(context)
                    try:
                        iter_nested_ctx.update(per_with)
                    except Exception:
                        pass

                    # Execute child playbook via broker (sequentially)
                    child_result = execute_playbook_via_broker(
                        playbook_content=rendered_content,
                        playbook_path=playbook_path or f"nested/{task_name}",
                        playbook_version=playbook_version,
                        input_payload=iter_nested_ctx,
                        sync_to_postgres=True,
                        merge=True,
                        parent_execution_id=parent_execution_id,
                        parent_event_id=parent_event_id,
                        parent_step=parent_step
                    )
                    results.append(child_result)
                    if isinstance(child_result, dict) and child_result.get('execution_id'):
                        child_ids.append(child_result.get('execution_id'))

                end_time = datetime.datetime.now()
                duration = (end_time - start_time).total_seconds()
                logger.info(f"PLAYBOOK.EXECUTE_PLAYBOOK_TASK: Loop executed for {len(items)} iterations (distribution={distribution})")

                # Log success event
                if log_event_callback:
                    event_id = str(uuid.uuid4())
                    log_event_callback(
                        'task_end', task_id, task_name, 'playbook',
                        'success', duration, context,
                        {
                            'results': results,
                            'child_execution_ids': child_ids,
                            'distributed': distribution,
                            'count': len(results)
                        },
                        {'with_params': task_with}, event_id
                    )

                success_result = {
                    'id': task_id,
                    'status': 'success',
                    'data': {
                        'results': results,
                        'child_execution_ids': child_ids,
                        'distributed': distribution,
                        'count': len(results)
                    }
                }
                return success_result

            # No loop: single execution
            result = execute_playbook_via_broker(
                playbook_content=rendered_content,
                playbook_path=playbook_path or f"nested/{task_name}",
                playbook_version=playbook_version,
                input_payload=nested_context,
                sync_to_postgres=True,
                merge=True,
                parent_execution_id=parent_execution_id,
                parent_event_id=parent_event_id,
                parent_step=parent_step
            )

            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()

            logger.info(f"PLAYBOOK.EXECUTE_PLAYBOOK_TASK: Nested playbook execution completed")
            logger.debug(f"PLAYBOOK.EXECUTE_PLAYBOOK_TASK: Task duration={duration} seconds")

            # Log success event
            if log_event_callback:
                logger.debug(f"PLAYBOOK.EXECUTE_PLAYBOOK_TASK: Writing task_end event log")
                event_id = str(uuid.uuid4())
                log_event_callback(
                    'task_end', task_id, task_name, 'playbook',
                    'success', duration, context, result,
                    {'with_params': task_with}, event_id
                )

            # Return success result
            success_result = {
                'id': task_id,
                'status': 'success',
                'data': result,
                'execution_id': result.get('execution_id'),
                'duration': duration
            }

            logger.debug(f"PLAYBOOK.EXECUTE_PLAYBOOK_TASK: Returning success result={success_result}")
            logger.debug("=== PLAYBOOK.EXECUTE_PLAYBOOK_TASK: Function exit (success) ===")
            return success_result

        except Exception as e:
            error_msg = f"Playbook execution failed: {str(e)}"
            logger.error(f"PLAYBOOK.EXECUTE_PLAYBOOK_TASK: {error_msg}", exc_info=True)
            
            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()

            # Log error event
            if log_event_callback:
                logger.debug(f"PLAYBOOK.EXECUTE_PLAYBOOK_TASK: Writing task_error event log")
                event_id = str(uuid.uuid4())
                log_event_callback(
                    'task_error', task_id, task_name, 'playbook',
                    'error', duration, context, None,
                    {'error': error_msg, 'with_params': task_with}, event_id
                )

            return {
                'id': task_id,
                'status': 'error',
                'error': error_msg,
                'duration': duration
            }

    except Exception as e:
        error_msg = f"Unexpected error in playbook task: {str(e)}"
        logger.error(f"PLAYBOOK.EXECUTE_PLAYBOOK_TASK: {error_msg}", exc_info=True)
        
        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()
        logger.debug(f"PLAYBOOK.EXECUTE_PLAYBOOK_TASK: Task duration={duration} seconds (error path)")

        if log_event_callback:
            logger.debug(f"PLAYBOOK.EXECUTE_PLAYBOOK_TASK: Writing task_error event log")
            event_id = str(uuid.uuid4())
            log_event_callback(
                'task_error', task_id, task_name, 'playbook',
                'error', duration, context, None,
                {'error': error_msg, 'with_params': task_with}, event_id
            )

        result = {
            'id': task_id,
            'status': 'error',
            'error': error_msg
        }
        logger.debug(f"PLAYBOOK.EXECUTE_PLAYBOOK_TASK: Returning error result={result}")
        logger.debug("=== PLAYBOOK.EXECUTE_PLAYBOOK_TASK: Function exit (error) ===")
        return result


__all__ = ['execute_playbook_task']
