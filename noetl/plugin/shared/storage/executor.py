"""
Sink task executor.

Main orchestrator for sink tasks that delegates to tool-specific handlers.
"""

from typing import Dict, Any, Optional, Callable
from jinja2 import Environment

from noetl.core.logger import setup_logger
from .config import extract_sink_config
from .rendering import render_data_mapping, normalize_params
from .postgres import handle_postgres_storage
from .python import handle_python_storage
from .duckdb import handle_duckdb_storage
from .http import handle_http_storage

logger = setup_logger(__name__, include_location=True)


def execute_sink_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Optional[Dict[str, Any]] = None,
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute a 'sink' task.
    
    This executor:
    1. Extracts sink configuration (tool type, data, auth, etc.)
    2. Renders data and parameters with Jinja2 templates
    3. Delegates to appropriate tool handler based on tool type
    4. Returns normalized sink result envelope
    
    Expected task_config keys (declarative):
    
    Flat structure (backward compatible):
      - tool: <string> (e.g. 'postgres', 'event_log', 'duckdb')
      - auth: <string|dict> (credential reference or auth config)
      - data: <object/list/scalar>
      - table: <string> (for database tools)
      - mode/key/format (optional)

    Nested structure (recommended):
      - tool:
          type: <string> (e.g. 'postgres', 'duckdb', 'http', 'python')
          data: <object/list/scalar>
          auth: <string|dict> (credential reference or auth config)
          table: <string> (for database tools)
          mode/key/format (optional)

    Statement mode (both structures):
      - tool: <string> OR { type: <string>, statement: <string>, params: <dict>, ... }
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
        Sink result dictionary with keys:
        - status: 'success' or 'error'
        - data: Sink result data (if success)
        - meta: Metadata about tool operation
        - error: Error message (if error)
    """
    logger.critical("SINK.EXECUTOR: execute_sink_task CALLED")
    logger.critical(f"SINK.EXECUTOR: task_config={task_config}")
    
    try:
        # Step 1: Extract sink configuration
        config = extract_sink_config(task_config)
        
        kind = config['kind']
        logger.critical(f"SINK.EXECUTOR: Extracted sink config with kind={kind}")
        logger.critical(f"SINK.EXECUTOR: Full config={config}")
        tool_config = config['tool_config']
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
            logger.critical(f"SINK.EXECUTOR: Rendered data_spec -> rendered_data={rendered_data}")
        
        # Prefer canonical data mapping; keep params for legacy only
        rendered_params = (render_data_mapping(jinja_env, params, context) 
                          if params else {})
        
        # Normalize complex param values (dict/list) to JSON strings
        rendered_params = normalize_params(rendered_params)
        
        # Step 3: Handle tool kinds
        if kind in ('event', 'event_log', ''):
            # Event log tool (implicit via return envelope)
            result_payload = {
                'saved': 'event',
                'data': rendered_data,
            }
            meta_payload = {
                'tool_kind': kind,
                'credential_ref': credential_ref,
                'sink_spec': {
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
        
        # Chain to the appropriate action plugin based on tool type
        if kind == 'postgres':
            logger.info(f"SINK.EXECUTOR: Delegating to postgres handler with table={table}, mode={mode}")
            return handle_postgres_storage(
                tool_config, rendered_data, rendered_params, statement,
                table, mode, key_cols, auth_config, credential_ref, spec,
                task_with, context, jinja_env, log_event_callback
            )
        
        elif kind == 'python':
            return handle_python_storage(
                tool_config, rendered_data, rendered_params,
                auth_config, credential_ref, spec,
                task_with, context, jinja_env, log_event_callback
            )
        
        elif kind == 'duckdb':
            return handle_duckdb_storage(
                tool_config, rendered_data, rendered_params, statement,
                auth_config, credential_ref, spec,
                task_with, context, jinja_env, log_event_callback
            )
        
        elif kind == 'http':
            import asyncio
            return asyncio.run(handle_http_storage(
                tool_config, rendered_data, rendered_params,
                auth_config, credential_ref, spec,
                task_with, context, jinja_env, log_event_callback
            ))
        
        else:
            raise ValueError(f"Unsupported sink tool type: {kind}")
            
    except Exception as e:
        logger.exception(f"Error executing sink task: {e}")
        return {
            'status': 'error',
            'data': None,
            'meta': {'tool_kind': kind if 'kind' in locals() else 'unknown'},
            'error': str(e)
        }
