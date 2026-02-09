"""
DuckDB connection management for distributed environments.

Connections are NOT pooled to avoid file locking conflicts when using shared storage
(e.g., Kubernetes with ReadWriteMany PVC). Each operation opens a fresh connection
and closes it after use to release the file lock for other workers.

Includes retry logic for transient lock conflicts in distributed environments.
"""

import threading
import time
from contextlib import contextmanager
from typing import Dict, Any

import duckdb

from noetl.core.logger import setup_logger

from .types import ConnectionConfig
from .errors import ConnectionError

logger = setup_logger(__name__, include_location=True)

# Retry configuration for lock conflicts
DUCKDB_MAX_RETRIES = 5
DUCKDB_RETRY_DELAY = 0.5  # seconds


@contextmanager
def get_duckdb_connection(connection_config: ConnectionConfig, max_retries: int = DUCKDB_MAX_RETRIES):
    """
    Context manager for DuckDB connections with automatic cleanup and retry logic.

    For shared storage environments (K8s with RWX PVC), connections are NOT pooled
    to avoid file locking conflicts between workers. Each operation opens a fresh
    connection and closes it after use.

    Includes retry logic for transient lock conflicts when multiple workers
    try to access the same DuckDB file simultaneously.

    Args:
        connection_config: Connection configuration
        max_retries: Maximum number of retries for lock conflicts (default: 5)

    Yields:
        DuckDB connection

    Raises:
        ConnectionError: If connection cannot be established after all retries
    """
    database_path = connection_config.database_path
    conn = None
    last_error = None

    logger.debug(f"DUCKDB.GET_CONNECTION: Opening connection to {database_path}")

    for attempt in range(max_retries + 1):
        try:
            # Create a fresh connection for each operation to avoid lock conflicts in distributed environments
            conn = duckdb.connect(database_path)
            logger.debug(f"DUCKDB.GET_CONNECTION: Connection established to {database_path} (attempt {attempt + 1})")

            try:
                yield conn
                return  # Success - exit the retry loop
            finally:
                # CRITICAL: Close connection after use to release file lock for other workers
                if conn:
                    try:
                        conn.close()
                        logger.debug(f"DUCKDB.GET_CONNECTION: Connection closed for {database_path}")
                    except Exception as e:
                        logger.warning(f"Error closing DuckDB connection: {e}")

        except duckdb.IOException as e:
            last_error = e
            # Check if this is a lock conflict error
            if "Could not set lock on file" in str(e) or "Conflicting lock" in str(e):
                if attempt < max_retries:
                    delay = DUCKDB_RETRY_DELAY * (2 ** attempt)  # Exponential backoff
                    logger.warning(
                        f"DUCKDB.GET_CONNECTION: Lock conflict on {database_path}, "
                        f"retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries + 1})"
                    )
                    time.sleep(delay)
                    continue
            # Not a lock conflict or out of retries
            raise ConnectionError(f"Failed to establish DuckDB connection to {database_path}: {e}")
        except Exception as e:
            raise ConnectionError(f"Failed to establish DuckDB connection to {database_path}: {e}")

    # If we get here, we exhausted all retries
    raise ConnectionError(
        f"Failed to establish DuckDB connection to {database_path} after {max_retries + 1} attempts: {last_error}"
    )


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