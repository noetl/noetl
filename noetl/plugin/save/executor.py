"""
Save task executor.

Main orchestrator for save tasks that delegates to storage-specific handlers.
"""

from typing import Dict, Any, Optional, Callable
from jinja2 import Environment

from noetl.core.logger import setup_logger
from .config import extract_save_config
from .rendering import render_data_mapping, normalize_params
from .postgres import handle_postgres_storage
from .python import handle_python_storage
from .duckdb import handle_duckdb_storage
from .http import handle_http_storage

logger = setup_logger(__name__, include_location=True)


def execute_save_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Optional[Dict[str, Any]] = None,
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute a 'save' task.
    
    This executor:
    1. Extracts save configuration (storage type, data, auth, etc.)
    2. Renders data and parameters with Jinja2 templates
    3. Delegates to appropriate storage handler based on storage type
    4. Returns normalized save result envelope
    
    Expected task_config keys (declarative):
    
    Flat structure (backward compatible):
      - storage: <string> (e.g. 'postgres', 'event_log', 'duckdb')
      - auth: <string|dict> (credential reference or auth config)
      - data: <object/list/scalar>
      - table: <string> (for database storage)
      - mode/key/format (optional)

    Nested structure (recommended):
      - storage:
          type: <string> (e.g. 'postgres', 'duckdb', 'http', 'python')
          data: <object/list/scalar>
          auth: <string|dict> (credential reference or auth config)
          table: <string> (for database storage)
          mode/key/format (optional)

    Statement mode (both structures):
      - storage: <string> OR { type: <string>, statement: <string>, params: <dict>, ... }
      - auth: <string|dict> (credential reference or auth config)

    Current implementation persists to event_log implicitly (via returned result envelope).
    Heavy external writes are delegated to storage-specific handlers.
    
    Args:
        task_config: Task configuration
        context: Execution context
        jinja_env: Jinja2 environment
        task_with: With-parameters
        log_event_callback: Optional event logging callback
        
    Returns:
        Save result dictionary with keys:
        - status: 'success' or 'error'
        - data: Save result data (if success)
        - meta: Metadata about storage operation
        - error: Error message (if error)
    """
    try:
        # Step 1: Extract save configuration
        config = extract_save_config(task_config)
        
        kind = config['kind']
        storage_config = config['storage_config']
        data_spec = config['data_spec']
        statement = config['statement']
        params = config['params']
        mode = config['mode']
        key_cols = config['key_cols']
        fmt = config['fmt']
        table = config['table']
        batch = config['batch']
        chunk_size = config['chunk_size']
        concurrency = config['concurrency']
        auth_config = config['auth_config']
        credential_ref = config['credential_ref']
        spec = config['spec']
        
        # Step 2: Render data/params against the execution context
        rendered_data = None
        if data_spec is not None:
            rendered_data = render_data_mapping(jinja_env, data_spec, context)
        
        # Prefer canonical data mapping; keep params for legacy only
        rendered_params = (render_data_mapping(jinja_env, params, context) 
                          if params else {})
        
        # Normalize complex param values (dict/list) to JSON strings
        rendered_params = normalize_params(rendered_params)
        
        # Step 3: Handle storage kinds
        if kind in ('event', 'event_log', ''):
            # Event log storage (implicit via return envelope)
            result_payload = {
                'saved': 'event',
                'data': rendered_data,
            }
            meta_payload = {
                'storage_kind': kind,
                'credential_ref': credential_ref,
                'save_spec': {
                    'mode': mode,
                    'format': fmt,
                    'key': key_cols,
                    'table': table,
                    'batch': batch,
                    'chunk_size': chunk_size,
                    'concurrency': concurrency,
                    'statement_present': bool(statement),
                    'param_keys': (list(rendered_params.keys()) 
                                  if isinstance(rendered_params, dict) else None),
                }
            }
            return {
                'status': 'success',
                'data': result_payload,
                'meta': meta_payload,
            }
        
        # Chain to the appropriate action plugin based on storage type
        if kind == 'postgres':
            return handle_postgres_storage(
                storage_config, rendered_data, rendered_params, statement,
                table, mode, key_cols, auth_config, credential_ref, spec,
                task_with, context, jinja_env, log_event_callback
            )
        
        elif kind == 'python':
            return handle_python_storage(
                storage_config, rendered_data, rendered_params,
                auth_config, credential_ref, spec,
                task_with, context, jinja_env, log_event_callback
            )
        
        elif kind == 'duckdb':
            return handle_duckdb_storage(
                storage_config, rendered_data, rendered_params, statement,
                auth_config, credential_ref, spec,
                task_with, context, jinja_env, log_event_callback
            )
        
        elif kind == 'http':
            return handle_http_storage(
                storage_config, rendered_data, rendered_params,
                auth_config, credential_ref, spec,
                task_with, context, jinja_env, log_event_callback
            )
        
        else:
            raise ValueError(f"Unsupported save storage type: {kind}")
            
    except Exception as e:
        logger.exception(f"Error executing save task: {e}")
        return {
            'status': 'error',
            'data': None,
            'meta': {'storage_kind': kind if 'kind' in locals() else 'unknown'},
            'error': str(e)
        }
