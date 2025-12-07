"""
NoETL Plugin Registry

This package contains all NoETL plugins that handle different action types
and data processing tasks.

New structure (v2.0+):
- runtime/: Worker infrastructure (execution, events, retry, sql)
- shared/: Cross-plugin services (auth, storage, secrets)
- controller/: Flow control plugins (iterator, workbook, result, playbook)
- tools/: Task implementations (postgres, http, python, duckdb, snowflake, transfer)

Legacy structure (backward compatibility):
- tool/: Old name for runtime/
- auth/, save/, secret/: Old locations for shared services
- Direct plugin imports from root
"""

from typing import Any, Dict

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)

# New imports from refactored structure
# Iterator logic removed - loops are now handled server-side only
from noetl.plugin.controller.playbook import execute_playbook_task
from noetl.plugin.controller.result import process_loop_aggregation_job
from noetl.plugin.controller.workbook import execute_workbook_task
from noetl.plugin.runtime import (
    RetryPolicy,
    execute_task,
    execute_task_resolved,
    report_event,
    report_event_async,
    sql_split,
)
from noetl.plugin.shared.secrets import execute_secrets_task
from noetl.plugin.shared.storage import execute_sink_task

# Import module references for registry
from noetl.plugin.tools import duckdb, http, postgres, python, snowflake
from noetl.plugin.tools.duckdb import execute_duckdb_task, get_duckdb_connection
from noetl.plugin.tools.http import execute_http_task
from noetl.plugin.tools.postgres import execute_postgres_task
from noetl.plugin.tools.python import execute_python_task
from noetl.plugin.tools.snowflake import execute_snowflake_task

# Plugin registry mapping action types to their respective modules
REGISTRY = {
    "http": http,
    "postgres": postgres,
    "duckdb": duckdb,
    "snowflake": snowflake,
    "python": python,
}


# Export public API
__all__ = [
    "execute_task",
    "execute_task_resolved",
    "execute_http_task",
    "execute_python_task",
    "execute_duckdb_task",
    "execute_postgres_task",
    "execute_snowflake_task",
    "execute_secrets_task",
    "execute_playbook_task",
    "execute_workbook_task",
    "execute_sink_task",
    "execute_iterator_task",
    "process_loop_aggregation_job",
    "get_duckdb_connection",
    "report_event",
    "report_event_async",
    "sql_split",
    "RetryPolicy",
    "REGISTRY",
]
