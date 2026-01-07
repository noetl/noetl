"""
DuckLake plugin for NoETL - Distributed DuckDB with shared metastore.

This module provides DuckLake task execution capabilities with support for:
- PostgreSQL-backed metastore/catalog
- Multi-worker concurrent access without file locking
- ACID transactions and snapshots
- Time-travel queries
- Schema evolution

DuckLake uses a Postgres database to store catalog metadata, allowing multiple
DuckDB workers to safely read/write to the same tables without file locking conflicts.

Public API:
- execute_ducklake_task: Main task execution function
"""

import traceback
from typing import Dict, Any, Optional, Callable

from noetl.core.logger import setup_logger
from noetl.tools.ducklake.config import create_ducklake_config
from noetl.tools.ducklake.connections import get_ducklake_connection
from noetl.tools.ducklake.extensions import install_ducklake_extensions
from noetl.tools.ducklake.sql import render_commands, execute_sql_commands, serialize_results
from noetl.tools.ducklake.types import JinjaEnvironment, ContextDict, LogEventCallback
from noetl.tools.ducklake.errors import DuckLakePluginError

logger = setup_logger(__name__, include_location=True)


def execute_ducklake_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: JinjaEnvironment,
    task_with: Dict[str, Any],
    log_event_callback: LogEventCallback = None
) -> Dict[str, Any]:
    """
    Execute a DuckLake task with PostgreSQL metastore.

    Args:
        task_config: The task configuration with required fields:
            - catalog_connection: Postgres connection string for metastore
            - catalog_name: Name of the DuckLake catalog
            - data_path: Path to store data files (e.g., '/opt/noetl/data/ducklake')
            - command OR commands: SQL command(s) to execute
        context: The context for rendering templates
        jinja_env: The Jinja2 environment for template rendering
        task_with: The task 'with' block for credentials/configuration
        log_event_callback: Optional callback for logging execution events

    Returns:
        Dict containing:
            - status: 'ok' or 'error'
            - result: Query results (for SELECT) or affected rows
            - error: Error message (if status='error')
            - catalog_info: DuckLake catalog metadata

    Example task configuration:
        - step: create_table
          tool: ducklake
          catalog_connection: "postgresql://noetl:noetl@postgres.noetl.svc.cluster.local:5432/ducklake_catalog"
          catalog_name: "my_catalog"
          data_path: "/opt/noetl/data/ducklake"
          command: |
            CREATE TABLE users (
              id INTEGER PRIMARY KEY,
              name VARCHAR,
              created_at TIMESTAMP
            );
            INSERT INTO users VALUES (1, 'Alice', NOW());
    """
    try:
        logger.info("DuckLake task execution started")

        # Create configuration
        ducklake_config = create_ducklake_config(task_config, context, jinja_env, task_with)
        
        logger.info(
            f"DuckLake config: catalog={ducklake_config.catalog_name}, "
            f"data_path={ducklake_config.data_path}"
        )

        # Get connection with catalog attached
        with get_ducklake_connection(ducklake_config) as conn:
            
            # Install required extensions
            install_ducklake_extensions(conn)
            
            # Render SQL commands
            commands = render_commands(ducklake_config, context, jinja_env)
            logger.info(f"Executing {len(commands)} SQL command(s)")
            
            # Execute commands
            results = execute_sql_commands(conn, commands, log_event_callback)
            
            # Serialize results
            serialized = serialize_results(results)
            
            # Get catalog info
            catalog_info = _get_catalog_info(conn, ducklake_config.catalog_name)
            
            logger.info("DuckLake task execution completed successfully")
            
            return {
                "status": "ok",
                "result": serialized,
                "catalog_info": catalog_info
            }

    except Exception as e:
        error_msg = f"DuckLake task execution failed: {str(e)}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        
        return {
            "status": "error",
            "error": error_msg,
            "traceback": traceback.format_exc()
        }


def _get_catalog_info(conn, catalog_name: str) -> Dict[str, Any]:
    """Get information about the DuckLake catalog."""
    from decimal import Decimal
    from datetime import datetime, date, time
    
    def serialize_value(value):
        """Serialize a single value for JSON compatibility."""
        if isinstance(value, Decimal):
            return float(value)
        elif isinstance(value, (datetime, date, time)):
            return value.isoformat()
        elif isinstance(value, (list, tuple)):
            return [serialize_value(v) for v in value]
        elif isinstance(value, dict):
            return {k: serialize_value(v) for k, v in value.items()}
        else:
            return value
    
    try:
        # Get snapshot info
        snapshots = conn.execute(
            f"SELECT * FROM ducklake_snapshots('{catalog_name}') ORDER BY snapshot_id DESC LIMIT 5"
        ).fetchall()
        
        # Get table info
        tables = conn.execute(
            f"SELECT * FROM ducklake_table_info('{catalog_name}')"
        ).fetchall()
        
        # Serialize snapshot data
        latest_snapshot = None
        if snapshots:
            snapshot_cols = [col[0] for col in conn.description]
            latest_snapshot_raw = dict(zip(snapshot_cols, snapshots[0]))
            latest_snapshot = {k: serialize_value(v) for k, v in latest_snapshot_raw.items()}
        
        # Serialize table data
        serialized_tables = []
        if tables:
            table_cols = [col[0] for col in conn.description]
            for row in tables:
                table_dict = dict(zip(table_cols, row))
                serialized_tables.append({k: serialize_value(v) for k, v in table_dict.items()})
        
        return {
            "catalog_name": catalog_name,
            "snapshot_count": len(snapshots),
            "latest_snapshot": latest_snapshot,
            "table_count": len(tables),
            "tables": serialized_tables
        }
    except Exception as e:
        logger.warning(f"Failed to get catalog info: {e}")
        return {
            "catalog_name": catalog_name,
            "error": str(e)
        }


__all__ = ["execute_ducklake_task"]
