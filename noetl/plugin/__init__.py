"""
NoETL Plugin Registry

This package contains all NoETL plugins that handle different action types
and data processing tasks.
"""

from typing import Dict, Any

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)

# Import all action executors (strict - no fallbacks)
from .http import execute_http_task
from .python import execute_python_task
from .duckdb import execute_duckdb_task, get_duckdb_connection
from .postgres import execute_postgres_task
from .secrets import execute_secrets_task
from .playbook import execute_playbook_task
from .workbook import execute_workbook_task
from .save import execute_save_task
from .iterator import execute_loop_task as execute_iterator_task

# Import MCP-compliant tools
from .tool import execute_task, execute_task_resolved, report_event, sql_split


# Plugin registry mapping action types to their respective modules
REGISTRY = {
    "http": http,
    "postgres": postgres,
    "duckdb": duckdb,
    "python": python,
}


# Export public API
__all__ = [
    'execute_task',
    'execute_task_resolved',
    'execute_http_task',
    'execute_python_task',
    'execute_duckdb_task',
    'execute_postgres_task',
    'execute_secrets_task',
    'execute_playbook_task',
    'execute_workbook_task',
    'execute_save_task',
    'execute_iterator_task',
    'get_duckdb_connection',
    'report_event',
    'sql_split',
    'REGISTRY',
]