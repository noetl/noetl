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
    event_callback: Optional[Callable] = None
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
        event_callback: Optional callback for emitting iterator/loop events

    Returns:
        Task execution result

    Raises:
        ValueError: If task tool is unknown or not supported
    """
    # Import plugin executors here to avoid circular imports
    from noetl.plugin.controller.playbook import execute_playbook_task
    from noetl.plugin.controller.workbook import execute_workbook_task
    from noetl.plugin.shared.secrets import execute_secrets_task
    from noetl.plugin.shared.storage import execute_sink_task
    # Note: container tool is imported lazily below only if needed to avoid optional deps
    from noetl.plugin.tools.duckdb import execute_duckdb_task
    from noetl.plugin.tools.http import execute_http_task
    from noetl.plugin.tools.postgres import execute_postgres_task
    from noetl.plugin.tools.python import execute_python_task
    from noetl.plugin.tools.snowflake import execute_snowflake_task
    from noetl.plugin.tools.transfer import execute_transfer_action
    from noetl.plugin.tools.transfer.snowflake_transfer import (
        execute_snowflake_transfer_action,
    )

    task_type, raw_type = _resolve_task_type(task_config)

    logger.debug(f"Executing task '{task_name}' of tool '{task_type}'")

    # Wrap context results to support .data attribute access in templates
    wrapped_context = _wrap_context_results(context)

    # Dispatch to appropriate action handler
    if task_type == "http":
        # Check if retry.on_success is configured - this needs worker-side execution
        retry_config = task_config.get('retry') or {}
        if retry_config.get('on_success'):
            # Use worker-side retry wrapper for pagination/polling
            from noetl.plugin.runtime.retry import execute_with_retry
            return execute_with_retry(
                lambda cfg, ctx, env, a: asyncio.run(execute_http_task(cfg, ctx, env, a or {})),
                task_config,
                task_name,
                wrapped_context,
                jinja_env,
                args
            )
        # HTTP plugin is async - run directly without retry wrapper
        # on_error retry is handled server-side through event-driven control loop
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    lambda: asyncio.run(execute_http_task(task_config, wrapped_context, jinja_env, args or {}))
                )
                return future.result()
        except RuntimeError:
            return asyncio.run(execute_http_task(task_config, wrapped_context, jinja_env, args or {}))
    elif task_type == "python":
        return execute_python_task(
            task_config, wrapped_context, jinja_env, args or {}
        )
    elif task_type == "duckdb":
        return execute_duckdb_task(
            task_config, wrapped_context, jinja_env, args or {}
        )
    elif task_type == "container":
        # Lazy import to avoid optional deps unless needed
        from noetl.plugin.tools.container import execute_container_task
        return execute_container_task(
            task_config, wrapped_context, jinja_env, args or {}
        )
    elif task_type == "postgres":
        return execute_postgres_task(
            task_config, wrapped_context, jinja_env, args or {}
        )
    elif task_type == "snowflake":
        return execute_snowflake_task(
            task_config, wrapped_context, jinja_env, args or {}
        )
    elif task_type == "snowflake_transfer":
        return execute_snowflake_transfer_action(
            task_config, wrapped_context, jinja_env, args or {}
        )
    elif task_type == "transfer":
        # Generic transfer executor - infers direction from source/target types
        return execute_transfer_action(
            task_config, wrapped_context, jinja_env, args or {}
        )
    elif task_type == "secrets":
        # For secrets, we need to get the secret_manager from context or somewhere
        secret_manager = wrapped_context.get("secret_manager")
        return execute_secrets_task(
            task_config, wrapped_context, secret_manager, args or {}
        )
    elif task_type == "playbook":
        return execute_playbook_task(
            task_config, wrapped_context, jinja_env, args or {}
        )
    elif task_type == "workbook":
        # Workbook tasks need async execution for catalog access
        return _execute_workbook_async(
            execute_workbook_task,
            task_config,
            wrapped_context,
            jinja_env,
            args
        )
    elif task_type == 'sink':
        return execute_sink_task(
            task_config, wrapped_context, jinja_env, args or {}
        )
    else:
        raise ValueError(
            f"Unknown task tool '{raw_type}'. "
            f"Available tools: http, python, duckdb, postgres, container, snowflake, snowflake_transfer, transfer, secrets, playbook, workbook, save. "
            f"Note: 'loop:' attribute is handled server-side for distributed iteration."
        )


def _execute_workbook_async(
    execute_workbook_task: Callable,
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    args: Optional[Dict[str, Any]]
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
        execute_workbook_task(task_config, context, jinja_env, args)
    )


def execute_task_resolved(
    task_config: Dict[str, Any],
    task_name: str,
    context: Dict[str, Any],
    jinja_env: Environment,
    args: Optional[Dict[str, Any]] = None
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

    Returns:
        Task execution result
    """
    return execute_task(
        task_config, task_name, context, jinja_env, args
    )
