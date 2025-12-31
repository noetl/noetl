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
from .gcs import handle_gcs_storage

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
    print(f"\n{'='*80}")
    print(f"SINK.EXECUTOR: execute_sink_task CALLED")
    print(f"task_config keys: {list(task_config.keys()) if isinstance(task_config, dict) else type(task_config)}")
    print(f"task_config: {task_config}")
    print(f"{'='*80}\n")
    logger.critical(f"SINK.EXECUTOR: execute_sink_task CALLED | task_config={task_config}")
    
    print(f"[SINK DEBUG] About to check task_config type - isinstance={isinstance(task_config, dict)}")
    print(f"[SINK DEBUG] Context type: {type(context)}")
    print(f"[SINK DEBUG] jinja_env type: {type(jinja_env)}")
    
    # Step 0: Render task_config to resolve any template variables
    # This ensures credential references like "{{ workload.gcs_auth }}" are resolved
    import json
    
    print(f"[SINK DEBUG] Defining render_value function...")
    
    def render_value(value, context, path="root"):
        """Recursively render a value (str, dict, list) with Jinja2."""
        print(f"[SINK DEBUG] render_value called: path={path}, value_type={type(value)}")
        if isinstance(value, str):
            # Check if this is a simple variable reference like "{{ result }}" or "{{ data }}"
            # If so, return the actual value from context instead of string rendering
            stripped = value.strip()
            if stripped.startswith('{{') and stripped.endswith('}}'):
                var_name = stripped[2:-2].strip()
                # Simple variable reference without dots, filters, or operators
                if ' ' not in var_name and '.' not in var_name and '|' not in var_name and '[' not in var_name:
                    if var_name in context:
                        actual_value = context[var_name]
                        print(f"[SINK DEBUG] Using context value directly for {path}: var={var_name}, type={type(actual_value).__name__}")
                        return actual_value
            
            # Otherwise, render as template
            try:
                template = jinja_env.from_string(value)
                rendered = template.render(context)
                print(f"[SINK DEBUG] Rendered {path}: '{value}' -> '{rendered}'")
                return rendered
            except Exception as e:
                print(f"[SINK DEBUG] ERROR rendering {path}: {e}")
                logger.error(f"SINK.EXECUTOR: Failed to render string at {path}: '{value}' | Error: {e}", exc_info=True)
                raise ValueError(f"Template rendering failed at {path}: {e}")
        elif isinstance(value, dict):
            # Recursively render dict values
            return {k: render_value(v, context, f"{path}.{k}") for k, v in value.items()}
        elif isinstance(value, list):
            # Recursively render list items
            return [render_value(item, context, f"{path}[{i}]") for i, item in enumerate(value)]
        else:
            # Return non-string/dict/list values as-is
            return value
    
    # Debug write BEFORE any logic
    try:
        with open('/tmp/sink_executor_entry.txt', 'w') as f:
            f.write(f"execute_sink_task called\n")
            f.write(f"task_config type: {type(task_config)}\n")
            f.write(f"is dict: {isinstance(task_config, dict)}\n")
            f.write(f"context type: {type(context)}\n")
    except Exception as e:
        pass
    
    rendered_task_config = {}
    if isinstance(task_config, dict):
        import sys
        context_keys = list(context.keys()) if isinstance(context, dict) else type(context)
        has_result = 'result' in context if isinstance(context, dict) else 'N/A'
        has_data = 'data' in context if isinstance(context, dict) else 'N/A'
        result_value = context.get('result') if isinstance(context, dict) else 'N/A'
        data_value = context.get('data') if isinstance(context, dict) else 'N/A'
        result_type = type(result_value)
        data_type = type(data_value)
        
        # Log first few items if it's a list
        result_preview = str(result_value)[:200] if result_value != 'N/A' else 'N/A'
        data_preview = str(data_value)[:200] if data_value != 'N/A' else 'N/A'
        
        # Write to file for debugging
        try:
            with open('/tmp/sink_context_debug.txt', 'w') as f:
                f.write(f"Context keys: {context_keys}\n")
                f.write(f"has_result: {has_result}\n")
                f.write(f"has_data: {has_data}\n")
                f.write(f"result_type: {result_type}\n")
                f.write(f"data_type: {data_type}\n")
                f.write(f"result_preview: {result_preview}\n")
                f.write(f"data_preview: {data_preview}\n")
        except:
            pass
        
        print(f"[SINK DEBUG] Context keys: {context_keys}", flush=True)
        print(f"[SINK DEBUG] has_result={has_result} | has_data={has_data}", flush=True)
        print(f"[SINK DEBUG] result_type={result_type} | data_type={data_type}", flush=True)
        
        try:
            # Render dict recursively BEFORE any JSON operations
            print(f"[SINK DEBUG] About to call render_value...")
            rendered_task_config = render_value(task_config, context)
            print(f"[SINK DEBUG] Rendered task config SUCCESS: {rendered_task_config}")
        except Exception as e:
            logger.error(f"SINK.EXECUTOR: Template rendering error: {e}", exc_info=True)
            logger.error(f"SINK.EXECUTOR: Problematic task_config: {task_config}")
            raise ValueError(f"Template rendering failed: {e}")
    else:
        rendered_task_config = task_config
        logger.critical(f"SINK.EXECUTOR: task_config not a dict, using as-is: {type(task_config)}")
    
    # Step 1: Extract sink configuration (now using rendered config)
    print(f"[SINK DEBUG] About to call extract_sink_config...", flush=True)
    print(f"[SINK DEBUG] rendered_task_config: {rendered_task_config}", flush=True)
    
    try:
        config = extract_sink_config(rendered_task_config)
        logger.critical(f"[SINK DEBUG] extract_sink_config SUCCESS")
    except Exception as extract_err:
        logger.critical(f"[SINK DEBUG] extract_sink_config FAILED: {extract_err}", exc_info=True)
        logger.critical(f"[SINK DEBUG] Exception type: {type(extract_err).__name__}, str: '{str(extract_err)}'")
        raise ValueError(f"Sink config extraction failed: {extract_err}")
    
    kind = config['kind']
    logger.critical(f"SINK.EXECUTOR: Extracted sink config | kind={kind}")
    
    try:
        tool_config = config['tool_config']
        logger.critical(f"[SINK DEBUG-1] tool_config OK")
        data_spec = config['data_spec']
        logger.critical(f"[SINK DEBUG-2] data_spec OK")
        statement = config['statement']
        logger.critical(f"[SINK DEBUG-3] statement OK")
        params = config['params']
        logger.critical(f"[SINK DEBUG-4] params OK")
        mode = config['mode']
        logger.critical(f"[SINK DEBUG-5] mode OK")
        key_cols = config['key_cols']
        logger.critical(f"[SINK DEBUG-6] key_cols OK")
        fmt = config['fmt']
        logger.critical(f"[SINK DEBUG-7] fmt OK")
        table = config['table']
        logger.critical(f"[SINK DEBUG-8] table OK")
        batch = config['batch']
        logger.critical(f"[SINK DEBUG-9] batch OK")
        chunk_size = config['chunk_size']
        logger.critical(f"[SINK DEBUG-10] chunk_size OK")
        concurrency = config['concurrency']
        logger.critical(f"[SINK DEBUG-11] concurrency OK")
        auth_config = config['auth_config']
        logger.critical(f"[SINK DEBUG-12] auth_config OK")
        credential_ref = config['credential_ref']
        logger.critical(f"[SINK DEBUG-13] credential_ref OK")
        spec = config['spec']
        logger.critical(f"[SINK DEBUG-14] spec OK - ALL CONFIG KEYS EXTRACTED")
    except Exception as ex:
        logger.critical(f"[SINK DEBUG] EXCEPTION extracting config keys: {ex}", exc_info=True)
        raise
    
    # Step 2: Render data/params against the execution context
    logger.critical(f"[SINK DEBUG-15] About to render data_spec, is_none={data_spec is None}")
    rendered_data = None
    if data_spec is not None:
        logger.critical(f"[SINK DEBUG-16] Calling render_data_mapping...")
        rendered_data = render_data_mapping(jinja_env, data_spec, context)
        logger.critical(f"[SINK DEBUG-17] render_data_mapping SUCCESS")
        logger.critical(f"SINK.EXECUTOR: Rendered data_spec -> rendered_data={rendered_data}")
    
    # Prefer canonical data mapping; keep params for legacy only
    rendered_params = (render_data_mapping(jinja_env, params, context) 
                      if params else {})
    
    # Normalize complex param values (dict/list) to JSON strings
    rendered_params = normalize_params(rendered_params)
    
    # Step 4: Handle tool kinds
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
    
    elif kind == 'gcs':
        logger.info(f"SINK.EXECUTOR: Delegating to GCS handler")
        return handle_gcs_storage(
            tool_config, rendered_data, rendered_params,
            auth_config, credential_ref, spec,
            task_with, context, jinja_env, log_event_callback
        )

    else:
        raise ValueError(f"Unsupported sink tool type: {kind}")
