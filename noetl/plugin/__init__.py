"""
NoETL Plugin Registry (Legacy Compatibility Layer)

REFACTORED STRUCTURE:
- noetl/tools/: All tool implementations (python, http, postgres, duckdb, snowflake, transfer)
- noetl/core/auth/: Authentication utilities
- noetl/core/script/: Script loading (GCS, S3, HTTP, file)
- noetl/core/secrets/: Secret management
- noetl/core/storage/: Sink/storage operations
- noetl/core/workflow/: Playbook and workbook execution
- noetl/core/runtime/: Worker infrastructure (events, retry, sql)

This file provides backward compatibility for old imports.
"""

from typing import Any, Dict

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)

# Import from new locations
from noetl.core.workflow.playbook import execute_playbook_task
from noetl.core.workflow.result import process_loop_aggregation_job
from noetl.core.workflow.workbook import execute_workbook_task
from noetl.core.runtime import (
    execute_with_retry,
    execute_task,
    execute_task_resolved,
    report_event,
    report_event_async,
    sql_split,
)
from noetl.core.secrets import execute_secrets_task
from noetl.core.storage import execute_sink_task

# Import tool modules from new location
from noetl.tools import duckdb, http, postgres, python, snowflake, transfer
from noetl.tools.duckdb import execute_duckdb_task, get_duckdb_connection
from noetl.tools.http import execute_http_task
from noetl.tools.postgres import execute_postgres_task
from noetl.tools.python import execute_python_task
from noetl.tools.snowflake import execute_snowflake_task
from noetl.tools.transfer import execute_transfer_action as execute_transfer_task

# Plugin registry mapping action types to their respective modules
REGISTRY = {
    "http": http,
    "postgres": postgres,
    "duckdb": duckdb,
    "snowflake": snowflake,
    "python": python,
    "transfer": transfer,
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
    "execute_transfer_task",
    "execute_secrets_task",
    "execute_playbook_task",
    "execute_workbook_task",
    "execute_sink_task",
    "process_loop_aggregation_job",
    "get_duckdb_connection",
    "report_event",
    "report_event_async",
    "sql_split",
    "REGISTRY",
]
