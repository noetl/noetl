"""
Python action executor for NoETL jobs.
"""

import uuid
import datetime
import os
import json
import inspect
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
        task_config: Task configuration
        context: Execution context
        jinja_env: Jinja2 environment for template rendering
        task_with: Task parameters
        log_event_callback: Optional callback for logging events

    Returns:
        Dict containing execution result
    """
    logger.debug("=== PYTHON.EXECUTE_PYTHON_TASK: Function entry ===")
    start_time = datetime.datetime.now()
    logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Start time={start_time}")

    task_id = str(uuid.uuid4())
    task_name = task_config.get('name', 'unnamed_python_task')
    logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Task ID={task_id}, name={task_name}")

    try:
        logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Task config keys: {list(task_config.keys())}")
        logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Task with keys: {list((task_with or {}).keys())}")
        logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Context keys: {list((context or {}).keys())}")

        # Get and decode the code
        code = None
        if 'code_b64' in task_config:
            import base64
            code = base64.b64decode(task_config['code_b64']).decode('utf-8')
            logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Decoded base64 code, length={len(code)} chars")
        elif 'code_base64' in task_config:
            import base64
            code = base64.b64decode(task_config['code_base64']).decode('utf-8')
            logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Decoded base64 code, length={len(code)} chars")
        elif 'code' in task_config:
            code = task_config['code']
            logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Using inline code, length={len(code)} chars")

        if not code:
            if 'code' in task_config:
                raise ValueError("Empty code provided.")
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

            # Enhanced function signature detection and flexible calling
            main_func = exec_locals['main']
            func_signature = inspect.signature(main_func)
            params = list(func_signature.parameters.keys())
            
            logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Function signature: {func_signature}")
            logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Function parameters: {params}")
            
            # Determine how to call the function based on its signature
            result_data = None
            
            if len(params) == 0:
                # Function takes no parameters: def main():
                logger.debug("PYTHON.EXECUTE_PYTHON_TASK: Calling function with no parameters")
                result_data = main_func()
                
            elif len(params) == 1 and 'input_data' in params:
                # Legacy function signature: def main(input_data):
                logger.debug("PYTHON.EXECUTE_PYTHON_TASK: Calling function with input_data parameter")
                input_data = {
                    'context': context,
                    'with': normalized_with,
                    **normalized_with  # Also include with params at top level
                }
                result_data = main_func(input_data)
                
            elif any(param.kind == inspect.Parameter.VAR_KEYWORD for param in func_signature.parameters.values()):
                # Function accepts **kwargs: def main(**kwargs):
                logger.debug("PYTHON.EXECUTE_PYTHON_TASK: Calling function with **kwargs")
                call_kwargs = {
                    'context': context,
                    **normalized_with
                }
                result_data = main_func(**call_kwargs)
                
            else:
                # Function has specific named parameters
                logger.debug("PYTHON.EXECUTE_PYTHON_TASK: Calling function with specific named parameters")
                call_kwargs = {}
                
                # Map available data to function parameters
                available_data = {
                    'context': context,
                    **normalized_with
                }
                
                for param_name in params:
                    if param_name in available_data:
                        call_kwargs[param_name] = available_data[param_name]
                    elif param_name == 'input_data':
                        # Provide input_data if specifically requested
                        call_kwargs['input_data'] = {
                            'context': context,
                            'with': normalized_with,
                            **normalized_with
                        }
                
                result_data = main_func(**call_kwargs)

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