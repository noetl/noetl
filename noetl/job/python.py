"""
Python action executor for NoETL jobs.
"""

import uuid
import datetime
import os
import json
from typing import Dict, Any, Optional, Callable
from jinja2 import Environment

from noetl.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def execute_python_task(
    task_config: Dict[str, Any], 
    context: Dict[str, Any], 
    jinja_env: Environment, 
    task_with: Dict[str, Any], 
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute a Python task.

    Args:
        task_config: The task configuration
        context: The context for rendering templates
        jinja_env: The Jinja2 environment for template rendering
        task_with: The rendered 'with' parameters dictionary
        log_event_callback: A callback function to log events

    Returns:
        A dictionary of the task result
    """
    logger.debug("=== PYTHON.EXECUTE_PYTHON_TASK: Function entry ===")
    logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Parameters - task_config={task_config}, task_with={task_with}")

    task_id = str(uuid.uuid4())
    # Prefer explicit 'name', then 'task'; fallback to generic
    task_name = task_config.get('name') or task_config.get('task') or 'python_task'
    start_time = datetime.datetime.now()

    logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Generated task_id={task_id}")
    logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Task name={task_name}")
    logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Start time={start_time.isoformat()}")

    try:
        code = task_config.get('code', '')
        logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Python code length={len(code)} chars")

        event_id = None
        if log_event_callback:
            logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Writing task_start event log")
            event_id = log_event_callback(
                'task_start', task_id, task_name, 'python',
                'in_progress', 0, context, None,
                {'with_params': task_with}, None
            )
            logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Task start event_id={event_id}")

        logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Setting up execution globals")
        exec_globals = {
            '__builtins__': __builtins__,
            'context': context,
            'os': os,
            'json': json,
            'datetime': datetime,
            'uuid': uuid
        }
        logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Execution globals keys: {list(exec_globals.keys())}")

        exec_locals = {}
        logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Executing Python code")
        exec(code, exec_globals, exec_locals)
        logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Python execution completed")
        logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Execution locals keys: {list(exec_locals.keys())}")

        if 'main' in exec_locals and callable(exec_locals['main']):
            # Harden common parameter shapes before calling user code
            try:
                if isinstance(task_with, dict):
                    # If city came as a string but context carries a dict, prefer the dict
                    if isinstance(task_with.get('city'), str) and isinstance(context, dict):
                        cw = context.get('city') or (context.get('work', {}).get('city') if isinstance(context.get('work'), dict) else None)
                        if isinstance(cw, dict):
                            task_with['city'] = cw
                    # Threshold coercion: try to resolve from context or parse
                    th = task_with.get('threshold')
                    if isinstance(th, str):
                        # Prefer context.temperature_threshold when available
                        ctx_th = None
                        try:
                            if isinstance(context, dict):
                                ctx_th = context.get('temperature_threshold')
                                if ctx_th is None and isinstance(context.get('work'), dict):
                                    ctx_th = context['work'].get('temperature_threshold')
                        except Exception:
                            ctx_th = None
                        if ctx_th is not None:
                            task_with['threshold'] = ctx_th
                        else:
                            try:
                                task_with['threshold'] = float(th)
                            except Exception:
                                # Default sensible threshold if unresolved
                                task_with['threshold'] = 0
                    # Coerce district string to object with name
                    if isinstance(task_with.get('district'), str):
                        task_with['district'] = {"name": task_with['district']}
                    # Alerts/items/districts as strings: attempt to parse list literal
                    for key in ('alerts','items','districts'):
                        val = task_with.get(key)
                        if isinstance(val, str):
                            try:
                                import ast
                                parsed = ast.literal_eval(val)
                                if isinstance(parsed, (list, dict)):
                                    task_with[key] = parsed
                            except Exception:
                                pass
            except Exception:
                pass
            result_data = exec_locals['main'](**task_with)
            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()

            if log_event_callback:
                log_event_callback(
                    'task_complete', task_id, task_name, 'python',
                    'success', duration, context, result_data,
                    {'with_params': task_with}, event_id
                )

            return {
                'id': task_id,
                'status': 'success',
                'data': result_data
            }
        else:
            error_msg = "Main function must be defined in Python task."
            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()

            if log_event_callback:
                log_event_callback(
                    'task_error', task_id, task_name, 'python',
                    'error', duration, context, None,
                    {'error': error_msg, 'with_params': task_with}, event_id
                )

            return {
                'id': task_id,
                'status': 'error',
                'error': error_msg
            }

    except Exception as e:
        error_msg = str(e)
        logger.error(f"PYTHON.EXECUTE_PYTHON_TASK: Exception - {error_msg}", exc_info=True)

        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()
        logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Task duration={duration} seconds (error path)")

        if log_event_callback:
            logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Writing task_error event log")
            log_event_callback(
                'task_error', task_id, task_name, 'python',
                'error', duration, context, None,
                {'error': error_msg, 'with_params': task_with}, event_id
            )

        result = {
            'id': task_id,
            'status': 'error',
            'error': error_msg
        }
        logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Returning error result={result}")
        logger.debug("=== PYTHON.EXECUTE_PYTHON_TASK: Function exit (error) ===")
        return result


__all__ = ['execute_python_task']
