import uuid
import datetime
from typing import Dict
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def execute_secrets_task(task_config: Dict, context: Dict, secret_manager, task_with: Dict, log_event_callback=None) -> Dict:
    """
    Execute a secret's task.

    Args:
        task_config: The task configuration
        context: The context to use for rendering templates
        secret_manager: The SecretManager instance
        task_with: The rendered 'with' parameters dictionary
        log_event_callback: A callback function to log events

    Returns:
        A dictionary of the task result
    """
    def log_event_wrapper(event_type, task_id, task_name, node_type, status, duration,
                          context, result, metadata, parent_event_id):
        if log_event_callback:
            if metadata is None:
                metadata = {}
            metadata['with_params'] = task_with
            return log_event_callback(
                event_type, task_id, task_name, node_type,
                status, duration, context, result,
                metadata, parent_event_id
            )
        return None

    return secret_manager.get_secret(task_config, context, log_event_wrapper)
