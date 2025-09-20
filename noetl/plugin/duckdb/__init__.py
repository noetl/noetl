"""
DuckDB plugin for NoETL - Refactored modular implementation.

This module provides DuckDB task execution capabilities with support for:
- Multiple database attachments (PostgreSQL, MySQL, SQLite)
- Cloud storage integration (GCS, S3)  
- Unified authentication system
- Legacy credential compatibility
- Connection pooling and management

Public API:
- execute_duckdb_task: Main task execution function
- get_duckdb_connection: Connection context manager (deprecated, use connections.get_duckdb_connection)
"""

import warnings
import datetime
import traceback
from typing import Dict, Any, Optional, Callable

from noetl.core.logger import setup_logger
from noetl.worker.auth_compatibility import validate_auth_transition, transform_credentials_to_auth

# Import refactored modules
from .config import create_connection_config, create_task_config, preprocess_task_with
from .connections import get_duckdb_connection as _get_connection_new, create_standalone_connection
from .extensions import get_required_extensions, install_and_load_extensions, install_database_extensions
from .auth import resolve_unified_auth, resolve_credentials, generate_duckdb_secrets
from .sql import render_commands, execute_sql_commands, serialize_results, create_task_result
from .cloud import detect_uri_scopes, configure_cloud_credentials, validate_cloud_output_requirement
from .types import JinjaEnvironment, ContextDict, LogEventCallback
from .errors import DuckDBPluginError

logger = setup_logger(__name__, include_location=True)


def execute_duckdb_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: JinjaEnvironment,
    task_with: Dict[str, Any],
    log_event_callback: LogEventCallback = None
) -> Dict[str, Any]:
    """
    Execute a DuckDB task using the refactored modular implementation.

    Args:
        task_config: The task configuration
        context: The context for rendering templates
        jinja_env: The Jinja2 environment for template rendering
        task_with: The rendered 'with' parameters dictionary
        log_event_callback: A callback function to log events

    Returns:
        A dictionary of the task result
    """
    start_time = datetime.datetime.now()
    task_id = None
    
    try:
        logger.debug("=== DUCKDB.EXECUTE_TASK: Refactored implementation entry ===")
        
        # Apply backwards compatibility transformation for deprecated 'credentials' field
        validate_auth_transition(task_config, task_with)
        task_config, task_with = transform_credentials_to_auth(task_config, task_with)
        
        # Preprocess task parameters
        processed_task_with = preprocess_task_with(task_with, jinja_env, context)
        
        # Create task and connection configurations
        task_cfg = create_task_config(task_config, processed_task_with, jinja_env, context)
        connection_config = create_connection_config(context, task_config, processed_task_with, jinja_env)
        
        task_id = task_cfg.task_id
        task_name = task_cfg.task_name
        
        logger.debug(f"DUCKDB.EXECUTE_TASK: task_id={task_id}, task_name={task_name}")
        
        # Log task start event
        event_id = None
        if log_event_callback:
            logger.debug("DUCKDB.EXECUTE_TASK: Writing task_start event log")
            event_id = log_event_callback(
                'task_start', task_id, task_name, 'duckdb',
                'in_progress', 0, context, None,
                {'with_params': processed_task_with}, None
            )
        
        # Establish DuckDB connection
        with _get_connection_new(connection_config) as conn:
            logger.info(f"Connected to DuckDB at {connection_config.database_path}")
            
            # Process authentication and create secrets
            secrets_created = 0
            if task_cfg.auto_secrets:
                secrets_created = _setup_authentication(
                    conn, task_config, processed_task_with, jinja_env, context
                )
            
            # Install database extensions for basic database types
            db_type = processed_task_with.get('db_type', 'postgres')
            install_database_extensions(conn, db_type)
            
            # Render SQL commands with full context
            template_context = {
                **context, 
                **(processed_task_with or {}),
                'task_id': task_id,
                'execution_id': connection_config.execution_id
            }
            
            rendered_commands = render_commands(task_cfg.commands, jinja_env, template_context)
            logger.info(f"Rendered {len(rendered_commands)} SQL commands for execution")
            
            # Detect cloud URI scopes and configure cloud credentials if needed
            uri_scopes = detect_uri_scopes(rendered_commands)
            if uri_scopes.get('gs') or uri_scopes.get('s3'):
                cloud_secrets = configure_cloud_credentials(
                    conn, uri_scopes, task_config, processed_task_with
                )
                secrets_created += cloud_secrets
                
            # Validate cloud output requirements
            require_cloud = bool(processed_task_with.get('require_cloud_output') or task_config.get('require_cloud_output'))
            validate_cloud_output_requirement(rendered_commands, require_cloud)
            
            # Execute SQL commands
            results = execute_sql_commands(conn, rendered_commands, task_id)
            
            # Add metadata to results
            results.update({
                'task_id': task_id,
                'execution_id': connection_config.execution_id,
                'secrets_created': secrets_created,
                'database_path': connection_config.database_path
            })
            
        # Calculate duration and serialize results
        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        serialized_results = serialize_results(results, task_id)
        
        # Log task completion
        if log_event_callback:
            log_event_callback(
                'task_complete', task_id, task_name, 'duckdb',
                'success', duration, context, serialized_results,
                {'with_params': processed_task_with}, event_id
            )
        
        return create_task_result(
            task_id=task_id,
            status='success',
            duration=duration,
            data=serialized_results
        )
        
    except Exception as e:
        error_msg = str(e)
        tb_text = traceback.format_exc()
        
        logger.error(f"DuckDB task execution error: {error_msg}", exc_info=True)
        
        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        # Log task error
        if log_event_callback and task_id:
            logger.debug("DUCKDB.EXECUTE_TASK: Writing task_error event log")
            log_event_callback(
                'task_error', task_id or 'unknown', task_config.get('task', 'duckdb_task'), 'duckdb',
                'error', duration, context, None,
                {'error': error_msg, 'with_params': task_with}, None
            )
        
        return create_task_result(
            task_id=task_id or 'unknown',
            status='error',
            duration=duration,
            error=error_msg,
            traceback=tb_text
        )


