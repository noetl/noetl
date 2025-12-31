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
from typing import Dict, Any, Optional, Callable, Tuple

from noetl.core.logger import setup_logger
from noetl.worker.auth_compatibility import validate_auth_transition, transform_credentials_to_auth

# Import refactored modules
from noetl.tools.duckdb.config import create_connection_config, create_task_config, preprocess_task_with
from noetl.tools.duckdb.connections import get_duckdb_connection as _get_connection_new, create_standalone_connection
from noetl.tools.duckdb.extensions import get_required_extensions, install_and_load_extensions, install_database_extensions
from noetl.tools.duckdb.auth import resolve_unified_auth, generate_duckdb_secrets
from noetl.tools.duckdb.sql import render_commands, execute_sql_commands, serialize_results, create_task_result
from noetl.tools.duckdb.cloud import detect_uri_scopes, configure_cloud_credentials, validate_cloud_output_requirement
from noetl.tools.duckdb.excel import ExcelExportManager
from noetl.tools.duckdb.types import JinjaEnvironment, ContextDict, LogEventCallback
from noetl.tools.duckdb.errors import DuckDBPluginError

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
        logger.debug("DUCKDB.EXECUTE_TASK: Entry")
        
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
            resolved_auth_map = {}
            if task_cfg.auto_secrets:
                secrets_created, resolved_auth_map = _setup_authentication(
                    conn, task_config, processed_task_with, jinja_env, context
                )
            else:
                resolved_auth_map = {}
            
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
            logger.debug(f"[DUCKDB DEBUG] Detected URI scopes: {uri_scopes}")
            logger.debug(f"[DUCKDB DEBUG] task_config keys: {list(task_config.keys())}, gcs_credential={task_config.get('gcs_credential')}")
            logger.debug(f"[DUCKDB DEBUG] processed_task_with keys: {list(processed_task_with.keys())}, gcs_credential={processed_task_with.get('gcs_credential')}")
            logger.info(f"Detected URI scopes: {uri_scopes}")
            logger.info(f"task_config keys: {list(task_config.keys())}, gcs_credential={task_config.get('gcs_credential')}")
            logger.info(f"processed_task_with keys: {list(processed_task_with.keys())}, gcs_credential={processed_task_with.get('gcs_credential')}")
            if uri_scopes.get('gs') or uri_scopes.get('s3'):
                logger.debug(f"[DUCKDB DEBUG] Calling configure_cloud_credentials...")
                cloud_secrets = configure_cloud_credentials(
                    conn,
                    uri_scopes,
                    task_config,
                    processed_task_with,
                    catalog_id=context.get('catalog_id'),
                    execution_id=context.get('execution_id'),
                )
                logger.debug(f"[DUCKDB DEBUG] Cloud secrets created: {cloud_secrets}")
                secrets_created += cloud_secrets
            
            # Diagnostic: List all secrets
            try:
                secrets_list = conn.execute("SELECT name, type, provider, scope FROM duckdb_secrets()").fetchall()
                logger.debug(f"[DUCKDB DEBUG] Current DuckDB secrets: {secrets_list}")
                logger.info(f"Current DuckDB secrets: {secrets_list}")
            except Exception as e:
                logger.debug(f"[DUCKDB DEBUG] Could not list secrets: {e}")
                
            # Validate cloud output requirements
            require_cloud = bool(processed_task_with.get('require_cloud_output') or task_config.get('require_cloud_output'))
            validate_cloud_output_requirement(rendered_commands, require_cloud)
            
            # Execute SQL commands
            excel_manager = ExcelExportManager(auth_map=resolved_auth_map)
            results = execute_sql_commands(
                conn,
                rendered_commands,
                task_id,
                excel_manager=excel_manager
            )
            
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
) -> Tuple[int, Dict[str, Any]]:
    """
    Setup authentication for DuckDB connection.
    
    Returns:
        Tuple of (number of secrets created, resolved auth map)
    """
    secrets_created = 0
    resolved_auth_map: Dict[str, Any] = {}
    
    try:
        # Try unified auth system first
        auth_config = task_config.get('auth') or processed_task_with.get('auth')
        if auth_config:
            logger.debug("Using unified auth system")
            
            resolved_auth_map = resolve_unified_auth(auth_config, jinja_env, context)
            logger.debug(f"[AUTH DEBUG] Resolved auth map: {list(resolved_auth_map.keys()) if resolved_auth_map else 'None'}")
            logger.debug(f"[AUTH DEBUG] Auth map details: {[(k, type(v)) for k, v in resolved_auth_map.items()] if resolved_auth_map else 'None'}")
            
            if resolved_auth_map:
                logger.info(f"Resolved auth aliases: {list(resolved_auth_map.keys())}")
                # Install required extensions
                required_extensions = get_required_extensions(resolved_auth_map)
                logger.info(f"Installing required extensions for auth: {required_extensions}")
                install_and_load_extensions(connection, required_extensions)
                
                # Generate and execute secret creation statements
                secret_statements = generate_duckdb_secrets(resolved_auth_map)
                logger.debug(f"[AUTH DEBUG] Generated {len(secret_statements)} secret statements")
                logger.debug(f"[AUTH DEBUG] Statements: {secret_statements[:3] if secret_statements else 'None'}")
                logger.info(f"Generated {len(secret_statements)} secret statements")
                for idx, stmt in enumerate(secret_statements):
                    # Log statement without revealing secrets
                    import re
                    redacted_stmt = re.sub(r"(SECRET|PASSWORD|KEY_ID|JSON_KEY)\s*'[^']*'", r"\1 '[REDACTED]'", stmt)
                    logger.debug(f"[AUTH DEBUG] Executing statement {idx+1}/{len(secret_statements)}: {redacted_stmt[:100]}...")
                    logger.info(f"Executing unified auth secret {idx+1}: {redacted_stmt[:150]}...")
                    try:
                        connection.execute(stmt)
                        logger.debug(f"[AUTH DEBUG] Statement {idx+1} executed successfully")
                    except Exception as stmt_err:
                        logger.debug(f"[AUTH DEBUG] Statement {idx+1} FAILED: {stmt_err}")
                        logger.error(f"Failed to execute statement {idx+1}: {stmt_err}")
                        raise
                
                secrets_created = len(secret_statements)
                if secrets_created:
                    logger.info(f"Unified auth system created {secrets_created} DuckDB secrets")
                
    except Exception as e:
        logger.warning(f"Authentication setup failed: {e}")
        
    return secrets_created, resolved_auth_map


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

