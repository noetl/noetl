"""
Snowflake task execution orchestration.

Main entry point for executing Snowflake tasks with:
- Authentication resolution
- Command parsing and rendering
- SQL execution
- Result processing
- Event logging
- MCP compatibility
- Chunked data transfer between Snowflake and PostgreSQL
"""

import uuid
import datetime
from typing import Dict
from jinja2 import Environment
from noetl.core.common import make_serializable
from noetl.core.logger import setup_logger, log_error

from .auth import resolve_snowflake_auth, validate_and_render_connection_params
from .command import escape_task_with_params, decode_base64_commands, render_and_split_commands
from .execution import connect_to_snowflake, execute_sql_statements
from .response import process_results, format_success_response, format_error_response, format_exception_response
from .transfer import transfer_snowflake_to_postgres, transfer_postgres_to_snowflake

logger = setup_logger(__name__, include_location=True)


def execute_snowflake_task(
    task_config: Dict,
    context: Dict,
    jinja_env: Environment,
    task_with: Dict,
    log_event_callback=None
) -> Dict:
    """
    Execute a Snowflake task.

    This function orchestrates the complete lifecycle of a Snowflake task:
    1. Resolve authentication (unified auth or legacy credentials)
    2. Validate and render connection parameters
    3. Decode and parse SQL commands
    4. Connect to Snowflake database
    5. Execute SQL statements
    6. Process results and log events
    7. Return formatted response

    Args:
        task_config: The task configuration containing:
            - command_b64 or commands_b64: Base64 encoded SQL commands
            - auth: Authentication configuration (optional)
            - credential: Legacy credential reference (deprecated, optional)
        context: The execution context for rendering templates containing:
            - execution_id: The execution identifier
            - Other context variables for Jinja2 rendering
        jinja_env: The Jinja2 environment for template rendering
        task_with: The rendered 'with' parameters dictionary containing:
            - account: Snowflake account identifier (required)
            - user: Snowflake username (required)
            - password: Snowflake password (required)
            - warehouse: Snowflake warehouse (optional, default: COMPUTE_WH)
            - database: Snowflake database (optional)
            - schema: Snowflake schema (optional, default: PUBLIC)
            - role: Snowflake role (optional)
            - authenticator: Authentication method (optional, default: snowflake)
        log_event_callback: Optional callback function to log events with signature:
            (event_type, task_id, task_name, task_type, status, duration, context, result, metadata, parent_event_id)

    Returns:
        A dictionary containing the task execution result:
        - id: Task identifier (UUID)
        - status: 'success' or 'error'
        - data: Dictionary of command results (on success or partial success)
        - error: Error message (on error)
        - traceback: Exception traceback (on unexpected error)

    Example:
        >>> result = execute_snowflake_task(
        ...     task_config={'command_b64': 'U0VMRUNUIDEgQVMgdmFsdWU7'},
        ...     context={'execution_id': 'exec-123'},
        ...     jinja_env=Environment(),
        ...     task_with={
        ...         'account': 'xy12345.us-east-1',
        ...         'user': 'my_user',
        ...         'password': 'my_password',
        ...         'warehouse': 'COMPUTE_WH',
        ...         'database': 'MY_DB',
        ...         'schema': 'PUBLIC'
        ...     }
        ... )
        >>> result['status']
        'success'
    """
    task_id = str(uuid.uuid4())
    task_name = task_config.get('task', 'snowflake_task')
    start_time = datetime.datetime.now()

    try:
        logger.info(f"Starting Snowflake task execution: {task_name}")
        
        # Step 1: Resolve authentication
        task_config, task_with = resolve_snowflake_auth(task_config, task_with, jinja_env, context)

        # Step 2: Validate and render connection parameters
        account, user, password, warehouse, database, schema, role, authenticator = validate_and_render_connection_params(
            task_with, jinja_env, context
        )

        # Step 3: Escape special characters in task_with for SQL compatibility
        processed_task_with = escape_task_with_params(task_with)

        # Step 4: Decode base64 commands
        commands_str = decode_base64_commands(task_config)

        # Step 5: Render and split commands into individual statements
        commands = render_and_split_commands(commands_str, jinja_env, context, processed_task_with)

        # Step 6: Log task start event
        event_id = None
        if log_event_callback:
            event_id = log_event_callback(
                'task_start', task_id, task_name, 'snowflake',
                'in_progress', 0, context, None,
                {'with_params': task_with}, None
            )

        # Step 7: Connect to Snowflake
        conn = connect_to_snowflake(
            account=account,
            user=user,
            password=password,
            warehouse=warehouse,
            database=database,
            schema=schema,
            role=role,
            authenticator=authenticator
        )

        # Step 8: Execute SQL statements
        results = {}
        if commands:
            results = execute_sql_statements(conn, commands)

        # Step 9: Close connection
        conn.close()
        logger.info(f"Snowflake connection closed")

        # Step 10: Process results
        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()
        has_error, error_message = process_results(results)
        task_status = 'error' if has_error else 'success'

        # Step 11: Log completion event
        if log_event_callback:
            log_event_callback(
                'task_complete' if not has_error else 'task_error',
                task_id, task_name, 'snowflake',
                task_status, duration, context, results,
                {'with_params': task_with}, event_id
            )

        # Step 12: Log errors to database if any
        if has_error:
            try:
                log_error(
                    error=Exception(error_message),
                    error_type="snowflake_execution",
                    template_string=str(commands),
                    context_data=make_serializable(context),
                    input_data=make_serializable(task_with),
                    execution_id=context.get('execution_id'),
                    step_id=task_id,
                    step_name=task_name
                )
            except Exception as e:
                logger.error(f"Failed to log error to database: {e}")

            return format_error_response(task_id, error_message, results)
        else:
            return format_success_response(task_id, results)

    except Exception as e:
        # Handle unexpected errors
        logger.error(f"Snowflake task execution error: {str(e)}", exc_info=True)
        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()

        # Log error event
        if log_event_callback:
            log_event_callback(
                'task_error', task_id, task_name, 'snowflake',
                'error', duration, context, None,
                {'error': str(e), 'with_params': task_with}, None
            )

        return format_exception_response(task_id, e)


