"""
PostgreSQL task execution orchestration with async connections.

Main entry point for executing PostgreSQL tasks with:
- Authentication resolution
- Command parsing and rendering
- Async SQL execution using psycopg AsyncConnection
- Result processing
- Event logging
"""

import asyncio
import datetime
import hashlib
import os
import uuid
from typing import Dict
from jinja2 import Environment
from noetl.core.logger import setup_logger
from noetl.worker.keychain_resolver import populate_keychain_context

from .auth import resolve_postgres_auth, validate_and_render_connection_params
from .command import escape_task_with_params, decode_base64_commands, render_and_split_commands
from .execution import execute_sql_with_connection
from .response import process_results, format_success_response, format_error_response, format_exception_response
from .models import validate_pool_config

logger = setup_logger(__name__, include_location=True)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except Exception:
        return default


def _default_pool_name(pg_host: str, pg_port: str, pg_db: str, pg_user: str) -> str:
    base = f"{pg_user}@{pg_host}:{pg_port}/{pg_db}"
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:10]
    return f"pg_{pg_db}_{digest}"


def _connection_meta(task_with: Dict, use_pool: bool, pool_name: str, pool_params: Dict) -> Dict:
    return {
        "with_param_keys": sorted(task_with.keys()) if isinstance(task_with, dict) else [],
        "connection_mode": "pool" if use_pool else "direct",
        "pool_name": pool_name if use_pool else None,
        "pool_params": pool_params if use_pool else {},
    }


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
    # Execute directly (async) - use asyncio.run() to bridge sync/async boundary
    # WARNING: This creates a new event loop per call, so plugin pools keyed by loop_id
    # are never reused. Prefer execute_postgres_task_async() when already in an async context.
    return asyncio.run(_execute_postgres_task_async(task_config, context, jinja_env, task_with, log_event_callback))


# Public async entry point - avoids asyncio.run() pool-leak when called from async worker
async def execute_postgres_task_async(
    task_config: Dict, context: Dict, jinja_env: Environment,
    task_with: Dict, log_event_callback=None
) -> Dict:
    """Async version of execute_postgres_task (no new event loop, pools are reused)."""
    return await _execute_postgres_task_async(
        task_config, context, jinja_env, task_with, log_event_callback
    )


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
    connection_meta = {
        "with_param_keys": sorted(task_with.keys()) if isinstance(task_with, dict) else [],
        "connection_mode": "unknown",
    }

    try:
        # Step 0: Populate keychain context FIRST before any template rendering
        catalog_id = context.get('catalog_id')
        if catalog_id:
            execution_id = context.get('execution_id')
            server_url = context.get('server_url', 'http://noetl.noetl.svc.cluster.local:8082')
            context = await populate_keychain_context(
                task_config=task_config,
                context=context,
                catalog_id=catalog_id,
                execution_id=execution_id,
                api_base_url=server_url
            )
            logger.debug(f"POSTGRES: Keychain context populated: {list(context.get('keychain', {}).keys())}")
        
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

        # Step 6: Resolve connection mode and pool configuration.
        # Default mode is pooled for stable DB pressure in distributed runs.
        pool_config = task_config.get('pool')
        use_pool = _env_bool("NOETL_POSTGRES_USE_POOL_DEFAULT", True)
        pool_params = {}
        pool_name = None

        if isinstance(pool_config, bool):
            use_pool = pool_config
        elif pool_config is None:
            use_pool = _env_bool("NOETL_POSTGRES_USE_POOL_DEFAULT", True)
        elif isinstance(pool_config, dict):
            use_pool = True
            try:
                validated = validate_pool_config(pool_config)
                pool_name = validated.pop("name", None)
                pool_params = validated
            except ValueError as e:
                logger.error(f"Invalid pool configuration: {e}")
                raise ValueError(f"Pool configuration validation failed: {e}")
        else:
            logger.warning(
                "Unsupported postgres.pool type=%s; using default mode",
                type(pool_config).__name__,
            )

        if use_pool:
            if not pool_name:
                pool_name = _default_pool_name(pg_host, pg_port, pg_db, pg_user)
            pool_params.setdefault("min_size", _env_int("NOETL_POSTGRES_POOL_MIN_SIZE", 1))
            pool_params.setdefault("max_size", _env_int("NOETL_POSTGRES_POOL_MAX_SIZE", 12))
            pool_params.setdefault("max_waiting", _env_int("NOETL_POSTGRES_POOL_MAX_WAITING", 100))
            pool_params.setdefault("timeout", _env_float("NOETL_POSTGRES_POOL_TIMEOUT_SECONDS", 60.0))
            logger.info(
                "POSTGRES: pooled mode pool=%s min=%s max=%s waiting=%s timeout=%ss commands=%s",
                pool_name,
                pool_params.get("min_size"),
                pool_params.get("max_size"),
                pool_params.get("max_waiting"),
                pool_params.get("timeout"),
                len(commands),
            )
        else:
            logger.info("POSTGRES: direct mode commands=%s", len(commands))

        connection_meta = _connection_meta(task_with, use_pool, pool_name, pool_params)

        # Step 7: Log task start event
        event_id = None
        if log_event_callback:
            event_id = log_event_callback(
                'task_start', task_id, task_name, 'postgres',
                'in_progress', 0, context, None,
                connection_meta, None
            )

        # Step 8: Execute SQL statements using async connection
        results = {}
        if commands:
            results = await execute_sql_with_connection(
                pg_conn_string, commands, pg_host, pg_port, pg_db,
                pool=use_pool,
                pool_name=pool_name,
                pool_params=pool_params
            )
        # Connection automatically closed via context manager

        # Step 9: Process results
        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()
        has_error, error_message = process_results(results)
        task_status = 'error' if has_error else 'success'

        # Step 10: Log completion event
        if log_event_callback:
            log_event_callback(
                'task_complete' if not has_error else 'task_error',
                task_id, task_name, 'postgres',
                task_status, duration, context, results,
                connection_meta, event_id
            )

        # Step 11: Return error response if any (error logged via event system)
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
            error_meta = dict(connection_meta)
            error_meta["error"] = str(e)
            log_event_callback(
                'task_error', task_id, task_name, 'postgres',
                'error', duration, context, None,
                error_meta, None
            )

        return format_exception_response(task_id, e)
