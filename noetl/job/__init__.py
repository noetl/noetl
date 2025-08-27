"""
Job execution package for NoETL.

This package provides modular action types for executing various tasks
such as HTTP requests, database operations, Python code execution, etc.
"""

from typing import Dict, Any, Optional, Callable
from jinja2 import Environment

from noetl.logger import setup_logger

logger = setup_logger(__name__, include_location=True)

# Import all action executors (strict - no fallbacks)
from .http import execute_http_task
from .python import execute_python_task
from .duckdb import execute_duckdb_task, get_duckdb_connection
from .postgres import execute_postgres_task
from .secrets import execute_secrets_task
from .action import report_event, sql_split

from .action import report_event, sql_split


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
    task_type = task_config.get('type', task_config.get('action', 'unknown'))
    
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
    else:
        raise ValueError(f"Unknown task type '{task_type}'. Available types: http, python, duckdb, postgres, secrets")


def execute_task_resolved(
    task_config: Dict[str, Any],
    task_name: str,
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Optional[Dict[str, Any]] = None,
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute a task with resolved configuration (backwards compatibility).
    """
    return execute_task(task_config, task_name, context, jinja_env, task_with, log_event_callback)


# Export public API
__all__ = [
    'execute_task',
    'execute_task_resolved',
    'execute_http_task',
    'execute_python_task',
    'execute_duckdb_task',
    'execute_postgres_task',
    'execute_secrets_task',
    'report_event',
]
