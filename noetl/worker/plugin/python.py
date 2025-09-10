"""
Python task executor for NoETL worker plugins.
"""

import sys
import traceback
from typing import Dict, Any, Optional, Callable
from jinja2 import Environment
from noetl.core.logger import setup_logger

logger = setup_logger(__name__)


def execute_python_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Dict[str, Any] = None,
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute a Python task.

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
        code = task_config.get('code')
        if not code:
            raise ValueError("Code is required for Python task")

        # Create execution namespace
        exec_globals = {
            '__builtins__': __builtins__,
            'context': context,
        }
        exec_locals = {}

        # Execute the Python code
        exec(code, exec_globals, exec_locals)

        return {
            'status': 'success',
            'result': exec_locals.get('result', None),
            'locals': {k: v for k, v in exec_locals.items() if not k.startswith('_')}
        }

    except Exception as e:
        logger.error(f"Python task failed: {e}")
        return {
            'status': 'error',
            'error': str(e),
            'traceback': traceback.format_exc()
        }
