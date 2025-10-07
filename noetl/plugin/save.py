"""
Save action executor for NoETL jobs.

Executes a declarative or statement-based save operation on the worker side.
Uses flattened save.storage structure (e.g., save.storage: 'postgres').
Supports event_log, postgres, and other storage kinds.
"""

from typing import Dict, Any, Optional, Callable
import os
from jinja2 import Environment

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)

def _pg_exec(pg_task, context, jinja_env, pg_with, log_event_callback):
    """Helper to invoke the Postgres plugin from the save action.
    Keeps the dependency local to avoid import cycles at module import time.
    """
    try:
        from .postgres import execute_postgres_task
        return execute_postgres_task(pg_task, context, jinja_env, pg_with, log_event_callback)
    except Exception as e:
        logger.error(f"SAVE: Failed delegating to postgres plugin: {e}")
        return {"status": "error", "error": str(e)}


def _python_exec(py_task, context, jinja_env, py_with, log_event_callback):
    """Helper to invoke the Python plugin from the save action.
    Keeps the dependency local to avoid import cycles at module import time.
    """
    try:
        from .python import execute_python_task
        return execute_python_task(py_task, context, jinja_env, py_with, log_event_callback)
    except Exception as e:
        logger.error(f"SAVE: Failed delegating to python plugin: {e}")
        return {"status": "error", "error": str(e)}


def _duckdb_exec(duck_task, context, jinja_env, duck_with, log_event_callback):
    """Helper to invoke the DuckDB plugin from the save action.
    Keeps the dependency local to avoid import cycles at module import time.
    """
    try:
        from .duckdb import execute_duckdb_task
        return execute_duckdb_task(duck_task, context, jinja_env, duck_with, log_event_callback)
    except Exception as e:
        logger.error(f"SAVE: Failed delegating to duckdb plugin: {e}")
        return {"status": "error", "error": str(e)}


def _http_exec(http_task, context, jinja_env, http_with, log_event_callback):
    """Helper to invoke the HTTP plugin from the save action.
    Keeps the dependency local to avoid import cycles at module import time.
    """
    try:
        from .http import execute_http_task
        return execute_http_task(http_task, context, jinja_env, http_with, log_event_callback)
    except Exception as e:
        logger.error(f"SAVE: Failed delegating to http plugin: {e}")
        return {"status": "error", "error": str(e)}


def _render_data_mapping(jinja_env: Environment, mapping: Any, context: Dict[str, Any]) -> Any:
    try:
        # Lazy import to avoid circulars
        from noetl.core.dsl.render import render_template
        return render_template(jinja_env, mapping, context, rules=None, strict_keys=False)
    except Exception as render_err:
        # Log the rendering failure for debugging
        logger.warning(f"SAVE: Template rendering failed for mapping {mapping}, falling back to unrendered: {render_err}")
        logger.debug(f"SAVE: Available context keys: {list(context.keys()) if isinstance(context, dict) else type(context)}")
        # Fallback: return as-is if rendering fails
        return mapping


