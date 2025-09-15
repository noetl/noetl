"""
Python action executor for NoETL jobs.
"""

import uuid
import datetime
import os
import json
from typing import Dict, Any, Optional, Callable
from jinja2 import Environment

from noetl.core.logger import setup_logger
import ast

logger = setup_logger(__name__, include_location=True)


def _coerce_param(value: Any) -> Any:
    """Best-effort coercion of stringified literals into Python objects.
    - Parses dict/list literals using ast.literal_eval to handle single quotes.
    - Falls back to JSON when appropriate
    - Leaves other types as-is
    """
    try:
        if isinstance(value, str):
            s = value.strip()
            if (s.startswith('{') and s.endswith('}')) or (s.startswith('[') and s.endswith(']')):
                try:
                    return json.loads(s)
                except Exception:
                    try:
                        return ast.literal_eval(s)
                    except Exception:
                        return value
        return value
    except Exception:
        return value


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
        # Prefer base64-encoded code when provided; fallback to plain inline 'code'
        code_b64 = task_config.get('code_b64', '')
        code_base64 = task_config.get('code_base64', '')  # Backward compatibility

        code = ''
        if code_b64:
            import base64
            try:
                code = base64.b64decode(code_b64.encode('ascii')).decode('utf-8')
                logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Decoded base64 code, length={len(code)} chars")
            except Exception as e:
                logger.error(f"PYTHON.EXECUTE_PYTHON_TASK: Failed to decode base64 code: {e}")
                raise ValueError(f"Invalid base64 code encoding: {e}")
        elif code_base64:
            import base64
            try:
                code = base64.b64decode(code_base64.encode('ascii')).decode('utf-8')
                logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Decoded backward-compatible base64 code, length={len(code)} chars")
            except Exception as e:
                logger.error(f"PYTHON.EXECUTE_PYTHON_TASK: Failed to decode backward-compatible base64 code: {e}")
                raise ValueError(f"Invalid backward-compatible base64 code encoding: {e}")
        else:
            inline_code = task_config.get('code')
            if isinstance(inline_code, str) and inline_code.strip():
                code = inline_code
                logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Using inline code, length={len(code)} chars")
            else:
                raise ValueError("No code provided. Expected 'code_b64', 'code_base64', or inline 'code' string in task configuration")

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
            # Render and normalize parameters from 'with' using server-evaluated context
            # 1) Render Jinja templates against provided context
            rendered_with = {}
            try:
                for k, v in (task_with or {}).items():
                    if isinstance(v, str):
                        try:
                            tmpl = jinja_env.from_string(v)
                            rendered_with[k] = tmpl.render(context or {})
                        except Exception:
                            rendered_with[k] = v
                    else:
                        rendered_with[k] = v
            except Exception:
                rendered_with = task_with or {}

            # 2) Coerce common literal/JSON strings to Python objects
            normalized_with = {}
            try:
                for k, v in rendered_with.items():
                    normalized_with[k] = _coerce_param(v)
            except Exception:
                normalized_with = rendered_with

            result_data = exec_locals['main'](**normalized_with)
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
