"""
Task execution tool - main entry point for plugin selection and execution.

This module provides the core task execution logic that routes tasks to
appropriate plugin implementations based on task type. It serves as the
MCP tool interface for executing NoETL playbook actions.
"""

from typing import Dict, Any, Optional, Callable
from jinja2 import Environment

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def execute_task(
    task_config: Dict[str, Any],
    task_name: str,
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Optional[Dict[str, Any]] = None,
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute a task based on its type.
    
    This is the main entry point for task execution. It routes tasks to the
    appropriate plugin implementation based on the task type (http, python,
    duckdb, postgres, secrets, playbook, workbook, iterator, save).

    Args:
        task_config: The task configuration dictionary
        task_name: Name of the task
        context: Execution context
        jinja_env: Jinja2 environment for template rendering
        task_with: Additional parameters from 'with' clause
        log_event_callback: Optional callback for logging events

    Returns:
        Task execution result

    Raises:
        ValueError: If task type is unknown or not supported
    """
    # Import plugin executors here to avoid circular imports
    from ..http import execute_http_task
    from ..python import execute_python_task
    from ..duckdb import execute_duckdb_task
    from ..postgres import execute_postgres_task
    from ..secrets import execute_secrets_task
    from ..playbook import execute_playbook_task
    from ..workbook import execute_workbook_task
    from ..save import execute_save_task
    from ..iterator import execute_loop_task as execute_iterator_task
    
    raw_type = task_config.get('type', task_config.get('action', 'unknown'))
    task_type = str(raw_type).strip().lower()

    logger.debug(f"Executing task '{task_name}' of type '{task_type}'")

    # Dispatch to appropriate action handler
    if task_type == 'http':
        return execute_http_task(task_config, context, jinja_env, task_with or {}, log_event_callback)
    elif task_type == 'python':
        return execute_python_task(task_config, context, jinja_env, task_with or {}, log_event_callback)
    elif task_type == 'duckdb':
        return execute_duckdb_task(task_config, context, jinja_env, task_with or {}, log_event_callback)
    elif task_type == 'postgres':
        return execute_postgres_task(task_config, context, jinja_env, task_with or {}, log_event_callback)
    elif task_type == 'secrets':
        # For secrets, we need to get the secret_manager from context or somewhere
        secret_manager = context.get('secret_manager')
        return execute_secrets_task(task_config, context, secret_manager, task_with or {}, log_event_callback)
    elif task_type == 'playbook':
        return execute_playbook_task(task_config, context, jinja_env, task_with or {}, log_event_callback)
    elif task_type == 'workbook':
        # Workbook tasks need async execution for catalog access
        return _execute_workbook_async(execute_workbook_task, task_config, context, jinja_env, task_with, log_event_callback)
    elif task_type == 'save':
        return execute_save_task(task_config, context, jinja_env, task_with or {}, log_event_callback)
    elif task_type == 'iterator':
        return execute_iterator_task(task_config, context, jinja_env, task_with or {}, log_event_callback)
    else:
        raise ValueError(
            f"Unknown task type '{raw_type}'. "
            f"Available types: http, python, duckdb, postgres, secrets, playbook, workbook, iterator, save"
        )


def _execute_workbook_async(
    execute_workbook_task: Callable,
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Optional[Dict[str, Any]],
    log_event_callback: Optional[Callable]
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
        task_with: Additional parameters
        log_event_callback: Event logging callback
        
    Returns:
        Task execution result
    """
    import asyncio
    
    if asyncio.iscoroutinefunction(execute_workbook_task):
        # In worker threads, there may be no running event loop; prefer asyncio.run
        try:
            return asyncio.run(
                execute_workbook_task(task_config, context, jinja_env, task_with or {}, log_event_callback)
            )
        except RuntimeError:
            # Fallback: create and manage a new event loop explicitly
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(
                    execute_workbook_task(task_config, context, jinja_env, task_with or {}, log_event_callback)
                )
            finally:
                try:
                    asyncio.set_event_loop(None)
                except Exception:
                    pass
                loop.close()
    else:
        return execute_workbook_task(task_config, context, jinja_env, task_with or {}, log_event_callback)


def execute_task_resolved(
    task_config: Dict[str, Any],
    task_name: str,
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Optional[Dict[str, Any]] = None,
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute a task with resolved configuration.
    
    This is an alias for execute_task provided for backwards compatibility.
    
    Args:
        task_config: The task configuration dictionary
        task_name: Name of the task
        context: Execution context
        jinja_env: Jinja2 environment for template rendering
        task_with: Additional parameters from 'with' clause
        log_event_callback: Optional callback for logging events

    Returns:
        Task execution result
    """
    return execute_task(task_config, task_name, context, jinja_env, task_with, log_event_callback)
