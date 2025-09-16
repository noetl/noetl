"""
Save action executor for NoETL jobs.

Executes a declarative or statement-based save operation on the worker side.
Initial implementation supports event (formerly event_log) "save" by returning the envelope;
other storage kinds can be extended incrementally (postgres/duckdb/etc.).
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
    except Exception:
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
      - storage: { kind: <kind>, credential?: <name>, spec?: {...} }
      - data: <object/list/scalar>
      - mode/key/format (optional)

    Statement mode:
      - storage as above (with dialect for graph/bigquery, etc.)
      - statement: str, params: dict

    Current implementation persists to event_log implicitly (via returned result envelope).
    Heavy external writes will be added per storage kind in future iterations.
    """
    try:
        # Support nested save: { save: { storage, data, statement, params, ... } }
        payload = task_config.get('save') or task_config
        storage = payload.get('storage') or {}
        kind = str((storage or {}).get('kind') or 'event').strip().lower()
        # Spec-defined attributes (parsed now; handling may be added later)
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
        # storage-level attributes (do not echo secrets)
        credential_ref = storage.get('credential') or storage.get('credentialRef')
        spec = storage.get('spec') or {}

        # Render data/params against the execution context
        rendered_data = None
        if data_spec is not None:
            rendered_data = _render_data_mapping(jinja_env, data_spec, context)
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
            from noetl.worker.plugin.postgres import execute_postgres_task as _pg_exec

            # Prepare the SQL to pass to the postgres plugin
            sql_text = None
            if isinstance(statement, str) and statement.strip():
                # If the statement isn't templated, allow :param style by mapping to Jinja params
                sql_text = statement
                if ('{{' not in sql_text) and isinstance(rendered_params, dict) and rendered_params:
                    try:
                        for _k in rendered_params.keys():
                            # Replace only plain tokens :key (very simple heuristic)
                            sql_text = sql_text.replace(f":{_k}", f"{{{{ params.{_k} }}}}")
                    except Exception:
                        pass
            else:
                # Build a basic INSERT (or UPSERT) template from declarative mapping
                if not table or not isinstance(rendered_data, dict):
                    raise ValueError("postgres save requires 'table' and mapping 'data' when no 'statement' provided")
                cols = list(rendered_data.keys())
                # Use Jinja to render values from save_data mapping we pass via with
                # Wrap values in single quotes and escape to ensure valid SQL for text values
                vals = []
                for c in cols:
                    vals.append("{{\"'\" ~ (save_data.%s|string)|replace(\"'\", \"''\") ~ \"'\"}}" % c)
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
            # Provide params/save_data to rendering context for the postgres plugin renderer
            if isinstance(rendered_params, dict) and rendered_params:
                pg_with['params'] = rendered_params
            if isinstance(rendered_data, dict) and rendered_data:
                pg_with['save_data'] = rendered_data

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
