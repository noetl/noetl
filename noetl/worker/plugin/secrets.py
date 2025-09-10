"""
Secrets task executor for NoETL worker plugins.
"""

from typing import Dict, Any, Optional, Callable
from jinja2 import Environment
from noetl.core.logger import setup_logger

logger = setup_logger(__name__)


def execute_secrets_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    secret_manager: Any = None,
    task_with: Dict[str, Any] = None,
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute a secrets task.

    Args:
        task_config: Task configuration
        context: Execution context
        secret_manager: Secret manager instance
        task_with: Additional parameters
        log_event_callback: Optional event callback

    Returns:
        Task execution result
    """
    try:
        secret_name = task_config.get('secret_name') or task_config.get('name')
        if not secret_name:
            raise ValueError("Secret name is required for secrets task")

        if not secret_manager:
            raise ValueError("Secret manager not available")

        # Get secret value
        secret_value = secret_manager.get_secret(secret_name)

        return {
            'status': 'success',
            'secret_name': secret_name,
            'has_value': bool(secret_value)
        }

    except Exception as e:
        logger.error(f"Secrets task failed: {e}")
        return {
            'status': 'error',
            'error': str(e)
        }