def _setup_authentication(
    connection,
    task_config: Dict[str, Any],
    processed_task_with: Dict[str, Any],
    jinja_env: JinjaEnvironment,
    context: ContextDict
) -> int:
    """
    Setup authentication for DuckDB connection.
    
    Returns:
        Number of secrets created
    """
    secrets_created = 0
    
    try:
        # Try unified auth system first
        auth_config = task_config.get('auth') or processed_task_with.get('auth')
        if auth_config:
            logger.debug("Using unified auth system")
            
            resolved_auth_map = resolve_unified_auth(auth_config, jinja_env, context)
            
            if resolved_auth_map:
                # Install required extensions
                required_extensions = get_required_extensions(resolved_auth_map)
                install_and_load_extensions(connection, required_extensions)
                
                # Generate and execute secret creation statements
                secret_statements = generate_duckdb_secrets(resolved_auth_map)
                for stmt in secret_statements:
                    # Log statement without revealing secrets
                    import re
                    redacted_stmt = re.sub(r"(SECRET|PASSWORD|KEY_ID)\s*'[^']*'", r"\1 '[REDACTED]'", stmt)
                    logger.info(f"Executing unified auth secret: {redacted_stmt[:150]}...")
                    connection.execute(stmt)
                
                secrets_created = len(secret_statements)
                if secrets_created:
                    logger.info(f"Unified auth system created {secrets_created} DuckDB secrets")
                    
        # Fall back to legacy credential system if no unified auth
        elif 'credentials' in task_config:
            logger.debug("Using legacy credential system")
            credentials_config = task_config.get('credentials')
            resolved_creds = resolve_credentials(credentials_config, jinja_env, context)
            
            # Convert legacy credentials to secret statements
            # This is simplified - full legacy support would require more complex handling
            if resolved_creds:
                logger.info(f"Resolved {len(resolved_creds)} legacy credentials")
                # Legacy system handling would go here
                
    except Exception as e:
        logger.warning(f"Authentication setup failed: {e}")
        
    return secrets_created


def get_duckdb_connection(duckdb_file_path: str):
    """
    Legacy compatibility function for getting DuckDB connections.
    
    DEPRECATED: Use connections.get_duckdb_connection with ConnectionConfig instead.
    
    Args:
        duckdb_file_path: Path to DuckDB file
        
    Yields:
        DuckDB connection
    """
    warnings.warn(
        "get_duckdb_connection(duckdb_file_path) is deprecated. "
        "Use connections.get_duckdb_connection with ConnectionConfig instead.",
        DeprecationWarning,
        stacklevel=2
    )
    
    # Create a simple ConnectionConfig for legacy compatibility
    from .types import ConnectionConfig
    config = ConnectionConfig(database_path=duckdb_file_path, execution_id="legacy")
    
    with _get_connection_new(config) as conn:
        yield conn


# Public API exports
__all__ = ['execute_duckdb_task', 'get_duckdb_connection']

# Legacy compatibility exports for internal functions used by tests
from .sql.rendering import render_deep as _render_deep, escape_sql as _escape_sql
from .auth.legacy import build_legacy_credential_prelude as _build_duckdb_secret_prelude