"""
Secret manager task executor.

This module provides the main entry point for executing secret manager tasks.
It acts as an adapter between NoETL's task execution framework and external
secret management systems (e.g., Google Cloud Secret Manager, AWS Secrets Manager).
"""

from typing import Dict, Optional, Callable
from noetl.core.logger import setup_logger

from .wrapper import create_log_event_wrapper

logger = setup_logger(__name__, include_location=True)


def execute_secrets_task(
    task_config: Dict,
    context: Dict,
    secret_manager,
    task_with: Dict,
    log_event_callback: Optional[Callable] = None
) -> Dict:
    """
    Execute a secrets task by delegating to the provided secret manager.

    This function serves as a thin adapter that:
    1. Creates a logging wrapper to inject task parameters
    2. Delegates secret retrieval to the external secret manager
    3. Returns the result from the secret manager

    The actual secret retrieval logic is implemented by the secret_manager
    instance, which is typically provided by the worker at runtime and
    configured for a specific secret management provider (Google Cloud,
    AWS, Azure, etc.).

    Args:
        task_config: The task configuration containing:
            - provider: Secret provider ('google', 'aws', etc.)
            - project_id: Project/account identifier
            - secret_name: Name of the secret to retrieve
            - version: Optional secret version (default: 'latest')
        context: The execution context for rendering templates containing:
            - execution_id: The execution identifier
            - workload: Workload variables
            - Other context variables for Jinja2 rendering
        secret_manager: The SecretManager instance that handles actual secret retrieval.
            Must implement a get_secret(task_config, context, log_callback) method.
        task_with: The rendered 'with' parameters dictionary (typically empty for secrets tasks)
        log_event_callback: Optional callback function to log events with signature:
            (event_type, task_id, task_name, task_type, status, duration, context, result, metadata, parent_event_id)

    Returns:
        A dictionary containing the task execution result from the secret manager:
        - id: Task identifier (UUID)
        - status: 'success' or 'error'
        - secret_value: The retrieved secret value (on success)
        - error: Error message (on error)

    Example:
        >>> # Typically called by the worker with a configured secret manager
        >>> result = execute_secrets_task(
        ...     task_config={
        ...         'provider': 'google',
        ...         'project_id': 'my-project',
        ...         'secret_name': 'api-key',
        ...         'version': 'latest'
        ...     },
        ...     context={'execution_id': 'exec-123'},
        ...     secret_manager=google_secret_manager_instance,
        ...     task_with={},
        ...     log_event_callback=my_logger
        ... )
        >>> result['status']
        'success'
        >>> result['secret_value']
        'my-api-key-value'

    Note:
        The secret_manager parameter is injected by the worker at runtime and
        is not part of the plugin's public API. It abstracts the secret
        provider implementation details.
    """
    # Create log event wrapper with task_with parameters
    log_wrapper = create_log_event_wrapper(log_event_callback, task_with)
    
    # Delegate to secret manager for actual retrieval
    return secret_manager.get_secret(task_config, context, log_wrapper)
