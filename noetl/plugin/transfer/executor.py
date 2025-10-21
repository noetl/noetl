"""
Transfer Executor - Generic data transfer between systems.

This executor handles data transfers between different database systems using
a source/target pattern. The direction is automatically inferred from the
source and target types.

Supported transfers:
- Snowflake -> PostgreSQL (sf_to_pg)
- PostgreSQL -> Snowflake (pg_to_sf)
- Future: More combinations as needed

Configuration:
    source:
      type: snowflake|postgres|...
      auth: credential reference
      query: SQL query to extract data
    target:
      type: postgres|snowflake|...
      auth: credential reference
      table: target table name (auto-generates INSERT)
      query: custom INSERT/UPSERT/MERGE query (optional)
    chunk_size: number of rows per chunk
"""

from typing import Dict, Any, Optional, Callable
import httpx
from noetl.core.logger import setup_logger
from noetl.plugin.snowflake.transfer import (
    transfer_snowflake_to_postgres,
    transfer_postgres_to_snowflake
)

logger = setup_logger(__name__, include_location=True)


def transfer_http_to_postgres(
    url: str,
    method: str,
    headers: Dict[str, str],
    pg_conn,
    target_table: str,
    mapping: Dict[str, str],
    data_path: str = None,
    chunk_size: int = 1000,
    mode: str = 'insert',
    progress_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Transfer data from HTTP API to PostgreSQL.
    
    Args:
        url: HTTP endpoint URL
        method: HTTP method (GET, POST)
        headers: HTTP headers
        pg_conn: PostgreSQL connection
        target_table: Target table name
        mapping: Column mapping {pg_column: json_field}
        data_path: Path to data in response (e.g., 'data', 'results.items')
        chunk_size: Rows per batch
        mode: insert|upsert
        progress_callback: Progress reporting callback
        
    Returns:
        Dict with rows_transferred, chunks_processed
    """
    logger.info(f"Starting HTTP to PostgreSQL transfer from {url}")
    
    # Fetch data from HTTP endpoint
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.request(method, url, headers=headers)
            response.raise_for_status()
            data = response.json()
    except Exception as e:
        raise ValueError(f"HTTP request failed: {e}")
    
    # Extract data from response using data_path
    if data_path:
        for part in data_path.split('.'):
            if isinstance(data, dict):
                data = data.get(part, [])
            else:
                # If data is already a list and data_path is specified, skip extraction
                break
    
    # Ensure data is a list
    if not isinstance(data, list):
        data = [data]
    
    logger.info(f"Fetched {len(data)} records from HTTP endpoint")
    
    # Build INSERT statement
    columns = list(mapping.keys())
    placeholders = ', '.join(['%s'] * len(columns))
    insert_sql = f"INSERT INTO {target_table} ({', '.join(columns)}) VALUES ({placeholders})"
    
    # Transfer data in chunks
    cursor = pg_conn.cursor()
    rows_transferred = 0
    chunks_processed = 0
    
    try:
        for i in range(0, len(data), chunk_size):
            chunk = data[i:i + chunk_size]
            
            # Extract values according to mapping
            for record in chunk:
                values = []
                for pg_col, json_field in mapping.items():
                    # Support nested field access with dots
                    value = record
                    for field_part in json_field.split('.'):
                        value = value.get(field_part) if isinstance(value, dict) else None
                        if value is None:
                            break
                    values.append(value)
                
                cursor.execute(insert_sql, values)
                rows_transferred += 1
            
            pg_conn.commit()
            chunks_processed += 1
            
            if progress_callback:
                progress_callback(rows_transferred, chunks_processed)
        
        cursor.close()
        
        logger.info(f"Transferred {rows_transferred} rows in {chunks_processed} chunks")
        
        return {
            'rows_transferred': rows_transferred,
            'chunks_processed': chunks_processed,
            'records_fetched': len(data)
        }
        
    except Exception as e:
        pg_conn.rollback()
        cursor.close()
        raise ValueError(f"PostgreSQL insert failed: {e}")


# Supported database types and data sources
SUPPORTED_TYPES = {'snowflake', 'postgres', 'http'}

# Transfer function registry: (source_type, target_type) -> function
TRANSFER_FUNCTIONS = {
    ('snowflake', 'postgres'): transfer_snowflake_to_postgres,
    ('postgres', 'snowflake'): transfer_postgres_to_snowflake,
    ('http', 'postgres'): transfer_http_to_postgres,
}


def _resolve_auth(auth_config: Dict[str, Any], jinja_env, context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resolve authentication configuration to actual credentials.
    
    Uses the worker's resolve_auth to get credentials from the catalog.
    """
    from noetl.worker.auth_resolver import resolve_auth
    
    # Call resolve_auth which handles credential lookup from catalog
    mode_type, resolved_auth_map = resolve_auth(auth_config, jinja_env, context)
    
    # Extract the actual credential data from the resolved auth item
    # resolved_auth_map is a dict of alias -> ResolvedAuthItem
    # We need to extract the .payload from the item
    auth_data = {}
    for alias, auth_item in resolved_auth_map.items():
        if hasattr(auth_item, 'payload'):
            auth_data = auth_item.payload
            break
    
    if not auth_data:
        raise ValueError(f"Failed to resolve credentials")
    
    return auth_data


def _create_connection(db_type: str, auth_data: Dict[str, Any]):
    """Create database connection based on type and auth data."""
    if db_type == 'snowflake':
        import snowflake.connector
        return snowflake.connector.connect(
            account=auth_data.get('sf_account') or auth_data.get('account'),
            user=auth_data.get('sf_user') or auth_data.get('user'),
            password=auth_data.get('sf_password') or auth_data.get('password'),
            warehouse=auth_data.get('sf_warehouse') or auth_data.get('warehouse'),
            database=auth_data.get('sf_database') or auth_data.get('database'),
            schema=auth_data.get('sf_schema') or auth_data.get('schema', 'PUBLIC'),
            role=auth_data.get('sf_role') or auth_data.get('role')
        )
    
    elif db_type == 'postgres':
        import psycopg
        return psycopg.connect(
            host=auth_data.get('pg_host') or auth_data.get('db_host') or auth_data.get('host', 'localhost'),
            port=int(auth_data.get('pg_port') or auth_data.get('db_port') or auth_data.get('port', 5432)),
            dbname=auth_data.get('pg_database') or auth_data.get('db_name') or auth_data.get('database'),
            user=auth_data.get('pg_user') or auth_data.get('db_user') or auth_data.get('user'),
            password=auth_data.get('pg_password') or auth_data.get('db_password') or auth_data.get('password')
        )
    
    else:
        raise ValueError(f"Connection creation not implemented for: {db_type}")


def _close_connection(db_type: str, conn):
    """Close database connection."""
    try:
        if conn:
            conn.close()
            logger.debug(f"Closed {db_type} connection")
    except Exception as e:
        logger.warning(f"Error closing {db_type} connection: {e}")


def _report_event(log_event_callback, event_type: str, status: str, context: Dict[str, Any]):
    """Report event if callback is provided."""
    if log_event_callback:
        try:
            log_event_callback(
                event_type=event_type,
                status=status,
                context=context
            )
        except Exception as e:
            logger.warning(f"Error reporting event: {e}")


def execute_transfer_action(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env=None,
    task_with: Dict[str, Any] = None,
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute data transfer between source and target systems.
    
    This is the main entry point for the generic transfer action type.
    Direction is automatically inferred from source.type and target.type.
    
    Args:
        task_config: Task configuration with source, target, chunk_size
        context: Execution context with workload, credentials, etc.
        jinja_env: Jinja2 environment (not used, for signature compatibility)
        task_with: Additional task parameters (not used, for signature compatibility)
        log_event_callback: Callback for logging events
        
    Returns:
        Transfer result with rows_transferred, chunks_processed, etc.
        
    Example:
        task_config = {
            'source': {
                'type': 'snowflake',
                'auth': {'source': 'credential', 'key': 'sf_cred'},
                'query': 'SELECT * FROM source_table'
            },
            'target': {
                'type': 'postgres',
                'auth': {'source': 'credential', 'key': 'pg_cred'},
                'table': 'target_table'
            },
            'chunk_size': 1000
        }
    """
    task_name = task_config.get('name', 'transfer')
    
    try:
        logger.info(f"Starting data transfer action: {task_name}")
        
        # Extract and validate source configuration
        source_config = task_config.get('source', {})
        if not source_config:
            raise ValueError("'source' configuration is required")
        
        source_type = source_config.get('type', '').lower()
        source_query = source_config.get('query')
        source_auth = source_config.get('auth')
        source_url = source_config.get('url')
        source_method = source_config.get('method', 'GET')
        source_headers = source_config.get('headers', {})
        source_data_path = source_config.get('data_path')
        
        if not source_type:
            raise ValueError("source.type is required")
        if source_type not in SUPPORTED_TYPES:
            raise ValueError(f"Unsupported source type: {source_type}. Supported: {SUPPORTED_TYPES}")
        
        # Validate source-specific requirements
        if source_type == 'http':
            if not source_url:
                raise ValueError("source.url is required for HTTP source")
        else:
            # Database sources need query and auth
            if not source_query:
                raise ValueError("source.query is required")
            if not source_auth:
                raise ValueError("source.auth is required")
        
        # Extract and validate target configuration
        target_config = task_config.get('target', {})
        if not target_config:
            raise ValueError("'target' configuration is required")
        
        target_type = target_config.get('type', '').lower()
        target_table = target_config.get('table')
        target_query = target_config.get('query')
        target_auth = target_config.get('auth')
        target_mapping = target_config.get('mapping', {})
        
        if not target_type:
            raise ValueError("target.type is required")
        if target_type not in SUPPORTED_TYPES:
            raise ValueError(f"Unsupported target type: {target_type}. Supported: {SUPPORTED_TYPES}")
        if not target_table and not target_query:
            raise ValueError("Either target.table or target.query is required")
        if not target_auth:
            raise ValueError("target.auth is required")
        
        # Extract optional parameters
        chunk_size = int(task_config.get('chunk_size', 1000))
        mode = task_config.get('mode', 'append')
        
        # Determine transfer direction and function
        direction_key = (source_type, target_type)
        transfer_function = TRANSFER_FUNCTIONS.get(direction_key)
        
        if not transfer_function:
            raise ValueError(
                f"Unsupported transfer direction: {source_type} -> {target_type}. "
                f"Supported combinations: {list(TRANSFER_FUNCTIONS.keys())}"
            )
        
        direction_name = f"{source_type}_to_{target_type}"
        
        logger.info(f"Transfer direction: {source_type} -> {target_type} ({direction_name})")
        if source_query:
            logger.info(f"Source query: {source_query[:100]}...")
        if target_table:
            logger.info(f"Target table: {target_table}")
        if target_query:
            logger.info(f"Target query: {target_query[:100]}...")
        logger.info(f"Chunk size: {chunk_size}, Mode: {mode if not target_query else 'custom'}")
        
        # Resolve authentication and create connections for database sources/targets
        source_conn = None
        target_conn = None
        
        if source_type != 'http':
            logger.info(f"Resolving authentication for source ({source_type})...")
            source_auth_data = _resolve_auth(source_auth, jinja_env, context)
            source_conn = _create_connection(source_type, source_auth_data)
        
        if target_type != 'http':
            logger.info(f"Resolving authentication for target ({target_type})...")
            target_auth_data = _resolve_auth(target_auth, jinja_env, context)
            target_conn = _create_connection(target_type, target_auth_data)
        
        # Progress callback for reporting
        def progress_callback(rows_so_far: int, chunk_num: int):
            logger.info(f"Transferred {rows_so_far} rows in {chunk_num} chunks")
            _report_event(
                log_event_callback,
                event_type='action_progress',
                status='RUNNING',
                context={
                    'rows_transferred': rows_so_far,
                    'chunks_processed': chunk_num,
                    'direction': direction_name
                }
            )
        
        # Execute transfer based on direction
        logger.info(f"Starting {direction_name} transfer...")
        
        if direction_key == ('http', 'postgres'):
            result = transfer_function(
                url=source_url,
                method=source_method,
                headers=source_headers,
                pg_conn=target_conn,
                target_table=target_table,
                mapping=target_mapping,
                data_path=source_data_path,
                chunk_size=chunk_size,
                mode=mode,
                progress_callback=progress_callback
            )
        elif direction_key == ('snowflake', 'postgres'):
            result = transfer_function(
                sf_conn=source_conn,
                pg_conn=target_conn,
                source_query=source_query,
                target_table=target_table,
                target_query=target_query,
                chunk_size=chunk_size,
                mode=mode,
                progress_callback=progress_callback
            )
        elif direction_key == ('postgres', 'snowflake'):
            result = transfer_function(
                pg_conn=source_conn,
                sf_conn=target_conn,
                source_query=source_query,
                target_table=target_table,
                target_query=target_query,
                chunk_size=chunk_size,
                mode=mode,
                progress_callback=progress_callback
            )
        else:
            raise ValueError(f"Transfer function not implemented for {direction_key}")
        
        # Close connections (if they exist)
        if source_conn:
            _close_connection(source_type, source_conn)
        if target_conn:
            _close_connection(target_type, target_conn)
        
        logger.info(f"Transfer completed: {result}")
        
        return {
            'status': 'success',
            'data': {
                'direction': direction_name,
                'source_type': source_type,
                'target_type': target_type,
                'mode': mode if not target_query else 'custom',
                **result
            }
        }
        
    except Exception as e:
        error_msg = f"Transfer failed: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise ValueError(error_msg) from e
