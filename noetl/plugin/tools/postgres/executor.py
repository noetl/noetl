"""
PostgreSQL task execution orchestration with async connection pooling.

Main entry point for executing PostgreSQL tasks with:
- Authentication resolution
- Command parsing and rendering
- Async SQL execution with connection pooling
- Result processing
- Event logging
"""

import uuid
import datetime
import asyncio
from typing import Dict
from jinja2 import Environment
from noetl.core.logger import setup_logger

from .auth import resolve_postgres_auth, validate_and_render_connection_params
from .command import escape_task_with_params, decode_base64_commands, render_and_split_commands
from .execution import execute_sql_with_pool
from .response import process_results, format_success_response, format_error_response, format_exception_response

logger = setup_logger(__name__, include_location=True)


def execute_postgres_task(task_config: Dict, context: Dict, jinja_env: Environment, task_with: Dict, log_event_callback=None) -> Dict:
    """
    Execute a PostgreSQL task (sync wrapper for async execution).

    This function orchestrates the complete lifecycle of a PostgreSQL task:
    1. Resolve authentication (unified auth or legacy credentials)
    2. Validate and render connection parameters
    3. Decode and parse SQL commands
    4. Execute SQL statements via async connection pool
    5. Process results and log events
    6. Return formatted response

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
            - db_host: Database host
            - db_port: Database port
            - db_user: Database user
            - db_password: Database password
            - db_name: Database name
            - db_conn_string: Optional connection string (overrides individual params)
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
        >>> result = execute_postgres_task(
        ...     task_config={'command_b64': 'U0VMRUNUIDEgQVMgdmFsdWU7'},
        ...     context={'execution_id': 'exec-123'},
        ...     jinja_env=Environment(),
        ...     task_with={
        ...         'db_host': 'localhost',
        ...         'db_port': '5432',
        ...         'db_user': 'user',
        ...         'db_password': 'pass',
        ...         'db_name': 'mydb'
        ...     }
        ... )
        >>> result['status']
        'success'
    """
    # Since we're called from worker's thread pool executor, just run async code directly
    return asyncio.run(_execute_postgres_task_async(task_config, context, jinja_env, task_with, log_event_callback))


async def _execute_postgres_task_async(
    task_config: Dict,
    context: Dict,
    jinja_env: Environment,
    task_with: Dict,
    log_event_callback=None
) -> Dict:
    """
    Execute a PostgreSQL task.

    This function orchestrates the complete lifecycle of a PostgreSQL task:
    1. Resolve authentication (unified auth or legacy credentials)
    2. Validate and render connection parameters
    3. Decode and parse SQL commands
    4. Connect to database
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
            - db_host: Database host
            - db_port: Database port
            - db_user: Database user
            - db_password: Database password
            - db_name: Database name
            - db_conn_string: Optional connection string (overrides individual params)
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
        >>> result = execute_postgres_task(
        ...     task_config={'command_b64': 'U0VMRUNUIDEgQVMgdmFsdWU7'},
        ...     context={'execution_id': 'exec-123'},
        ...     jinja_env=Environment(),
        ...     task_with={
        ...         'db_host': 'localhost',
        ...         'db_port': '5432',
        ...         'db_user': 'user',
        ...         'db_password': 'pass',
        ...         'db_name': 'mydb'
        ...     }
        ... )
        >>> result['status']
        'success'
    """
    task_id = str(uuid.uuid4())
    task_name = task_config.get('task', 'postgres_task')
    start_time = datetime.datetime.now()

    try:
        # Step 1: Resolve authentication
        task_config, task_with = resolve_postgres_auth(task_config, task_with, jinja_env, context)

        # Step 2: Validate and render connection parameters
        pg_host, pg_port, pg_user, pg_password, pg_db, pg_conn_string = validate_and_render_connection_params(
            task_with, jinja_env, context
        )

        # Step 3: Escape special characters in task_with for SQL compatibility
        processed_task_with = escape_task_with_params(task_with)

        # Step 4: Decode commands (with script support)
        commands_str = decode_base64_commands(task_config, context, jinja_env)

        # Step 5: Render and split commands into individual statements
        commands = render_and_split_commands(commands_str, jinja_env, context, processed_task_with)

        # Step 6: Log task start event
        event_id = None
        if log_event_callback:
            event_id = log_event_callback(
                'task_start', task_id, task_name, 'postgres',
                'in_progress', 0, context, None,
                {'with_params': task_with}, None
            )

        # Step 7: Execute SQL statements using connection pool (async)
        results = {}
        if commands:
            results = await execute_sql_with_pool(pg_conn_string, commands, pg_host, pg_port, pg_db)
        # Connection automatically returned to pool

        # Step 8: Process results
        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()
        has_error, error_message = process_results(results)
        task_status = 'error' if has_error else 'success'

        # Step 9: Log completion event
        if log_event_callback:
            log_event_callback(
                'task_complete' if not has_error else 'task_error',
                task_id, task_name, 'postgres',
                task_status, duration, context, results,
                {'with_params': task_with}, event_id
            )

        # Step 10: Return error response if any (error logged via event system)
        if has_error:
            return format_error_response(task_id, error_message, results)
        else:
            return format_success_response(task_id, results)

    except Exception as e:
        # Handle unexpected errors
        logger.error(f"Postgres task execution error: {str(e)}", exc_info=True)
        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()

        # Log error event
        if log_event_callback:
            log_event_callback(
                'task_error', task_id, task_name, 'postgres',
                'error', duration, context, None,
                {'error': str(e), 'with_params': task_with}, None
            )

        return format_exception_response(task_id, e)
