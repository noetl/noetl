# Action package API
#
# Note on structure:
# - The monolithic `action.py` remains as the internal implementation and central dispatcher
#   (exports: execute_task, report_event, and concrete execute_* functions). This minimizes risk
#   and avoids a large refactor right now.
# - Thin per-action modules (http.py, python.py, duckdb.py, postgres.py, secrets.py) re-export
#   their respective executors to make code navigation easier and provide a stable public surface.
# - In the future, we can gradually migrate implementations out of action.py into per-action
#   modules without changing the public API of this package.
from .action import execute_task, report_event
from .http import execute_http_task
from .python import execute_python_task
from .duckdb import execute_duckdb_task, get_duckdb_connection
from .postgres import execute_postgres_task
from .secrets import execute_secrets_task

__all__ = [
    "execute_task",
    "report_event",
    "execute_http_task",
    "execute_python_task",
    "execute_duckdb_task",
    "get_duckdb_connection",
    "execute_postgres_task",
    "execute_secrets_task",
]
