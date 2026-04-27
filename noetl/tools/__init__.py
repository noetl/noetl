"""NoETL tool implementations for workflow execution.

This package intentionally keeps imports lazy. Tool modules may import worker
helpers, and workers import tool executors; eager imports here create circular
initialization paths.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_MODULES = {
    "python": "noetl.tools.python",
    "http": "noetl.tools.http",
    "postgres": "noetl.tools.postgres",
    "duckdb": "noetl.tools.duckdb",
    "ducklake": "noetl.tools.ducklake",
    "snowflake": "noetl.tools.snowflake",
    "transfer": "noetl.tools.transfer",
    "snowflake_transfer": "noetl.tools.transfer.snowflake_transfer",
    "container": "noetl.tools.container",
    "gcs": "noetl.tools.gcs",
    "artifact": "noetl.tools.artifact",
    "nats": "noetl.tools.nats",
    "agent": "noetl.tools.agent",
    "mcp": "noetl.tools.mcp",
}

_EXECUTORS = {
    "execute_python_task": ("noetl.tools.python", "execute_python_task"),
    "execute_python_task_async": ("noetl.tools.python", "execute_python_task_async"),
    "execute_http_task": ("noetl.tools.http", "execute_http_task"),
    "execute_postgres_task": ("noetl.tools.postgres", "execute_postgres_task"),
    "execute_postgres_task_async": ("noetl.tools.postgres", "execute_postgres_task_async"),
    "execute_duckdb_task": ("noetl.tools.duckdb", "execute_duckdb_task"),
    "execute_ducklake_task": ("noetl.tools.ducklake", "execute_ducklake_task"),
    "execute_snowflake_task": ("noetl.tools.snowflake", "execute_snowflake_task"),
    "execute_snowflake_transfer_task": ("noetl.tools.snowflake", "execute_snowflake_transfer_task"),
    "execute_transfer_action": ("noetl.tools.transfer", "execute_transfer_action"),
    "execute_snowflake_transfer_action": (
        "noetl.tools.transfer.snowflake_transfer",
        "execute_snowflake_transfer_action",
    ),
    "execute_container_task": ("noetl.tools.container", "execute_container_task"),
    "execute_gcs_task": ("noetl.tools.gcs", "execute_gcs_task"),
    "execute_artifact_task": ("noetl.tools.artifact", "execute_artifact_task"),
    "execute_artifact_get": ("noetl.tools.artifact", "execute_artifact_get"),
    "execute_artifact_put": ("noetl.tools.artifact", "execute_artifact_put"),
    "execute_nats_task": ("noetl.tools.nats", "execute_nats_task"),
    "execute_agent_task": ("noetl.tools.agent", "execute_agent_task"),
    "execute_mcp_task": ("noetl.tools.mcp", "execute_mcp_task"),
    "execute_task": ("noetl.core.runtime.execution", "execute_task"),
    "execute_task_resolved": ("noetl.core.runtime.execution", "execute_task_resolved"),
}

REGISTRY = {name: name for name in _MODULES}


def __getattr__(name: str) -> Any:
    if name in _MODULES:
        module = import_module(_MODULES[name])
        globals()[name] = module
        return module
    if name in _EXECUTORS:
        module_name, attr = _EXECUTORS[name]
        value = getattr(import_module(module_name), attr)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'noetl.tools' has no attribute {name!r}")


__all__ = [*_MODULES.keys(), *_EXECUTORS.keys(), "REGISTRY"]
