"""
NoETL tool implementations for workflow execution.

This package contains all action executors moved from plugin/tools/:

- python: Python code execution
- http: HTTP request execution
- postgres: PostgreSQL task execution
- duckdb: DuckDB query execution
- ducklake: DuckLake distributed DuckDB with Postgres metastore
- snowflake: Snowflake task execution
- transfer: Data transfer operations
- container: Container execution
- artifact: Result artifact storage (get/put from S3, GCS, filesystem)
- nats: NATS JetStream, K/V Store, and Object Store operations
"""

# Import tool modules
from noetl.tools import (
    python,
    http,
    postgres,
    duckdb,
    ducklake,
    snowflake,
    transfer,
    container,
    gcs,
    artifact,
    nats,
)
from noetl.tools.transfer import snowflake_transfer

# Import executors
from noetl.tools.python import execute_python_task, execute_python_task_async
from noetl.tools.http import execute_http_task
from noetl.tools.postgres import execute_postgres_task
from noetl.tools.duckdb import execute_duckdb_task
from noetl.tools.ducklake import execute_ducklake_task
from noetl.tools.snowflake import execute_snowflake_task, execute_snowflake_transfer_task
from noetl.tools.transfer import execute_transfer_action
from noetl.tools.transfer.snowflake_transfer import execute_snowflake_transfer_action
from noetl.tools.container import execute_container_task
from noetl.tools.gcs import execute_gcs_task
from noetl.tools.artifact import execute_artifact_task, execute_artifact_get, execute_artifact_put
from noetl.tools.nats import execute_nats_task

# Tool registry for dynamic lookup
REGISTRY = {
    "python": python,
    "http": http,
    "postgres": postgres,
    "duckdb": duckdb,
    "ducklake": ducklake,
    "snowflake": snowflake,
    "transfer": transfer,
    "snowflake_transfer": snowflake_transfer,
    "container": container,
    "gcs": gcs,
    "artifact": artifact,
    "nats": nats,
}

__all__ = [
    # Modules
    "python",
    "http",
    "postgres",
    "duckdb",
    "ducklake",
    "snowflake",
    "transfer",
    "snowflake_transfer",
    "container",
    "gcs",
    "artifact",
    "nats",
    # Executors
    "execute_python_task",
    "execute_python_task_async",
    "execute_http_task",
    "execute_postgres_task",
    "execute_duckdb_task",
    "execute_ducklake_task",
    "execute_snowflake_task",
    "execute_snowflake_transfer_task",
    "execute_transfer_action",
    "execute_snowflake_transfer_action",
    "execute_container_task",
    "execute_gcs_task",
    "execute_artifact_task",
    "execute_artifact_get",
    "execute_artifact_put",
    "execute_nats_task",
    # Registry
    "REGISTRY",
]

