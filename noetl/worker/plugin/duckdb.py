"""
DuckDB task executor for NoETL worker plugins.
"""

from typing import Dict, Any, Optional, Callable
from jinja2 import Environment
from noetl.core.logger import setup_logger

logger = setup_logger(__name__)


def get_duckdb_connection():
    """Get a DuckDB connection."""
    try:
        import duckdb
        return duckdb.connect()
    except ImportError:
        raise ImportError("DuckDB is not installed. Install with: pip install duckdb")


def execute_duckdb_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Dict[str, Any] = None,
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute a DuckDB task.

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
        sql = task_config.get('sql') or task_config.get('query')
        if not sql:
            raise ValueError("SQL query is required for DuckDB task")

        conn = get_duckdb_connection()
        result = conn.execute(sql).fetchall()

        return {
            'status': 'success',
            'rows': result,
            'row_count': len(result)
        }

    except Exception as e:
        logger.error(f"DuckDB task failed: {e}")
        return {
            'status': 'error',
            'error': str(e)
        }
