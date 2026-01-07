"""
DuckDB connection management for distributed environments.

Connections are NOT pooled to avoid file locking conflicts when using shared storage
(e.g., Kubernetes with ReadWriteMany PVC). Each operation opens a fresh connection
and closes it after use to release the file lock for other workers.
"""

import threading
from contextlib import contextmanager
from typing import Dict, Any

import duckdb

from noetl.core.logger import setup_logger

from .types import ConnectionConfig
from .errors import ConnectionError

logger = setup_logger(__name__, include_location=True)


@contextmanager
def get_duckdb_connection(connection_config: ConnectionConfig):
    """
    Context manager for DuckDB connections with automatic cleanup.
    
    For shared storage environments (K8s with RWX PVC), connections are NOT pooled
    to avoid file locking conflicts between workers. Each operation opens a fresh
    connection and closes it after use.
    
    Args:
        connection_config: Connection configuration
        
    Yields:
        DuckDB connection
        
    Raises:
        ConnectionError: If connection cannot be established
    """
    database_path = connection_config.database_path
    conn = None
    
    logger.debug(f"DUCKDB.GET_CONNECTION: Opening connection to {database_path}")

    try:
        # Create a fresh connection for each operation to avoid lock conflicts in distributed environments
        conn = duckdb.connect(database_path)
        logger.debug(f"DUCKDB.GET_CONNECTION: Connection established to {database_path}")
        
        try:
            yield conn
        finally:
            # CRITICAL: Close connection after use to release file lock for other workers
            if conn:
                try:
                    conn.close()
                    logger.debug(f"DUCKDB.GET_CONNECTION: Connection closed for {database_path}")
                except Exception as e:
                    logger.warning(f"Error closing DuckDB connection: {e}")
            
    except Exception as e:
        raise ConnectionError(f"Failed to establish DuckDB connection to {database_path}: {e}")


def create_standalone_connection(database_path: str):
    """
    Create a standalone DuckDB connection (not pooled).
    
    Args:
        database_path: Path to DuckDB database file
        
    Returns:
        DuckDB connection
        
    Raises:
        ConnectionError: If connection cannot be established
    """
    try:
        logger.info(f"Creating standalone DuckDB connection to {database_path}")
        return duckdb.connect(database_path)
    except Exception as e:
        raise ConnectionError(f"Failed to create standalone connection to {database_path}: {e}")


def close_all_connections():
    """
    No-op function for backward compatibility.
    
    Connections are no longer pooled, so there's nothing to close.
    Each connection is automatically closed after use via context manager.
    """
    logger.debug("close_all_connections called, but connections are not pooled (no-op)")


def get_connection_count() -> int:
    """
    Get the number of active connections.
    
    Returns 0 since connections are no longer pooled.
    
    Returns:
        Number of active connections (always 0)
    """
    return 0