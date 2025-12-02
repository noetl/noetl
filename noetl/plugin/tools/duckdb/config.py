"""
Configuration and parameter processing for DuckDB tasks.
"""

import os
import uuid
import datetime
import json
import ast
from typing import Dict, Any, Optional

from noetl.core.dsl.render import render_template
from noetl.core.logger import setup_logger

from .types import TaskConfig, ConnectionConfig, JinjaEnvironment, ContextDict
from .errors import ConfigurationError

logger = setup_logger(__name__, include_location=True)


def create_connection_config(
    context: ContextDict,
    task_config: Dict[str, Any],
    task_with: Dict[str, Any],
    jinja_env: JinjaEnvironment
) -> ConnectionConfig:
    """
    Create connection configuration from task parameters.
    
    Args:
        context: Execution context
        task_config: Task configuration
        task_with: Task 'with' parameters
        jinja_env: Jinja2 environment for template rendering
        
    Returns:
        ConnectionConfig instance
        
    Raises:
        ConfigurationError: If configuration is invalid
    """
    try:
        # Get execution ID from various possible locations
        execution_id = (
            context.get("execution_id") or 
            context.get("jobId") or 
            (context.get("job", {}).get("uuid") if isinstance(context.get("job"), dict) else None) or
            "default"
        )
        
        # Render execution ID if it contains templates
        if isinstance(execution_id, str) and ('{{' in execution_id or '}}' in execution_id):
            execution_id = render_template(jinja_env, execution_id, context)
        
        # Determine database path
        custom_db_path = task_config.get('database')
        if custom_db_path:
            if '{{' in custom_db_path or '}}' in custom_db_path:
                custom_db_path = render_template(jinja_env, custom_db_path, {**context, **(task_with or {})})
            database_path = custom_db_path
        else:
            duckdb_data_dir = os.environ.get("NOETL_DATA_DIR", "./data")
            database_path = os.path.join(duckdb_data_dir, "noetldb", f"duckdb_{execution_id}.duckdb")
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(database_path), exist_ok=True)
        
        return ConnectionConfig(
            database_path=database_path,
            execution_id=str(execution_id)
        )
        
    except Exception as e:
        raise ConfigurationError(f"Failed to create connection config: {e}")


def create_task_config(
    task_config: Dict[str, Any],
    task_with: Dict[str, Any],
    jinja_env: JinjaEnvironment,
    context: ContextDict
) -> TaskConfig:
    """
    Create task configuration from input parameters.
    
    Args:
        task_config: Raw task configuration
        task_with: Task 'with' parameters  
        jinja_env: Jinja2 environment for template rendering
        context: Execution context
        
    Returns:
        TaskConfig instance
        
    Raises:
        ConfigurationError: If configuration is invalid
    """
    try:
        task_id = str(uuid.uuid4())
        task_name = task_config.get('task', 'duckdb_task')
        
        # Decode commands with script support
        commands = _decode_commands(task_config, context, jinja_env)
        
        return TaskConfig(
            task_id=task_id,
            task_name=task_name,
            commands=commands,
            credentials=task_config.get('credentials'),
            auth=task_config.get('auth'),
            database=task_config.get('database'),
            auto_secrets=task_with.get('auto_secrets', True) if task_with else True
        )
        
    except Exception as e:
        raise ConfigurationError(f"Failed to create task config: {e}")


def preprocess_task_with(
    task_with: Optional[Dict[str, Any]], 
    jinja_env: JinjaEnvironment,
    context: ContextDict
) -> Dict[str, Any]:
    """
    Preprocess and render task 'with' parameters.
    
    Args:
        task_with: Raw task 'with' parameters
        jinja_env: Jinja2 environment for template rendering
        context: Execution context
        
    Returns:
        Processed parameters dictionary
    """
    if not task_with:
        return {}
        
    try:
        # Pre-render task_with values so templates resolve before being used in commands
        processed = task_with
        if isinstance(task_with, (dict, list, str)):
            processed = render_template(jinja_env, task_with, context)
            
        # Coerce stringified dicts/lists into Python objects
        processed = _coerce_stringified_objects(processed)
        
        # Handle GCS schema normalization (gcs:// -> gs://)
        processed = _normalize_cloud_uris(processed)
        
        return processed
        
    except Exception as e:
        logger.warning(f"Failed to preprocess task_with parameters: {e}")
        return task_with or {}


