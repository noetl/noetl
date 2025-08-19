from typing import Dict, Any

from noetl.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def execute_secrets_task(task_config: Dict, context: Dict, secret_manager, task_with: Dict, log_event_callback=None) -> Dict:
    """
    Execute a secrets task via SecretManager.
    """
    def log_event_wrapper(event_type, task_id, task_name, node_type, status, duration,
                          context, output_result, metadata, parent_event_id):
        if log_event_callback:
            if metadata is None:
                metadata = {}
            metadata['with_params'] = task_with
            return log_event_callback(
                event_type, task_id, task_name, node_type,
                status, duration, context, output_result,
                metadata, parent_event_id
            )
        return None

    return secret_manager.get_secret(task_config, context, log_event_wrapper)


__all__ = ["execute_secrets_task"]
