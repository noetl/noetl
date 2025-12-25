"""
DuckDB extension management.
"""

from typing import Set, Dict, Any, List

from noetl.core.logger import setup_logger

from .types import AuthType
from .errors import ExtensionError

logger = setup_logger(__name__, include_location=True)


# Map auth types to required extensions
AUTH_TYPE_EXTENSIONS = {
    AuthType.POSTGRES: ['postgres'],
    AuthType.MYSQL: ['mysql'],
    AuthType.SQLITE: [],  # Built-in
    AuthType.SNOWFLAKE: ['snowflake'],
    AuthType.GCS: ['httpfs'],
    AuthType.GCS_HMAC: ['httpfs'],
    AuthType.S3: ['httpfs'],
    AuthType.S3_HMAC: ['httpfs'],
}


def get_required_extensions(resolved_auth_map: Dict[str, Dict[str, Any]]) -> Set[str]:
    """
    Determine required DuckDB extensions based on resolved authentication configuration.
    
    Args:
        resolved_auth_map: Map of auth alias to resolved auth data
        
    Returns:
        Set of extension names to install/load
    """
    extensions = set()
    
    for alias, auth_data in resolved_auth_map.items():
        try:
            auth_type_str = auth_data.get('type', '').lower()
            
            # Map string types to AuthType enum
            auth_type = None
            for auth_enum in AuthType:
                if auth_enum.value == auth_type_str:
                    auth_type = auth_enum
                    break
            
            if auth_type and auth_type in AUTH_TYPE_EXTENSIONS:
                required = AUTH_TYPE_EXTENSIONS[auth_type]
                extensions.update(required)
                logger.debug(f"Auth alias '{alias}' type '{auth_type_str}' requires extensions: {required}")
            else:
                logger.debug(f"Auth alias '{alias}' has unknown type '{auth_type_str}', no extensions added")
                
        except Exception as e:
            logger.warning(f"Failed to determine extensions for auth alias '{alias}': {e}")
    
    if extensions:
        logger.debug(f"Total required extensions: {sorted(extensions)}")
    return extensions


def install_and_load_extensions(connection, extensions: Set[str]) -> List[str]:
    """
    Install and load DuckDB extensions.
    
    Args:
        connection: DuckDB connection
        extensions: Set of extension names to install/load
        
    Returns:
        List of successfully installed extensions
        
    Raises:
        ExtensionError: If critical extensions fail to install
    """
    installed = []
    failed = []
    
    for ext in sorted(extensions):
        if not ext:  # Skip empty extension names
            continue
            
        try:
            logger.debug(f"Installing and loading DuckDB extension: {ext}")
            connection.execute(f"INSTALL {ext};")
            connection.execute(f"LOAD {ext};")
            installed.append(ext)
            logger.debug(f"Successfully installed/loaded extension: {ext}")
            
        except Exception as e:
            failed.append(ext)
            logger.warning(f"Failed to install/load extension '{ext}': {e}")
    
    if installed:
        logger.info(f"Successfully installed DuckDB extensions: {installed}")
    
    if failed:
        # Only raise error for critical extensions
        critical_failed = [ext for ext in failed if ext in {'postgres', 'mysql', 'snowflake', 'httpfs'}]
        if critical_failed:
            raise ExtensionError(f"Failed to install critical extensions: {critical_failed}")
        else:
            logger.warning(f"Non-critical extensions failed to install: {failed}")
    
    return installed


def install_database_extensions(connection, db_type: str) -> bool:
    """
    Install extensions for specific database types.
    
    Args:
        connection: DuckDB connection
        db_type: Database type ('postgres', 'mysql', 'sqlite')
        
    Returns:
        True if successful, False otherwise
    """
    db_type = db_type.lower()
    
    try:
        if db_type == 'postgres':
            logger.info("Installing and loading Postgres extension")
            connection.execute("INSTALL postgres;")
            connection.execute("LOAD postgres;")
        elif db_type == 'mysql':
            logger.info("Installing and loading MySQL extension")
            connection.execute("INSTALL mysql;")
            connection.execute("LOAD mysql;")
        elif db_type == 'snowflake':
            logger.info("Installing and loading Snowflake extension")
            connection.execute("INSTALL snowflake FROM community;")
            connection.execute("LOAD snowflake;")
        elif db_type == 'sqlite':
            logger.info("SQLite support is built-in to DuckDB, no extension needed")
        else:
            logger.info(f"Using custom database type: {db_type}, no specific extension loaded")
            
        return True
        
    except Exception as e:
        logger.error(f"Failed to install extension for database type '{db_type}': {e}")
        return False