def execute_save_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Optional[Dict[str, Any]] = None,
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute a 'save' task.

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
    Heavy external writes will be added per storage kind in future iterations.
    """
    try:
        # Support nested save: { save: { storage, data, statement, params, ... } }
        payload = task_config.get('save') or task_config
        
        # Get storage - support both flat string and nested structure
        storage_value = payload.get('storage') or 'event'
        
        # Parse storage configuration
        storage_config = {}
        if isinstance(storage_value, str):
            # Flat structure: storage: "postgres"
            kind = storage_value.strip().lower()
        elif isinstance(storage_value, dict):
            # Nested structure: storage: { type: "postgres", ... }
            kind = storage_value.get('type', 'event').strip().lower()
            storage_config = storage_value.copy()
            # Remove 'type' from config as it's already extracted
            storage_config.pop('type', None)
        else:
            raise ValueError("save.storage must be a string (e.g., 'postgres') or dict with 'type' field (e.g., {type: 'postgres', ...})")
            
        # Get save configuration attributes
        # Prefer nested storage.data over top-level data for nested structure
        if isinstance(storage_value, dict) and 'data' in storage_value:
            data_spec = storage_value.get('data')
        else:
            data_spec = payload.get('data')
            
        # Statement can come from nested storage or top-level
        if isinstance(storage_value, dict) and 'statement' in storage_value:
            statement = storage_value.get('statement')
        else:
            statement = payload.get('statement')
        # Get configuration parameters, preferring nested storage over top-level
        def get_config_value(key, default=None):
            if isinstance(storage_value, dict) and key in storage_value:
                return storage_value.get(key, default)
            return payload.get(key, default)
            
        params = get_config_value('params', {})
        mode = get_config_value('mode')
        key_cols = get_config_value('key') or get_config_value('keys')
        fmt = get_config_value('format')
        table = get_config_value('table')
        batch = get_config_value('batch')
        chunk_size = get_config_value('chunk_size') or get_config_value('chunksize')
        concurrency = get_config_value('concurrency')
        
        # Get auth configuration, preferring nested storage auth over top-level
        auth_config = get_config_value('auth')
        credential_ref = None
        
        # Handle auth configuration
        if isinstance(auth_config, dict):
            # Unified auth dictionary
            logger.debug("SAVE: Using unified auth dictionary")
        elif isinstance(auth_config, str):
            # String reference to credential
            credential_ref = auth_config
            logger.debug("SAVE: Using auth string reference")
        
        # Get spec configuration, preferring nested storage spec over top-level
        spec = get_config_value('spec', {})

        # Render data/params against the execution context
        rendered_data = None
        if data_spec is not None:
            rendered_data = _render_data_mapping(jinja_env, data_spec, context)
        # Prefer canonical data mapping; keep params for legacy only
        rendered_params = _render_data_mapping(jinja_env, params, context) if params else {}
        # Normalize complex param values (dict/list) to JSON strings to ensure
        # safe embedding into SQL statements when using {{ params.* }} in strings.
        try:
            if isinstance(rendered_params, dict):
                import json as _json
                from noetl.core.common import DateTimeEncoder as _Enc
                for _k, _v in list(rendered_params.items()):
                    if isinstance(_v, (dict, list)):
                        try:
                            rendered_params[_k] = _json.dumps(_v, cls=_Enc)
                        except Exception:
                            rendered_params[_k] = str(_v)
        except Exception:
            pass

        # Handle storage kinds - initial support for event/event_log
        if kind in ('event', 'event_log', ''):
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
                    'param_keys': list(rendered_params.keys()) if isinstance(rendered_params, dict) else None,
                }
            }
            return {
                'status': 'success',
                'data': result_payload,
                'meta': meta_payload,
            }

        # Chain to the appropriate action plugin based on storage type
        if kind == 'postgres':
            return _handle_postgres_storage(
                storage_config, rendered_data, rendered_params, statement, 
                table, mode, key_cols, auth_config, credential_ref, spec,
                task_with, context, jinja_env, log_event_callback
            )
        
        elif kind == 'python':
            return _handle_python_storage(
                storage_config, rendered_data, rendered_params, 
                auth_config, credential_ref, spec,
                task_with, context, jinja_env, log_event_callback
            )
        
        elif kind == 'duckdb':
            return _handle_duckdb_storage(
                storage_config, rendered_data, rendered_params, statement,
                auth_config, credential_ref, spec,
                task_with, context, jinja_env, log_event_callback
            )
        
        elif kind == 'http':
            return _handle_http_storage(
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


def _handle_postgres_storage(storage_config, rendered_data, rendered_params, statement, 
                           table, mode, key_cols, auth_config, credential_ref, spec,
                           task_with, context, jinja_env, log_event_callback):
    """Handle postgres storage type delegation."""
    # Resolve credential alias if provided (best-effort)
    try:
        if credential_ref:
            server_url = os.getenv('NOETL_SERVER_URL', 'http://localhost:8082').rstrip('/')
            if not server_url.endswith('/api'):
                server_url = server_url + '/api'
            cred_key = str(credential_ref)
            import httpx
            url = f"{server_url}/credentials/{cred_key}?include_data=true"
            with httpx.Client(timeout=5.0) as _c:
                _r = _c.get(url)
                if _r.status_code == 200:
                    body = _r.json() or {}
                    cdata = body.get('data') or {}
                    if isinstance(cdata, dict):
                        merged = dict(cdata)
                        if isinstance(spec, dict):
                            for k, v in spec.items():
                                if v is not None:
                                    merged[k] = v
                        spec = merged
    except Exception:
        pass
    
    import base64

    # Prepare the SQL to pass to the postgres plugin
    sql_text = None
    if isinstance(statement, str) and statement.strip():
        # If the statement isn't templated, allow :name style by mapping to Jinja data
        sql_text = statement
        # Use explicit data mapping to render binds; fall back to legacy params
        bind_keys = []
        try:
            if isinstance(rendered_data, dict):
                bind_keys = list(rendered_data.keys())
            elif isinstance(rendered_params, dict):
                bind_keys = list(rendered_params.keys())
        except Exception:
            bind_keys = []
        if ('{{' not in sql_text) and bind_keys:
            try:
                for _k in bind_keys:
                    sql_text = sql_text.replace(f":{_k}", f"{{{{ data.{_k} }}}}")
            except Exception:
                pass
    else:
        # Build a basic INSERT (or UPSERT) template from declarative mapping
        if not table or not isinstance(rendered_data, dict):
            raise ValueError("postgres save requires 'table' and mapping 'data' when no 'statement' provided")
        cols = list(rendered_data.keys())
        # Use Jinja to render values from data mapping we pass via with
        # Wrap values in single quotes and escape to ensure valid SQL for text values
        vals = []
        for c in cols:
            vals.append("{{\"'\" ~ (data.%s|string)|replace(\"'\", \"''\") ~ \"'\"}}" % c)
        insert_sql = f"INSERT INTO {table} (" + ", ".join(cols) + ") VALUES (" + ", ".join(vals) + ")"
        if (mode or '').lower() == 'upsert' and key_cols:
            key_list = key_cols if isinstance(key_cols, (list, tuple)) else [key_cols]
            set_parts = []
            for c in cols:
                if c not in key_list:
                    set_parts.append(f"{c} = EXCLUDED.{c}")
            if set_parts:
                insert_sql += f" ON CONFLICT (" + ", ".join(key_list) + ") DO UPDATE SET " + ", ".join(set_parts)
            else:
                insert_sql += f" ON CONFLICT (" + ", ".join(key_list) + ") DO NOTHING"
        sql_text = insert_sql

    # Build task config and with-params for postgres plugin
    pg_task = {
        'type': 'postgres',
        'task': 'save_postgres',
        'command_b64': base64.b64encode(sql_text.encode('utf-8')).decode('ascii'),
    }

    # Start with provided 'with' for DB creds passthrough, then overlay storage.spec
    pg_with = {}
    try:
        if isinstance(task_with, dict):
            pg_with.update(task_with)
    except Exception:
        pass
    
    # Map storage spec to expected postgres plugin keys
    try:
        if isinstance(spec, dict):
            # Allow direct connection string when provided
            if spec.get('dsn'):
                pg_with['db_conn_string'] = spec.get('dsn')
            for src, dst in (
                ('db_host','db_host'), ('host','db_host'), ('pg_host','db_host'),
                ('db_port','db_port'), ('port','db_port'),
                ('db_user','db_user'), ('user','db_user'),
                ('db_password','db_password'), ('password','db_password'),
                ('db_name','db_name'), ('dbname','db_name'),
            ):
                if spec.get(src) is not None and not pg_with.get(dst):
                    pg_with[dst] = spec.get(src)
    except Exception:
        pass
    
    # Provide data to rendering context for the postgres plugin renderer
    # Canonical mapping: pass as 'data' for the postgres plugin to render
    if isinstance(rendered_data, dict) and rendered_data:
        pg_with['data'] = rendered_data
    elif isinstance(rendered_params, dict) and rendered_params:
        # Legacy: still allow 'params' to be passed for old statements
        pg_with['data'] = rendered_params

    # Migration helper: if the statement still refers to params.*, rewrite to data.*
    try:
        if isinstance(sql_text, str) and ('params.' in sql_text):
            sql_text = sql_text.replace('params.', 'data.')
            pg_task['command_b64'] = base64.b64encode(sql_text.encode('utf-8')).decode('ascii')
    except Exception:
        pass

    # Pass through unified auth or legacy credential reference
    if isinstance(auth_config, dict) and 'auth' not in pg_with:
        pg_with['auth'] = auth_config
    elif credential_ref and 'auth' not in pg_with:
        pg_with['auth'] = credential_ref

    # DEBUG: Log context keys before calling postgres plugin
    logger.debug(f"SAVE: Calling postgres plugin with context keys: {list(context.keys()) if isinstance(context, dict) else type(context)}")
    if isinstance(context, dict) and 'result' in context:
        result_val = context['result']
        logger.debug(f"SAVE: Found 'result' in context - type: {type(result_val)}, keys: {list(result_val.keys()) if isinstance(result_val, dict) else 'not dict'}")
    else:
        logger.debug("SAVE: No 'result' found in context")
    
    pg_result = _pg_exec(pg_task, context, jinja_env, pg_with, log_event_callback)
    # Normalize into save envelope
    if isinstance(pg_result, dict) and pg_result.get('status') == 'success':
        return {
            'status': 'success',
            'data': {
                'saved': 'postgres',
                'table': table,
                'task_result': pg_result.get('data')
            },
            'meta': {
                'storage_kind': 'postgres',
                'credential_ref': credential_ref,
                'save_spec': {
                    'mode': mode,
                    'key': key_cols,
                    'statement_present': bool(statement),
                    'param_keys': list(rendered_params.keys()) if isinstance(rendered_params, dict) else None,
                }
            }
        }
    else:
        return {
            'status': 'error',
            'data': None,
            'meta': {'storage_kind': 'postgres'},
            'error': (pg_result or {}).get('error') if isinstance(pg_result, dict) else 'postgres save failed'
        }


def _handle_python_storage(storage_config, rendered_data, rendered_params,
                         auth_config, credential_ref, spec,
                         task_with, context, jinja_env, log_event_callback):
    """Handle python storage type delegation."""
    # Extract code from storage config or use default data serialization
    code = storage_config.get('code') or storage_config.get('script')
    
    if not code:
        # Default python code to serialize data to JSON
        code = '''
def main(data):
    import json
    result = json.dumps(data, indent=2, default=str)
    print(f"PYTHON_SAVE: {result}")
    return {"status": "success", "data": {"saved_data": data, "serialized": result}}
'''
    
    import base64
    
    # Build task config for python plugin
    py_task = {
        'type': 'python',
        'task': 'save_python',
        'code_b64': base64.b64encode(code.encode('utf-8')).decode('ascii'),
    }
    
    # Build with-params for python plugin
    py_with = {}
    try:
        if isinstance(task_with, dict):
            py_with.update(task_with)
    except Exception:
        pass
    
    # Pass rendered data as input to python code
    if isinstance(rendered_data, dict) and rendered_data:
        py_with['data'] = rendered_data
    elif isinstance(rendered_params, dict) and rendered_params:
        py_with['data'] = rendered_params
    else:
        py_with['data'] = {}
    
    # Pass through auth config
    if isinstance(auth_config, dict) and 'auth' not in py_with:
        py_with['auth'] = auth_config
    elif credential_ref and 'auth' not in py_with:
        py_with['auth'] = credential_ref
    
    logger.debug(f"SAVE: Calling python plugin for storage")
    py_result = _python_exec(py_task, context, jinja_env, py_with, log_event_callback)
    
    # Normalize into save envelope
    if isinstance(py_result, dict) and py_result.get('status') == 'success':
        return {
            'status': 'success',
            'data': {
                'saved': 'python',
                'task_result': py_result.get('data')
            },
            'meta': {
                'storage_kind': 'python',
                'credential_ref': credential_ref,
            }
        }
    else:
        return {
            'status': 'error',
            'data': None,
            'meta': {'storage_kind': 'python'},
            'error': (py_result or {}).get('error') if isinstance(py_result, dict) else 'python save failed'
        }


def _handle_duckdb_storage(storage_config, rendered_data, rendered_params, statement,
                         auth_config, credential_ref, spec,
                         task_with, context, jinja_env, log_event_callback):
    """Handle duckdb storage type delegation."""
    # Extract commands/SQL from storage config or build from data
    commands = storage_config.get('commands') or storage_config.get('sql') or statement
    
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
        raise ValueError("duckdb save requires 'commands', 'sql', or 'statement' when no data mapping provided")
    
    # Build task config for duckdb plugin
    duck_task = {
        'type': 'duckdb',
        'task': 'save_duckdb',
        'commands': commands,
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
    
    logger.debug(f"SAVE: Calling duckdb plugin for storage")
    duck_result = _duckdb_exec(duck_task, context, jinja_env, duck_with, log_event_callback)
    
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
            'error': (duck_result or {}).get('error') if isinstance(duck_result, dict) else 'duckdb save failed'
        }


def _handle_http_storage(storage_config, rendered_data, rendered_params,
                       auth_config, credential_ref, spec,
                       task_with, context, jinja_env, log_event_callback):
    """Handle http storage type delegation."""
    # Extract HTTP config from storage config
    endpoint = storage_config.get('endpoint') or storage_config.get('url')
    method = storage_config.get('method', 'POST')
    headers = storage_config.get('headers', {})
    
    if not endpoint:
        raise ValueError("http save requires 'endpoint' or 'url' in storage config")
    
    # Build task config for http plugin
    http_task = {
        'type': 'http',
        'task': 'save_http',
        'endpoint': endpoint,
        'method': method,
        'headers': headers,
    }
    
    # Use rendered data as request data/payload
    if isinstance(rendered_data, dict) and rendered_data:
        http_task['data'] = rendered_data
    elif isinstance(rendered_params, dict) and rendered_params:
        http_task['data'] = rendered_params
    
    # Build with-params for http plugin
    http_with = {}
    try:
        if isinstance(task_with, dict):
            http_with.update(task_with)
    except Exception:
        pass
    
    # Pass through auth config
    if isinstance(auth_config, dict) and 'auth' not in http_with:
        http_with['auth'] = auth_config
    elif credential_ref and 'auth' not in http_with:
        http_with['auth'] = credential_ref
    
    logger.debug(f"SAVE: Calling http plugin for storage to {endpoint}")
    http_result = _http_exec(http_task, context, jinja_env, http_with, log_event_callback)
    
    # Normalize into save envelope
    if isinstance(http_result, dict) and http_result.get('status') == 'success':
        return {
            'status': 'success',
            'data': {
                'saved': 'http',
                'endpoint': endpoint,
                'task_result': http_result.get('data')
            },
            'meta': {
                'storage_kind': 'http',
                'credential_ref': credential_ref,
            }
        }
    else:
        return {
            'status': 'error',
            'data': None,
            'meta': {'storage_kind': 'http'},
            'error': (http_result or {}).get('error') if isinstance(http_result, dict) else 'http save failed'
        }


__all__ = ['execute_save_task']
