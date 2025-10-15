"""
Snowflake task execution orchestration.

Main entry point for executing Snowflake tasks with:
- Authentication resolution
- Command parsing and rendering
- SQL execution
- Result processing
- Event logging
- MCP compatibility
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
