"""
Task execution tool - main entry point for plugin selection and execution.

This module provides the core task execution logic that routes tasks to
appropriate plugin implementations based on task tool. It serves as the
MCP tool interface for executing NoETL playbook actions.
"""

import asyncio
from typing import Any, Callable, Dict, Optional

from jinja2 import Environment

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def _resolve_task_type(task_config: Dict[str, Any]) -> tuple[str, str]:
    """
    Determine the canonical tool identifier for a task configuration.

    Args:
        task_config: Task configuration dictionary

    Returns:
        Tuple of (normalized_tool, raw_tool_value)
    """
    raw_type = task_config.get("tool")
    if not isinstance(raw_type, str) or not raw_type.strip():
        raise ValueError("Task configuration must include a 'tool' field")
    normalized = raw_type.strip().lower()
    task_config["tool"] = raw_type
    return normalized, raw_type


class ResultWrapper(dict):
    """
    Wrapper for step results that supports both dict-style and attribute-style access.

    Enables templates to use both {{ step.data }} and {{ step['data'] }} patterns.
    """

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'"
            )

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


def _wrap_context_results(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Wrap step results in context with ResultWrapper to support .data attribute access.

    Args:
        context: Execution context dictionary

    Returns:
        Context with wrapped results
    """
    wrapped = {}
    for k, v in context.items():
        if isinstance(v, dict) and k not in (
            "workload",
            "execution_id",
            "job_id",
            "job",
            "env",
        ):
            # Wrap dict values that look like step results
            try:
                result = ResultWrapper(v)
                logger.debug(f"Wrapped context key '{k}' with keys: {list(v.keys())}")
                wrapped[k] = result
            except (TypeError, AttributeError, KeyError) as e:
                logger.debug(f"Could not wrap result for key '{k}': {e}")
                wrapped[k] = v
        else:
            wrapped[k] = v
    return wrapped


def execute_task(
    task_config: Dict[str, Any],
    task_name: str,
    context: Dict[str, Any],
    jinja_env: Environment,
    args: Optional[Dict[str, Any]] = None,
    log_event_callback: Optional[Callable] = None,
) -> Dict[str, Any]:
    """
    Execute a task based on its declared tool.

    This is the main entry point for task execution. It routes tasks to the
    appropriate plugin implementation based on the tool (http, python,
    duckdb, postgres, secrets, playbook, workbook, iterator, save).

    Retry logic is handled server-side through the event queue system.
    Workers execute tasks without retry awareness and report results via events.

    Args:
        task_config: The task configuration dictionary
        task_name: Name of the task
        context: Execution context
        jinja_env: Jinja2 environment for template rendering
        args: Task arguments/parameters
        log_event_callback: Optional callback for logging events

    Returns:
        Task execution result

    Raises:
        ValueError: If task tool is unknown or not supported
    """
    # Import plugin executors here to avoid circular imports
    from noetl.plugin.controller.iterator import (
        execute_loop_task as execute_iterator_task,
    )
    from noetl.plugin.controller.playbook import execute_playbook_task
    from noetl.plugin.controller.workbook import execute_workbook_task
    from noetl.plugin.shared.secrets import execute_secrets_task
    from noetl.plugin.shared.storage import execute_sink_task
    from noetl.plugin.tools.duckdb import execute_duckdb_task
    from noetl.plugin.tools.http import execute_http_task
    from noetl.plugin.tools.postgres import execute_postgres_task
    from noetl.plugin.tools.python import execute_python_task
    from noetl.plugin.tools.snowflake import execute_snowflake_task
    from noetl.plugin.tools.transfer import execute_transfer_action
    from noetl.plugin.tools.transfer.snowflake_transfer import (
        execute_snowflake_transfer_action,
    )

    # Check if this step has loop configuration (iterator pattern)
    # If so, delegate to iterator executor regardless of tool type
    logger.critical(f"EXECUTION.execute_task: task='{task_name}', checking for loop attribute")
    logger.critical(f"EXECUTION.execute_task: task_config keys = {list(task_config.keys())}")
    if 'loop' in task_config:
        logger.critical(f"EXECUTION.execute_task: LOOP DETECTED! loop={task_config.get('loop')}")
        logger.critical(f"EXECUTION.execute_task: Routing to iterator executor")
        logger.debug(f"Executing task '{task_name}' with loop configuration")
        wrapped_context = _wrap_context_results(context)
        return execute_iterator_task(
            task_config, wrapped_context, jinja_env, args or {}, log_event_callback
        )
    
    task_type, raw_type = _resolve_task_type(task_config)

    logger.debug(f"Executing task '{task_name}' of tool '{task_type}'")

    # Wrap context results to support .data attribute access in templates
    wrapped_context = _wrap_context_results(context)

    # Dispatch to appropriate action handler
    if task_type == "http":
        # HTTP plugin is async for credential caching support
        # Check if we're already in an async context
        try:
            loop = asyncio.get_running_loop()
            # Already in async context - cannot use asyncio.run()
            # Create a task and get result synchronously using run_until_complete on a new thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    lambda: asyncio.run(execute_http_task(
                        task_config, wrapped_context, jinja_env, args or {}, log_event_callback
                    ))
                )
                return future.result()
        except RuntimeError:
            # No running loop - safe to use asyncio.run()
            return asyncio.run(execute_http_task(
                task_config, wrapped_context, jinja_env, args or {}, log_event_callback
            ))
    elif task_type == "python":
        return execute_python_task(
            task_config, wrapped_context, jinja_env, args or {}, log_event_callback
        )
    elif task_type == "duckdb":
        return execute_duckdb_task(
            task_config, wrapped_context, jinja_env, args or {}, log_event_callback
        )
    elif task_type == "postgres":
        return execute_postgres_task(
            task_config, wrapped_context, jinja_env, args or {}, log_event_callback
        )
    elif task_type == "container":
        # Lazy import to avoid optional deps unless needed
        from noetl.plugin.tools.container import execute_container_task
        return execute_container_task(
            task_config, wrapped_context, jinja_env, args or {}, log_event_callback
        )
    elif task_type == "snowflake":
        return execute_snowflake_task(
            task_config, wrapped_context, jinja_env, args or {}, log_event_callback
        )
    elif task_type == "snowflake_transfer":
        return execute_snowflake_transfer_action(
            task_config, wrapped_context, jinja_env, args or {}, log_event_callback
        )
    elif task_type == "transfer":
        # Generic transfer executor - infers direction from source/target types
        return execute_transfer_action(
            task_config, wrapped_context, jinja_env, args or {}, log_event_callback
        )
    elif task_type == "secrets":
        # For secrets, we need to get the secret_manager from context or somewhere
        secret_manager = wrapped_context.get("secret_manager")
        return execute_secrets_task(
            task_config, wrapped_context, secret_manager, args or {}, log_event_callback
        )
    elif task_type == "playbook":
        return execute_playbook_task(
            task_config, wrapped_context, jinja_env, args or {}, log_event_callback
        )
    elif task_type == "workbook":
        # Workbook tasks need async execution for catalog access
        return _execute_workbook_async(
            execute_workbook_task,
            task_config,
            wrapped_context,
            jinja_env,
            args,
            log_event_callback,
        )
    elif task_type == 'sink':
        return execute_sink_task(
            task_config, wrapped_context, jinja_env, args or {}, log_event_callback
        )
    else:
        raise ValueError(
            f"Unknown task tool '{raw_type}'. "
            f"Available tools: http, python, duckdb, postgres, container, snowflake, snowflake_transfer, transfer, secrets, playbook, workbook, save. "
            f"Note: Use 'loop:' attribute to iterate over collections, not 'tool: iterator'."
        )


def _execute_workbook_async(
    execute_workbook_task: Callable,
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    args: Optional[Dict[str, Any]],
    log_event_callback: Optional[Callable],
) -> Dict[str, Any]:
    """
    Execute workbook task with proper async handling.

    Workbook tasks require async execution for catalog access. This helper
    ensures proper event loop handling in worker threads.

    Args:
        execute_workbook_task: The workbook task executor function
        task_config: Task configuration
        context: Execution context
        jinja_env: Jinja2 environment
        args: Task arguments
        log_event_callback: Optional event logging callback

    Returns:
        Task execution result
    """
    import asyncio

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(
        execute_workbook_task(task_config, context, jinja_env, args, log_event_callback)
    )


def execute_task_resolved(
    task_config: Dict[str, Any],
    task_name: str,
    context: Dict[str, Any],
    jinja_env: Environment,
    args: Optional[Dict[str, Any]] = None,
    log_event_callback: Optional[Callable] = None,
) -> Dict[str, Any]:
    """
    Execute a task with resolved configuration.

    This is an alias for execute_task provided for backwards compatibility.

    Args:
        task_config: The task configuration dictionary
        task_name: Name of the task
        context: Execution context
        jinja_env: Jinja2 environment for template rendering
        args: Task arguments
        log_event_callback: Optional callback for logging events

    Returns:
        Task execution result
    """
    return execute_task(
        task_config, task_name, context, jinja_env, args, log_event_callback
    )
