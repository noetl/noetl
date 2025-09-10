"""
HTTP task executor for NoETL worker plugins.
"""

import json
from typing import Dict, Any, Optional, Callable
from jinja2 import Environment
import requests
from noetl.core.logger import setup_logger

logger = setup_logger(__name__)


def execute_http_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Dict[str, Any] = None,
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute an HTTP task.

    Args:
        task_config: Task configuration
        context: Execution context
        jinja_env: Jinja2 environment
        task_with: Additional parameters
        log_event_callback: Optional event callback

    Returns:
        Task execution result
    """
    try:
        url = task_config.get('url') or task_config.get('endpoint')
        method = task_config.get('method', 'GET').upper()
        headers = task_config.get('headers', {})
        params = task_config.get('params', {})
        data = task_config.get('data') or task_config.get('payload')

        if not url:
            raise ValueError("URL/endpoint is required for HTTP task")

        # Basic HTTP request
        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=data if isinstance(data, dict) else None,
            data=data if not isinstance(data, dict) else None
        )

        return {
            'status': 'success',
            'status_code': response.status_code,
            'response': response.text,
            'headers': dict(response.headers)
        }

    except Exception as e:
        logger.error(f"HTTP task failed: {e}")
        return {
            'status': 'error',
            'error': str(e)
        }
