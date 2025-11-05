"""
DuckDB storage delegation for save operations.

Handles delegating to duckdb plugin for database operations.
"""

from typing import Dict, Any, Optional, Callable
from jinja2 import Environment

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def build_duckdb_commands(
    storage_config: Dict[str, Any],
    statement: Optional[str],
    rendered_data: Dict[str, Any]
) -> str:
    """
    Build DuckDB commands from configuration.
    
    Args:
        storage_config: Storage configuration
        statement: SQL statement
        rendered_data: Rendered data mapping
        
    Returns:
        DuckDB SQL commands string
        
    Raises:
        ValueError: If no commands can be built
    """
    # Extract commands/SQL from storage config or build from data
    commands = (storage_config.get('commands') or 
                storage_config.get('sql') or 
                statement)
    
    if not commands and rendered_data:
        # Build default DuckDB commands to create table and insert data
        if isinstance(rendered_data, dict):
            # Simple table creation from dict keys
            table_name = storage_config.get('table', 'save_data')
            cols = []
            vals = []
            
            for k, v in rendered_data.items():
                cols.append(f"{k} VARCHAR")
                if v is not None:
                    escaped_v = str(v).replace("'", "''")
                    vals.append(f"'{escaped_v}'")
                else:
                    vals.append("NULL")
            
            commands = f"""
CREATE OR REPLACE TABLE {table_name} AS
SELECT {', '.join(f"'{k}' as {k}" for k in rendered_data.keys())} 
WHERE FALSE;

INSERT INTO {table_name} VALUES ({', '.join(vals)});

SELECT * FROM {table_name};
"""
    
    if not commands:
        raise ValueError(
            "duckdb save requires 'commands', 'sql', or 'statement' when "
            "no data mapping provided"
        )
    
    return commands


def handle_duckdb_storage(
    storage_config: Dict[str, Any],
    rendered_data: Dict[str, Any],
    rendered_params: Dict[str, Any],
    statement: Optional[str],
    auth_config: Any,
    credential_ref: Optional[str],
    spec: Dict[str, Any],
    task_with: Optional[Dict[str, Any]],
    context: Dict[str, Any],
    jinja_env: Environment,
    log_event_callback: Optional[Callable]
) -> Dict[str, Any]:
    """
    Handle duckdb storage type delegation.
    
    Args:
        storage_config: Storage configuration
        rendered_data: Rendered data mapping
        rendered_params: Rendered parameters
        statement: SQL statement
        auth_config: Authentication configuration
        credential_ref: Credential reference
        spec: Additional specifications
        task_with: Task with-parameters
        context: Execution context
        jinja_env: Jinja2 environment
        log_event_callback: Event logging callback
        
    Returns:
        Save result envelope
    """
    import base64
    
    # Build DuckDB commands
    commands = build_duckdb_commands(storage_config, statement, rendered_data)
    
    # Base64 encode commands for duckdb plugin (required by plugin interface)
    commands_b64 = base64.b64encode(commands.encode('utf-8')).decode('utf-8')
    
    # Build task config for duckdb plugin
    duck_task = {
        'type': 'duckdb',
        'task': 'save_duckdb',
        'commands_b64': commands_b64,
    }
    
    # Build with-params for duckdb plugin
    duck_with = {}
    try:
        if isinstance(task_with, dict):
            duck_with.update(task_with)
    except Exception:
        pass
    
    # Pass rendered data for template processing
    if isinstance(rendered_data, dict) and rendered_data:
        duck_with['data'] = rendered_data
    elif isinstance(rendered_params, dict) and rendered_params:
        duck_with['data'] = rendered_params
    
    # Pass through auth config
    if isinstance(auth_config, dict) and 'auth' not in duck_with:
        duck_with['auth'] = auth_config
    elif credential_ref and 'auth' not in duck_with:
        duck_with['auth'] = credential_ref
    
    logger.debug("SAVE: Calling duckdb plugin for storage")
    
    # Delegate to duckdb plugin
    try:
        from noetl.plugin.actions.duckdb import execute_duckdb_task
        duck_result = execute_duckdb_task(
            duck_task, context, jinja_env, duck_with, log_event_callback
        )
    except Exception as e:
        logger.error(f"SAVE: Failed delegating to duckdb plugin: {e}")
        duck_result = {"status": "error", "error": str(e)}
    
    # Normalize into save envelope
    if isinstance(duck_result, dict) and duck_result.get('status') == 'success':
        return {
            'status': 'success',
            'data': {
                'saved': 'duckdb',
                'task_result': duck_result.get('data')
            },
            'meta': {
                'storage_kind': 'duckdb',
                'credential_ref': credential_ref,
            }
        }
    else:
        return {
            'status': 'error',
            'data': None,
            'meta': {'storage_kind': 'duckdb'},
            'error': ((duck_result or {}).get('error') 
                     if isinstance(duck_result, dict) else 'duckdb save failed')
        }