def execute_snowflake_transfer_task(
    task_config: Dict,
    context: Dict,
    jinja_env: Environment,
    task_with: Dict,
    log_event_callback=None
) -> Dict:
    """
    Execute a Snowflake data transfer task with chunked streaming.

    This function enables efficient data movement between Snowflake and PostgreSQL:
    - Snowflake to PostgreSQL transfer with configurable chunk size
    - PostgreSQL to Snowflake transfer with configurable chunk size
    - Multiple transfer modes: append, replace, upsert/merge
    - Progress tracking through callback mechanism

    Args:
        task_config: The task configuration containing:
            - transfer_direction: 'sf_to_pg' or 'pg_to_sf' (required)
            - source_query: SQL query to fetch data from source (required)
            - target_table: Target table name (required)
            - chunk_size: Rows per chunk (optional, default: 1000)
            - mode: Transfer mode - 'append', 'replace', 'upsert'/'merge' (optional, default: 'append')
            - sf_auth: Snowflake authentication config (required)
            - pg_auth: PostgreSQL authentication config (required)
        context: The execution context for rendering templates
        jinja_env: The Jinja2 environment for template rendering
        task_with: The rendered 'with' parameters dictionary containing:
            Snowflake connection params:
            - sf_account, sf_user, sf_password, sf_warehouse, sf_database, sf_schema
            PostgreSQL connection params:
            - pg_host, pg_port, pg_user, pg_password, pg_database
        log_event_callback: Optional callback function to log events

    Returns:
        A dictionary containing the transfer result:
        - id: Task identifier (UUID)
        - status: 'success' or 'error'
        - data: Transfer statistics (rows_transferred, chunks_processed, etc.)
        - error: Error message (on error)

    Example:
        >>> result = execute_snowflake_transfer_task(
        ...     task_config={
        ...         'transfer_direction': 'sf_to_pg',
        ...         'source_query': 'SELECT * FROM my_table',
        ...         'target_table': 'public.my_target',
        ...         'chunk_size': 5000,
        ...         'mode': 'append'
        ...     },
        ...     context={'execution_id': 'exec-123'},
        ...     jinja_env=Environment(),
        ...     task_with={
        ...         'sf_account': 'xy12345.us-east-1',
        ...         'sf_user': 'my_user',
        ...         'sf_password': 'my_password',
        ...         'pg_host': 'localhost',
        ...         'pg_port': '5432',
        ...         'pg_user': 'postgres',
        ...         'pg_password': 'pass',
        ...         'pg_database': 'mydb'
        ...     }
        ... )
        >>> result['status']
        'success'
    """
    import psycopg
    
    task_id = str(uuid.uuid4())
    task_name = task_config.get('task', 'snowflake_transfer_task')
    start_time = datetime.datetime.now()

    try:
        logger.info(f"Starting Snowflake transfer task: {task_name}")
        
        # Extract transfer parameters
        transfer_direction = task_config.get('transfer_direction')
        source_query = task_config.get('source_query')
        target_table = task_config.get('target_table')
        chunk_size = task_config.get('chunk_size', 1000)
        mode = task_config.get('mode', 'append')
        
        if not transfer_direction or transfer_direction not in ['sf_to_pg', 'pg_to_sf']:
            raise ValueError("transfer_direction must be 'sf_to_pg' or 'pg_to_sf'")
        
        if not source_query:
            raise ValueError("source_query is required")
        
        if not target_table:
            raise ValueError("target_table is required")
        
        logger.info(f"Transfer: {transfer_direction}, Mode: {mode}, Chunk size: {chunk_size}")
        
        # Resolve Snowflake authentication
        sf_account = task_with.get('sf_account')
        sf_user = task_with.get('sf_user')
        sf_password = task_with.get('sf_password')
        sf_warehouse = task_with.get('sf_warehouse', 'COMPUTE_WH')
        sf_database = task_with.get('sf_database')
        sf_schema = task_with.get('sf_schema', 'PUBLIC')
        sf_role = task_with.get('sf_role')
        
        # Resolve PostgreSQL authentication
        pg_host = task_with.get('pg_host', 'localhost')
        pg_port = task_with.get('pg_port', '5432')
        pg_user = task_with.get('pg_user')
        pg_password = task_with.get('pg_password')
        pg_database = task_with.get('pg_database')
        
        # Log task start event
        event_id = None
        if log_event_callback:
            event_id = log_event_callback(
                'task_start', task_id, task_name, 'snowflake_transfer',
                'in_progress', 0, context, None,
                {'with_params': task_with, 'direction': transfer_direction}, None
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
        
        # Execute transfer based on direction
        if transfer_direction == 'sf_to_pg':
            result = transfer_snowflake_to_postgres(
                sf_conn=sf_conn,
                pg_conn=pg_conn,
                source_query=source_query,
                target_table=target_table,
                chunk_size=chunk_size,
                mode=mode,
                progress_callback=progress_cb
            )
        else:  # pg_to_sf
            result = transfer_postgres_to_snowflake(
                pg_conn=pg_conn,
                sf_conn=sf_conn,
                source_query=source_query,
                target_table=target_table,
                chunk_size=chunk_size,
                mode=mode,
                progress_callback=progress_cb
            )
        
        # Close connections
        sf_conn.close()
        pg_conn.close()
        logger.info("Connections closed")
        
        # Calculate duration
        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        # Determine task status
        task_status = result.get('status', 'error')
        
        # Log completion event
        if log_event_callback:
            log_event_callback(
                'task_complete' if task_status == 'success' else 'task_error',
                task_id, task_name, 'snowflake_transfer',
                task_status, duration, context, result,
                {'with_params': task_with, 'direction': transfer_direction}, event_id
            )
        
        # Return result
        if task_status == 'success':
            return {
                'id': task_id,
                'status': 'success',
                'data': result
            }
        else:
            return {
                'id': task_id,
                'status': 'error',
                'error': result.get('error', 'Unknown transfer error'),
                'data': result
            }
    
    except Exception as e:
        # Handle unexpected errors
        logger.error(f"Snowflake transfer task error: {str(e)}", exc_info=True)
        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()

        # Log error event
        if log_event_callback:
            log_event_callback(
                'task_error', task_id, task_name, 'snowflake_transfer',
                'error', duration, context, None,
                {'error': str(e), 'with_params': task_with}, None
            )

        return format_exception_response(task_id, e)
