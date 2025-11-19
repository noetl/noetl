"""
Python action executor for NoETL jobs.
"""

import asyncio
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


def _build_call_kwargs(
    func_signature: inspect.Signature,
    provided_args: Dict[str, Any],
    context: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Resolve function arguments from rendered args and context."""
    context = context or {}
    if not isinstance(context, dict):
        context = {}

    context_input = context.get("input")
    if not isinstance(context_input, dict):
        context_input = {}
    context_data = context.get("data")
    if not isinstance(context_data, dict):
        context_data = {}

    used_keys = set()
    call_kwargs: Dict[str, Any] = {}

    def _lookup(name: str) -> Any:
        if name in provided_args:
            used_keys.add(name)
            return provided_args[name]
        if name in context_input:
            used_keys.add(name)
            return context_input[name]
        if name in context_data:
            used_keys.add(name)
            return context_data[name]
        if name in context:
            used_keys.add(name)
            return context[name]
        raise TypeError(
            f"Missing required argument '{name}' for python task. Provide it via args or context."
        )

    for param in func_signature.parameters.values():
        if param.kind == inspect.Parameter.VAR_POSITIONAL:
            raise TypeError("*args are not supported in python tasks")
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            continue  # handled later
        if param.name == "context":
            call_kwargs["context"] = context
            continue
        if param.kind == inspect.Parameter.KEYWORD_ONLY or param.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD:
            if param.default != inspect.Parameter.empty:
                try:
                    call_kwargs[param.name] = _lookup(param.name)
                except TypeError:
                    call_kwargs[param.name] = param.default
            else:
                call_kwargs[param.name] = _lookup(param.name)

    # Handle **kwargs by merging remaining entries
    if any(
        param.kind == inspect.Parameter.VAR_KEYWORD
        for param in func_signature.parameters.values()
    ):
        merged_kwargs: Dict[str, Any] = {}
        for source in (context_input, context_data, provided_args, context):
            if isinstance(source, dict):
                for key, value in source.items():
                    if key not in call_kwargs and key not in merged_kwargs:
                        merged_kwargs[key] = value
        call_kwargs.update(merged_kwargs)

    return call_kwargs


def _build_call_kwargs(
    signature: inspect.Signature, provided_args: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    """Resolve function arguments from provided args and execution context."""
    if context is None:
        context = {}

    context_input = context.get("input") if isinstance(context, dict) else {}
    if not isinstance(context_input, dict):
        context_input = {}
    context_data = context.get("data") if isinstance(context, dict) else {}
    if not isinstance(context_data, dict):
        context_data = {}

    call_kwargs: Dict[str, Any] = {}
    var_kwargs = False

    def _resolve(name: str) -> Any:
        if name in provided_args:
            return provided_args[name]
        if name in context_input:
            return context_input[name]
        if name in context_data:
            return context_data[name]
        if isinstance(context, dict) and name in context:
            return context[name]
        raise TypeError(
            f"Missing required argument '{name}' for Python task. Provide it via args or context."
        )

    for param in signature.parameters.values():
        if param.kind == inspect.Parameter.VAR_POSITIONAL:
            raise TypeError("*args are not supported in python tasks")
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            var_kwargs = True
            continue
        if param.name == "context":
            call_kwargs["context"] = context
            continue
        try:
            value = _resolve(param.name)
            call_kwargs[param.name] = value
        except TypeError as err:
            if param.default != inspect.Parameter.empty:
                continue
            raise err

    if var_kwargs:
        merged_kwargs: Dict[str, Any] = {}
        for source in (context_input, context_data, provided_args):
            for key, value in source.items():
                if key not in call_kwargs and key not in merged_kwargs:
                    merged_kwargs[key] = value
        call_kwargs.update(merged_kwargs)

    return call_kwargs


async def execute_python_task_async(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    args: Optional[Dict[str, Any]] = None,
    log_event_callback: Optional[Callable] = None,
) -> Dict[str, Any]:
    """Execute a Python task asynchronously."""
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

            # Call main function as async coroutine
            main_func = exec_locals["main"]
            func_signature = inspect.signature(main_func)
            call_kwargs = _build_call_kwargs(func_signature, coerced_args, context)
            logger.info(
                f"PYTHON.CALL: Executing main with kwargs: {list(call_kwargs.keys())}"
            )
            result_data = await _invoke_main(main_func, call_kwargs)

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
            raise RuntimeError("Main function must be defined in Python task.")

    except Exception as e:
        error_msg = str(e)
        logger.exception(f"PYTHON.EXECUTE_PYTHON_TASK: Exception - {error_msg}", exc_info=True)

        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()

        if log_event_callback:
            log_event_callback(
                'task_error', task_id, task_name, 'python',
                'error', duration, context, None,
                {'error': error_msg, 'args': args}, None
            )

        return {
            'id': task_id,
            'status': 'error',
            'error': error_msg
        }


def execute_python_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    args: Optional[Dict[str, Any]] = None,
    log_event_callback: Optional[Callable] = None,
) -> Dict[str, Any]:
    """Backward-compatible synchronous entry point."""
    return asyncio.run(
        execute_python_task_async(
            task_config, context, jinja_env, args, log_event_callback
        )
    )
__all__ = ['execute_python_task', 'execute_python_task_async']


async def _invoke_main(main_func: Callable, kwargs: Dict[str, Any]) -> Any:
    """Execute user-provided main function, supporting both async and sync."""
    if inspect.iscoroutinefunction(main_func):
        return await main_func(**kwargs)

    logger.debug("PYTHON.CALL: main is synchronous; running in default executor")
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: main_func(**kwargs))
