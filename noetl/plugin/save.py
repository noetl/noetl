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
      - storage: <string> (e.g. 'postgres', 'event_log', 'duckdb')
      - auth: <string|dict> (credential reference or auth config)
      - data: <object/list/scalar>
      - table: <string> (for database storage)
      - mode/key/format (optional)

    Statement mode:
      - storage: <string> (database type)
      - auth: <string|dict> (credential reference or auth config)
      - statement: str, params: dict

    Current implementation persists to event_log implicitly (via returned result envelope).
    Heavy external writes will be added per storage kind in future iterations.
    """
    try:
        # Support nested save: { save: { storage, data, statement, params, ... } }
        payload = task_config.get('save') or task_config
        
        # Get storage - must be a string (flattened structure)
        storage_value = payload.get('storage') or 'event'
        if isinstance(storage_value, str):
            kind = storage_value.strip().lower()
        else:
            raise ValueError("save.storage must be a string enum (e.g., 'postgres', 'event_log'). Legacy save.storage.kind structure is no longer supported.")
            
        # Get save configuration attributes  
        data_spec = payload.get('data')
        statement = payload.get('statement')
        params = payload.get('params') or {}
        mode = payload.get('mode')
        key_cols = payload.get('key') or payload.get('keys')
        fmt = payload.get('format')
        table = payload.get('table')
        batch = payload.get('batch')
        chunk_size = payload.get('chunk_size') or payload.get('chunksize')
        concurrency = payload.get('concurrency')
        
        # Get auth configuration (top-level only)
        auth_config = payload.get('auth')
        credential_ref = None
        
        # Handle auth configuration
        if isinstance(auth_config, dict):
            # Unified auth dictionary
            logger.debug("SAVE: Using unified auth dictionary")
        elif isinstance(auth_config, str):
            # String reference to credential
            credential_ref = auth_config
            logger.debug("SAVE: Using auth string reference")
        
        # Get spec configuration
        spec = payload.get('spec') or {}

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

        # Chain to the Postgres worker plugin rather than re-implementing
        if kind == 'postgres':
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
            from noetl.plugin.postgres import execute_postgres_task as _pg_exec

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
            pg_with: Dict[str, Any] = {}
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
                        'storage_kind': kind,
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
                    'meta': {'storage_kind': kind},
                    'error': (pg_result or {}).get('error') if isinstance(pg_result, dict) else 'postgres save failed'
                }

        # Placeholder behavior for unsupported kinds: report not-implemented
        return {
            'status': 'error',
            'data': None,
            'meta': {
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
            },
            'error': f"save task: storage kind '{kind}' not implemented yet"
        }
    except Exception as e:
        logger.exception("SAVE: Exception during save task execution")
        return {
            'status': 'error',
            'data': None,
            'meta': None,
            'error': str(e)
        }


__all__ = ['execute_save_task']
