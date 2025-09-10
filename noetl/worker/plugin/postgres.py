"""
PostgreSQL task executor for NoETL worker plugins.
"""

from typing import Dict, Any, Optional, Callable
from jinja2 import Environment
from noetl.core.logger import setup_logger

logger = setup_logger(__name__)


def execute_postgres_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Dict[str, Any] = None,
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute a PostgreSQL task.

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
        from noetl.core.common import get_db_connection

        sql = task_config.get('sql') or task_config.get('query')
        if not sql:
            raise ValueError("SQL query is required for PostgreSQL task")

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql)
                if cursor.description:
                    result = cursor.fetchall()
                else:
                    result = []

        return {
            'status': 'success',
            'rows': result,
            'row_count': len(result)
        }

    except Exception as e:
        logger.error(f"PostgreSQL task failed: {e}")
        return {
            'status': 'error',
            'error': str(e)
        }
