"""
DuckDB connection management with connection pooling.
"""

import threading
from contextlib import contextmanager
from typing import Dict, Any

import duckdb

from noetl.core.logger import setup_logger

from .types import ConnectionConfig
from .errors import ConnectionError

logger = setup_logger(__name__, include_location=True)

# Global connection pool and lock
_duckdb_connections: Dict[str, Any] = {}
_connection_lock = threading.Lock()


@contextmanager
def get_duckdb_connection(connection_config: ConnectionConfig):
    """
    Context manager for shared DuckDB connections to maintain attachments.
    
    Args:
        connection_config: Connection configuration
        
    Yields:
        DuckDB connection
        
    Raises:
        ConnectionError: If connection cannot be established
    """
    database_path = connection_config.database_path
    
    logger.debug("=== DUCKDB.GET_CONNECTION: Function entry ===")
    logger.debug(f"DUCKDB.GET_CONNECTION: database_path={database_path}")

    try:
        with _connection_lock:
            if database_path not in _duckdb_connections:
                logger.debug(f"DUCKDB.GET_CONNECTION: Creating new DuckDB connection for {database_path}")
                _duckdb_connections[database_path] = duckdb.connect(database_path)
            else:
                logger.debug(f"DUCKDB.GET_CONNECTION: Reusing existing DuckDB connection for {database_path}")
            conn = _duckdb_connections[database_path]

        try:
            logger.debug("DUCKDB.GET_CONNECTION: Yielding connection")
            yield conn
        finally:
            # Connection stays in pool for reuse
            pass
            
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
    Close all connections in the pool.
    
    Note: This should typically only be called during shutdown or testing.
    """
    with _connection_lock:
        for path, conn in _duckdb_connections.items():
            try:
                conn.close()
                logger.debug(f"Closed DuckDB connection for {path}")
            except Exception as e:
                logger.warning(f"Failed to close connection for {path}: {e}")
        _duckdb_connections.clear()


def get_connection_count() -> int:
    """
    Get the number of active connections in the pool.
    
    Returns:
        Number of active connections
    """
    with _connection_lock:
        return len(_duckdb_connections)