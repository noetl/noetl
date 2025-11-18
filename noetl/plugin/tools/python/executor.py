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
    args: Optional[Dict[str, Any]] = None,
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute a Python task.

    Args:
        task_config: Task configuration
        context: Execution context
        jinja_env: Jinja2 environment for template rendering
        args: Task arguments/parameters
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

    # Extract args from task_config if not provided as parameter
    # This allows 'args' field in YAML to be used
    if not args:
        args = task_config.get('args', {})
        logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Extracted args from task_config: {args}")
    else:
        # Merge task_config args with provided args (provided args take precedence)
        config_args = task_config.get('args', {})
        if config_args:
            merged_args = {**config_args, **args}
            logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Merged config args with provided args")
            args = merged_args
    
    # Use args if provided, otherwise empty dict
    args = args or {}

    try:
        logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Task config keys: {list(task_config.keys())}")
        logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Args keys: {args}")
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
                {'args': args}, None
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
            # Render Jinja templates in args against context
            rendered_args = {}
            try:
                for k, v in args.items():
                    # Check if value is a TaskResultProxy object (has _data attribute)
                    if hasattr(v, '_data'):
                        logger.info(f"PYTHON.RENDER: Unwrapping TaskResultProxy for key={k}")
                        rendered_args[k] = v._data
                    # Check if value is dict or list (already resolved data structures)
                    elif isinstance(v, (dict, list)):
                        logger.info(f"PYTHON.RENDER: Using dict/list directly for key={k}, type={type(v).__name__}")
                        rendered_args[k] = v
                    elif isinstance(v, str):
                        try:
                            logger.info(f"PYTHON.RENDER: Rendering template for key={k}, value={v[:100]}")
                            tmpl = jinja_env.from_string(v)
                            rendered = tmpl.render(context or {})
                            logger.info(f"PYTHON.RENDER: Rendered result for key={k}: {rendered[:200]}")
                            rendered_args[k] = rendered
                        except Exception as render_ex:
                            logger.exception(f"PYTHON.RENDER: Exception rendering key={k}: {render_ex}")
                            rendered_args[k] = v
                    else:
                        rendered_args[k] = v
            except Exception:
                rendered_args = args

            # Coerce string literals to Python objects (e.g., "30" -> 30)
            coerced_args = {}
            try:
                for k, v in rendered_args.items():
                    coerced = _coerce_param(v)
                    logger.info(f"PYTHON.COERCE: key={k}, type before={type(v).__name__}, type after={type(coerced).__name__}, value={str(coerced)[:200]}")
                    coerced_args[k] = coerced
            except Exception as coerce_ex:
                logger.exception(f"PYTHON.COERCE: Exception: {coerce_ex}")
                coerced_args = rendered_args

            # Call main function based on its signature
            main_func = exec_locals['main']
            func_signature = inspect.signature(main_func)
            params = list(func_signature.parameters.keys())
            
            logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Function signature: {func_signature}")
            logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Function parameters: {params}")
            logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Available args: {list(coerced_args.keys())}")
            
            result_data = None
            
            if len(params) == 0:
                # Function takes no parameters: def main():
                logger.debug("PYTHON.CALL: Calling function with no parameters")
                result_data = main_func()
                
            elif len(params) == 1 and 'input_data' in params:
                # Legacy function signature: def main(input_data):
                logger.debug("PYTHON.CALL: Calling function with input_data parameter")
                input_data_value = coerced_args.get('input_data')
                logger.info(f"PYTHON.CALL: Passing input_data value type={type(input_data_value).__name__}, value={str(input_data_value)[:200]}")
                result_data = main_func(input_data_value)
                
            elif any(param.kind == inspect.Parameter.VAR_KEYWORD for param in func_signature.parameters.values()):
                # Function accepts **kwargs: def main(**kwargs):
                logger.debug("PYTHON.CALL: Calling function with **kwargs")
                call_kwargs = {'context': context, **coerced_args}
                logger.info(f"PYTHON.CALL: Passing kwargs: {list(call_kwargs.keys())}")
                result_data = main_func(**call_kwargs)
                
            else:
                # Function has specific named parameters: def main(param1, param2, ...):
                logger.debug("PYTHON.CALL: Calling function with specific named parameters")
                call_kwargs = {}
                
                # Map args to function parameters by name
                for param_name in params:
                    if param_name in coerced_args:
                        call_kwargs[param_name] = coerced_args[param_name]
                        logger.info(f"PYTHON.CALL: Mapped arg '{param_name}' = {str(coerced_args[param_name])[:100]}")
                    elif param_name == 'context':
                        call_kwargs['context'] = context
                        logger.info(f"PYTHON.CALL: Mapped 'context'")
                    else:
                        # Check if parameter has a default value
                        param_obj = func_signature.parameters[param_name]
                        if param_obj.default == inspect.Parameter.empty:
                            raise TypeError(f"Missing required argument: '{param_name}'")
                
                logger.info(f"PYTHON.CALL: Final kwargs: {list(call_kwargs.keys())}")
                result_data = main_func(**call_kwargs)

            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()

            if log_event_callback:
                log_event_callback(
                    'task_complete', task_id, task_name, 'python',
                    'success', duration, context, result_data,
                    {'args': args}, event_id
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
                    {'error': error_msg, 'args': args}, event_id
                )

            return {
                'id': task_id,
                'status': 'error',
                'error': error_msg
            }

    except Exception as e:
        error_msg = str(e)
        logger.exception(f"PYTHON.EXECUTE_PYTHON_TASK: Exception - {error_msg}", exc_info=True)

        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()
        logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Task duration={duration} seconds (error path)")

        if log_event_callback:
            logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Writing task_error event log")
            log_event_callback(
                'task_error', task_id, task_name, 'python',
                'error', duration, context, None,
                {'error': error_msg, 'args': args}, event_id
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