def _decode_commands(task_config: Dict[str, Any], context: Optional[ContextDict] = None, jinja_env: Optional[JinjaEnvironment] = None) -> str:
    """
    Decode or extract commands from task configuration.
    
    Priority order (matching postgres plugin):
    1. script attribute (external code loading)
    2. command_b64 or commands_b64 (base64 encoded)
    3. command or commands (inline, for Jinja2 rendering)
    
    Args:
        task_config: Task configuration containing commands
        context: Execution context (required for script resolution)
        jinja_env: Jinja2 environment (required for script resolution)
        
    Returns:
        Commands string
        
    Raises:
        ConfigurationError: If no valid commands found or decoding fails
    """
    import base64
    
    # Priority 1: External script (requires context and jinja_env)
    if 'script' in task_config:
        from noetl.plugin.shared.script import resolve_script
        logger.debug(f"DUCKDB: Resolving external script")
        if not context or not jinja_env:
            raise ConfigurationError("Context and jinja_env are required for script resolution")
        commands = resolve_script(task_config['script'], context, jinja_env)
        logger.debug(f"DUCKDB: Resolved script from {task_config['script']['source']['type']}, length={len(commands)} chars")
        return commands
    
    # Priority 2: Base64 encoded commands
    command_b64 = task_config.get('command_b64', '')
    commands_b64 = task_config.get('commands_b64', '')
    
    commands = ''
    
    if command_b64:
        try:
            commands = base64.b64decode(command_b64.encode('ascii')).decode('utf-8')
            logger.debug(f"DUCKDB: Decoded base64 command, length={len(commands)} chars")
        except Exception as e:
            raise ConfigurationError(f"Invalid base64 command encoding: {e}")
    elif commands_b64:
        try:
            commands = base64.b64decode(commands_b64.encode('ascii')).decode('utf-8')
            logger.debug(f"DUCKDB: Decoded base64 commands, length={len(commands)} chars")
        except Exception as e:
            raise ConfigurationError(f"Invalid base64 commands encoding: {e}")
    
    # Priority 3: Inline command/commands (for Jinja2 template rendering)
    elif 'command' in task_config:
        commands = task_config['command']
        logger.debug(f"DUCKDB: Using inline command, length={len(commands)} chars")
    elif 'commands' in task_config:
        commands = task_config['commands']
        logger.debug(f"DUCKDB: Using inline commands, length={len(commands)} chars")
    
    else:
        raise ConfigurationError("No command provided. Expected 'script', 'command_b64', 'commands_b64', 'command', or 'commands'")
    
    return commands


def _coerce_stringified_objects(processed: Any) -> Any:
    """
    Convert stringified dicts/lists (e.g., "{'key': 'val'}") into Python objects.
    
    Args:
        processed: Object to process
        
    Returns:
        Object with stringified dicts/lists converted to actual objects
    """
    try:
        def _coerce_val(v):
            if isinstance(v, str):
                s = v.strip()
                if (s.startswith('{') and s.endswith('}')) or (s.startswith('[') and s.endswith(']')):
                    try:
                        return json.loads(s)
                    except Exception:
                        try:
                            return ast.literal_eval(s)
                        except Exception:
                            return v
            return v
            
        if isinstance(processed, dict):
            return {k: _coerce_val(v) for k, v in processed.items()}
        return processed
        
    except Exception:
        return processed


def _normalize_cloud_uris(processed: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize cloud URIs (convert gcs:// to gs://).
    
    Args:
        processed: Parameters to normalize
        
    Returns:
        Parameters with normalized URIs
    """
    if not isinstance(processed, dict):
        return processed
        
    output_base = processed.get('output_uri_base', '')
    if isinstance(output_base, str) and output_base.lower().startswith('gcs://'):
        new_base = 'gs://' + output_base[6:]
        processed['output_uri_base'] = new_base
        logger.warning("output_uri_base uses gcs://; rewriting to gs:// (%s -> %s)", output_base, new_base)
        
    return processed