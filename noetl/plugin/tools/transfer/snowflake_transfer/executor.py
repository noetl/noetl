"""
Snowflake Transfer action executor.

Handles bidirectional data transfer between Snowflake and PostgreSQL databases
with chunked streaming support.
"""

import uuid
import datetime
from typing import Dict, Optional, Callable, Any
from jinja2 import Environment

from noetl.core.logger import setup_logger
from noetl.core.common import make_serializable
from noetl.plugin.tools.snowflake.transfer import transfer_snowflake_to_postgres, transfer_postgres_to_snowflake
from noetl.plugin.tools.snowflake.execution import connect_to_snowflake
import psycopg

logger = setup_logger(__name__, include_location=True)


def execute_snowflake_transfer_action(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Dict[str, Any],
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute a Snowflake transfer action.
    
    This action type enables efficient data movement between Snowflake and PostgreSQL:
    - Bidirectional transfer (sf_to_pg or pg_to_sf)
    - Chunked streaming for memory efficiency
    - Configurable transfer modes (append, replace, upsert/merge)
    - Progress tracking through callbacks
    
    Task Configuration:
        direction: 'sf_to_pg' or 'pg_to_sf' (required)
        source:
            query: SQL query to fetch data from source (required)
        target:
            table: Target table name, can be schema-qualified (required)
        chunk_size: Number of rows per chunk (optional, default: 1000)
        mode: Transfer mode - 'append', 'replace', 'upsert' (optional, default: 'append')
        credentials:
            sf: { key: "snowflake_credential_name" } (required)
            pg: { key: "postgres_credential_name" } (required)
    
    Task With Parameters (resolved from credentials):
        Snowflake credentials:
            sf_account, sf_user, sf_password, sf_warehouse, sf_database, sf_schema, sf_role
        PostgreSQL credentials:
            pg_host, pg_port, pg_user, pg_password, pg_database
    
    Args:
        task_config: Task configuration dictionary
        context: Execution context with execution_id, etc.
        jinja_env: Jinja2 environment for template rendering
        task_with: Rendered parameters from credentials
        log_event_callback: Optional callback for event logging
        
    Returns:
        Dictionary with transfer results:
        {
            'id': str,
            'status': 'success' or 'error',
            'data': {
                'rows_transferred': int,
                'chunks_processed': int,
                'target_table': str,
                'direction': str
            },
            'error': str (if error occurred)
        }
        
    Example:
        >>> result = execute_snowflake_transfer_action(
        ...     task_config={
        ...         'direction': 'sf_to_pg',
        ...         'source': {'query': 'SELECT * FROM my_table'},
        ...         'target': {'table': 'public.target_table'},
        ...         'chunk_size': 5000,
        ...         'mode': 'append'
        ...     },
        ...     context={'execution_id': 'exec-123'},
        ...     jinja_env=Environment(),
        ...     task_with={
        ...         'sf_account': 'xy12345.us-east-1',
        ...         'sf_user': 'user',
        ...         'sf_password': 'pass',
        ...         'pg_host': 'localhost',
        ...         'pg_user': 'postgres',
        ...         'pg_password': 'pass',
        ...         'pg_database': 'mydb'
        ...     }
        ... )
        >>> result['status']
        'success'
    """
    task_id = str(uuid.uuid4())
    task_name = task_config.get('name', 'snowflake_transfer')
    start_time = datetime.datetime.now()
    
    try:
        logger.info(f"Starting Snowflake transfer action: {task_name}")
        
        # Extract transfer configuration
        direction = task_config.get('direction')
        source_config = task_config.get('source', {})
        target_config = task_config.get('target', {})
        chunk_size = int(task_config.get('chunk_size', 1000))  # Convert to int
        mode = task_config.get('mode', 'append')
        
        # Validate required parameters
        if not direction or direction not in ['sf_to_pg', 'pg_to_sf']:
            logger.error(f"Invalid direction value: {direction!r}")
            raise ValueError("'direction' must be 'sf_to_pg' or 'pg_to_sf'")
        
        source_query = source_config.get('query')
        if not source_query:
            raise ValueError("source.query is required")
        
        # Target can be either table or query (custom INSERT/UPSERT)
        target_table = target_config.get('table')
        target_query = target_config.get('query')
        
        if not target_table and not target_query:
            raise ValueError("Either target.table or target.query is required")
        
        logger.info(f"Transfer direction: {direction}")
        logger.info(f"Source query: {source_query}")
        if target_table:
            logger.info(f"Target table: {target_table}")
        if target_query:
            logger.info(f"Target query: {target_query[:100]}...")  # Log first 100 chars
        logger.info(f"Chunk size: {chunk_size}, Mode: {mode if not target_query else 'custom'}")
        
        # Resolve credentials from auth configuration
        logger.info("Step 1: Getting auth config from task_config")
        auth_config = task_config.get('auth', {})
        logger.info(f"Step 2: Auth config retrieved: {bool(auth_config)}")
        
        if not auth_config:
            raise ValueError("auth configuration is required for snowflake_transfer")
        
        logger.info(f"Step 3: Auth config content: {auth_config}")
        
        # Use worker's auth resolver to fetch credentials
        logger.info("Step 4: Importing resolve_auth")
        from noetl.worker.auth_resolver import resolve_auth
        
        logger.info("Step 5: Calling resolve_auth")
        mode_type, resolved_auth_map = resolve_auth(auth_config, jinja_env, context)
        
        logger.info(f"Step 6: Resolved auth mode: {mode_type}, aliases: {list(resolved_auth_map.keys())}")
        
        # Get Snowflake and PostgreSQL credentials (following duckdb pattern)
        sf_auth_item = resolved_auth_map.get('sf')
        pg_auth_item = resolved_auth_map.get('pg')
        
        if not sf_auth_item:
            raise ValueError("Snowflake credential 'sf' not found in resolved auth")
        if not pg_auth_item:
            raise ValueError("PostgreSQL credential 'pg' not found in resolved auth")
        
        # Access payload attribute from ResolvedAuthItem (same as duckdb/auth/secrets.py line 67)
        sf_auth_data = sf_auth_item.payload
        pg_auth_data = pg_auth_item.payload
        
        logger.info(f"SF auth payload keys: {list(sf_auth_data.keys())}")
        logger.info(f"PG auth payload keys: {list(pg_auth_data.keys())}")
        
        # Extract Snowflake connection parameters (use sf_ prefix as stored in credential)
        sf_account = sf_auth_data.get('sf_account') or sf_auth_data.get('account')
        sf_user = sf_auth_data.get('sf_user') or sf_auth_data.get('user') or sf_auth_data.get('username')
        sf_password = sf_auth_data.get('sf_password') or sf_auth_data.get('password')
        sf_warehouse = sf_auth_data.get('sf_warehouse') or sf_auth_data.get('warehouse', 'COMPUTE_WH')
        sf_database = sf_auth_data.get('sf_database') or sf_auth_data.get('database')
        sf_schema = sf_auth_data.get('sf_schema') or sf_auth_data.get('schema', 'PUBLIC')
        sf_role = sf_auth_data.get('sf_role') or sf_auth_data.get('role')
        
        # Extract PostgreSQL connection parameters (use db_ prefix as stored in credential)
        pg_host = pg_auth_data.get('db_host') or pg_auth_data.get('host', 'localhost')
        pg_port = int(pg_auth_data.get('db_port') or pg_auth_data.get('port', 5432))  # Convert to int
        pg_user = pg_auth_data.get('db_user') or pg_auth_data.get('user') or pg_auth_data.get('username')
        pg_password = pg_auth_data.get('db_password') or pg_auth_data.get('password')
        pg_database = pg_auth_data.get('db_name') or pg_auth_data.get('database')
        
        # Validate credentials
        if not all([sf_account, sf_user, sf_password]):
            logger.error(f"Snowflake auth data keys: {list(sf_auth_data.keys())}")
            logger.error(f"Snowflake credentials extracted: account={sf_account}, user={sf_user}, password={'***' if sf_password else None}")
            raise ValueError("Snowflake credentials (account, user, password) are required")
        
        if not all([pg_user, pg_password, pg_database]):
            logger.error(f"PostgreSQL auth data keys: {list(pg_auth_data.keys())}")
            logger.error(f"PostgreSQL credentials extracted: user={pg_user}, database={pg_database}, password={'***' if pg_password else None}")
            raise ValueError("PostgreSQL credentials (user, password, database) are required")
        
        # Log task start event
        event_id = None
        if log_event_callback:
            event_id = log_event_callback(
                'action_started',
                task_id,
                task_name,
                'snowflake_transfer',
                'STARTED',
                0,
                context,
                None,
                {
                    'direction': direction,
                    'target_table': target_table,
                    'chunk_size': chunk_size,
                    'mode': mode
                },
                None
            )
        
        # Connect to Snowflake
        logger.info("Connecting to Snowflake...")
        sf_conn = connect_to_snowflake(
            account=sf_account,
            user=sf_user,
            password=sf_password,
            warehouse=sf_warehouse,
            database=sf_database,
            schema=sf_schema,
            role=sf_role
        )
        
        # Connect to PostgreSQL
        logger.info("Connecting to PostgreSQL...")
        pg_conn_string = f"host={pg_host} port={pg_port} dbname={pg_database} user={pg_user} password={pg_password}"
        pg_conn = psycopg.connect(pg_conn_string)
        
        # Define progress callback
        def progress_cb(rows, total):
            logger.info(f"Transfer progress: {rows} rows transferred")
            if log_event_callback:
                log_event_callback(
                    'transfer_progress',
                    task_id,
                    task_name,
                    'snowflake_transfer',
                    'RUNNING',
                    0,
                    context,
                    {'rows_transferred': rows},
                    None,
                    event_id
                )
        
        # Execute transfer based on direction
        if direction == 'sf_to_pg':
            logger.info("Executing Snowflake → PostgreSQL transfer")
            result = transfer_snowflake_to_postgres(
                sf_conn=sf_conn,
                pg_conn=pg_conn,
                source_query=source_query,
                target_table=target_table,
                target_query=target_query,
                chunk_size=chunk_size,
                mode=mode,
                progress_callback=progress_cb
            )
        else:  # pg_to_sf
            logger.info("Executing PostgreSQL → Snowflake transfer")
            result = transfer_postgres_to_snowflake(
                pg_conn=pg_conn,
                sf_conn=sf_conn,
                source_query=source_query,
                target_table=target_table,
                target_query=target_query,
                chunk_size=chunk_size,
                mode=mode,
                progress_callback=progress_cb
            )
        
        # Close connections
        sf_conn.close()
        pg_conn.close()
        
        # Calculate duration
        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        # Check transfer result
        if result.get('status') == 'error':
            error_msg = result.get('error', 'Unknown transfer error')
            logger.error(f"Transfer failed: {error_msg}")
            
            if log_event_callback:
                log_event_callback(
                    'action_failed',
                    task_id,
                    task_name,
                    'snowflake_transfer',
                    'FAILED',
                    duration,
                    context,
                    None,
                    {'error': error_msg},
                    event_id
                )
            
            return {
                'id': task_id,
                'status': 'error',
                'error': error_msg,
                'data': make_serializable(result)
            }
        
        # Success
        logger.info(f"Transfer completed successfully: {result.get('rows_transferred')} rows")
        
        transfer_data = {
            'rows_transferred': result.get('rows_transferred'),
            'chunks_processed': result.get('chunks_processed'),
            'target_table': result.get('target_table'),
            'direction': direction,
            'mode': mode,
            'columns': result.get('columns', [])
        }
        
        if log_event_callback:
            log_event_callback(
                'action_completed',
                task_id,
                task_name,
                'snowflake_transfer',
                'COMPLETED',
                duration,
                context,
                transfer_data,
                None,
                event_id
            )
        
        return {
            'id': task_id,
            'status': 'success',
            'data': make_serializable(transfer_data)
        }
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Snowflake transfer action failed: {error_msg}", exc_info=True)
        
        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        if log_event_callback:
            log_event_callback(
                'action_failed',
                task_id,
                task_name,
                'snowflake_transfer',
                'FAILED',
                duration,
                context,
                None,
                {'error': error_msg},
                None
            )
        
        return {
            'id': task_id,
            'status': 'error',
            'error': error_msg
        }
