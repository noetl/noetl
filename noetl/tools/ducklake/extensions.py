"""DuckLake extension management."""

from typing import Any
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def install_ducklake_extensions(conn: Any) -> None:
    """
    Install and load required DuckDB extensions for DuckLake.
    
    Args:
        conn: DuckDB connection
    """
    extensions = [
        "ducklake",   # DuckLake format support
        "postgres",   # Postgres catalog backend
    ]
    
    for ext in extensions:
        try:
            logger.debug(f"Installing extension: {ext}")
            conn.execute(f"INSTALL {ext};")
            conn.execute(f"LOAD {ext};")
            logger.debug(f"Loaded extension: {ext}")
        except Exception as e:
            logger.warning(f"Failed to install/load extension {ext}: {e}")
            # Continue - extension might already be installed


def get_loaded_extensions(conn: Any) -> list:
    """
    Get list of currently loaded extensions.
    
    Args:
        conn: DuckDB connection
        
    Returns:
        List of loaded extension names
    """
    try:
        result = conn.execute("SELECT extension_name FROM duckdb_extensions() WHERE loaded;").fetchall()
        return [row[0] for row in result]
    except Exception as e:
        logger.warning(f"Failed to get loaded extensions: {e}")
        return []
