"""
Save action executor for NoETL jobs.

Executes a declarative or statement-based save operation on the worker side.
Initial implementation supports event_log "save" by returning the envelope;
other storage kinds can be extended incrementally (postgres/duckdb/etc.).
"""

from typing import Dict, Any, Optional, Callable
from jinja2 import Environment

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


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
        kind = str((storage or {}).get('kind') or 'event_log').strip().lower()
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

        # Handle storage kinds - initial support for event_log only
        if kind in ('event_log', ''):
            result_payload = {
                'saved': 'event_log',
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

        # Demonstration wiring: postgres save
        if kind == 'postgres':
            try:
                import psycopg
                from psycopg import sql as _sql
            except Exception as e:
                return {
                    'status': 'error',
                    'data': None,
                    'meta': {'storage_kind': kind},
                    'error': f'psycopg not available: {e}'
                }

            # Build connection string from spec or env
            dsn = spec.get('dsn')
            if not dsn:
                host = spec.get('db_host') or spec.get('host') or spec.get('pg_host') or os.environ.get('POSTGRES_HOST')
                port = spec.get('db_port') or spec.get('port') or os.environ.get('POSTGRES_PORT', '5432')
                user = spec.get('db_user') or spec.get('user') or os.environ.get('POSTGRES_USER')
                password = spec.get('db_password') or spec.get('password') or os.environ.get('POSTGRES_PASSWORD')
                dbname = spec.get('db_name') or spec.get('dbname') or os.environ.get('POSTGRES_DB')
                parts = []
                if host: parts.append(f"host={host}")
                if port: parts.append(f"port={port}")
                if user: parts.append(f"user={user}")
                if password: parts.append(f"password={password}")
                if dbname: parts.append(f"dbname={dbname}")
                dsn = ' '.join(parts)

            rows_affected = None
            with psycopg.connect(dsn) as conn:
                with conn.cursor() as cur:
                    if statement:
                        # Convert :name params to %(name)s for psycopg
                        stmt = str(statement)
                        rp = rendered_params if isinstance(rendered_params, dict) else {}
                        for k in rp.keys():
                            stmt = stmt.replace(f":{k}", f"%({k})s")
                        cur.execute(stmt, rp)
                        rows_affected = cur.rowcount
                    else:
                        # Declarative insert/upsert
                        if not table or not isinstance(rendered_data, dict):
                            raise ValueError("postgres declarative save requires 'table' and mapping 'data'")
                        cols = list(rendered_data.keys())
                        placeholders = [ _sql.Placeholder(c) for c in cols ]
                        insert_sql = _sql.SQL("INSERT INTO {tbl} ({cols}) VALUES ({vals})").format(
                            tbl=_sql.Identifier(str(table)),
                            cols=_sql.SQL(', ').join(map(_sql.Identifier, cols)),
                            vals=_sql.SQL(', ').join(placeholders)
                        )
                        if (mode or '').lower() == 'upsert' and key_cols:
                            key_list = key_cols if isinstance(key_cols, (list, tuple)) else [key_cols]
                            # non-key columns updated from EXCLUDED
                            upd_cols = [c for c in cols if c not in key_list]
                            if upd_cols:
                                on_conflict = _sql.SQL(" ON CONFLICT ({keys}) DO UPDATE SET {updates}").format(
                                    keys=_sql.SQL(', ').join(map(_sql.Identifier, key_list)),
                                    updates=_sql.SQL(', ').join(
                                        _sql.Composed([
                                            _sql.Identifier(c), _sql.SQL(" = EXCLUDED."), _sql.Identifier(c)
                                        ]) for c in upd_cols
                                    )
                                )
                            else:
                                on_conflict = _sql.SQL(" ON CONFLICT ({keys}) DO NOTHING").format(
                                    keys=_sql.SQL(', ').join(map(_sql.Identifier, key_list))
                                )
                            query = _sql.Composed([insert_sql, on_conflict])
                        else:
                            query = insert_sql
                        cur.execute(query, rendered_data)
                        rows_affected = cur.rowcount

            return {
                'status': 'success',
                'data': {
                    'saved': 'postgres',
                    'table': table,
                    'rows_affected': rows_affected,
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
