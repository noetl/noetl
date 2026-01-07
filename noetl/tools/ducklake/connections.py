"""DuckLake connection management with Postgres-backed catalog."""

import duckdb
from contextlib import contextmanager
from typing import Any
from noetl.tools.ducklake.types import DuckLakeConfig
from noetl.tools.ducklake.errors import CatalogConnectionError
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


@contextmanager
def get_ducklake_connection(config: DuckLakeConfig):
    """
    Context manager for DuckLake connections with Postgres catalog.
    
    This creates a fresh DuckDB connection and attaches it to the DuckLake catalog
    stored in Postgres. The connection can be pooled since the catalog coordination
    happens through Postgres, avoiding file locking issues.
    
    Args:
        config: DuckLake configuration
        
    Yields:
        DuckDB connection with catalog attached
        
    Raises:
        CatalogConnectionError: If connection or catalog attachment fails
    """
    conn = None
    
    try:
        # Create in-memory DuckDB connection
        # Using :memory: since data is managed by DuckLake catalog
        conn = duckdb.connect(":memory:")
        logger.debug("Created in-memory DuckDB connection")
        
        # Configure DuckDB settings
        if config.memory_limit:
            conn.execute(f"SET memory_limit='{config.memory_limit}'")
        if config.threads:
            conn.execute(f"SET threads={config.threads}")
        
        # Install required extensions
        conn.execute("INSTALL ducklake;")
        conn.execute("LOAD ducklake;")
        conn.execute("INSTALL postgres;")
        conn.execute("LOAD postgres;")
        logger.debug("Loaded ducklake and postgres extensions")
        
        # Attach to DuckLake catalog with Postgres metastore
        attach_string = (
            f"ATTACH 'ducklake:postgres:{config.catalog_connection}' "
            f"AS {config.catalog_name} "
            f"(DATA_PATH '{config.data_path}')"
        )
        
        logger.info(f"Attaching to DuckLake catalog: {config.catalog_name}")
        conn.execute(attach_string)
        
        # Use the catalog if configured
        if config.use_catalog:
            conn.execute(f"USE {config.catalog_name};")
            logger.debug(f"Using catalog: {config.catalog_name}")
        
        try:
            yield conn
        finally:
            # Detach catalog gracefully
            try:
                conn.execute(f"DETACH {config.catalog_name};")
                logger.debug(f"Detached catalog: {config.catalog_name}")
            except Exception as e:
                logger.warning(f"Error detaching catalog: {e}")
            
    except Exception as e:
        error_msg = f"Failed to establish DuckLake connection: {str(e)}"
        logger.error(error_msg)
        raise CatalogConnectionError(error_msg) from e
        
    finally:
        # Close connection
        if conn:
            try:
                conn.close()
                logger.debug("DuckDB connection closed")
            except Exception as e:
                logger.warning(f"Error closing DuckDB connection: {e}")


def validate_catalog_connection(catalog_connection: str) -> bool:
    """
    Validate that the Postgres catalog connection string is valid.
    
    Args:
        catalog_connection: Postgres connection string
        
    Returns:
        True if valid, False otherwise
    """
    # Basic validation - should start with postgresql://
    if not catalog_connection.startswith(("postgresql://", "postgres://")):
        logger.error(f"Invalid catalog connection string: {catalog_connection}")
        return False
    
    return True
