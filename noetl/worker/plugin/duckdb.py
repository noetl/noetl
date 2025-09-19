"""
DuckDB action executor for NoETL jobs.
"""

import os
import re
import uuid
import datetime
import json
import time
import threading
import traceback
"""
DuckDB action executor for NoETL jobs.
"""

import os
import re
import uuid
import datetime
import json
import time
import threading
from contextlib import contextmanager
from typing import Dict, Any, Optional, Callable
from decimal import Decimal
from jinja2 import Environment

from noetl.core.dsl.render import render_template
from noetl.core.common import DateTimeEncoder
from noetl.core.logger import setup_logger

import duckdb
import httpx

from noetl.worker.secrets import fetch_credentials_by_keys, fetch_credential_by_key
from noetl.worker.plugin._auth import (
    resolve_auth_map, get_duckdb_secrets, get_required_extensions
)

logger = setup_logger(__name__, include_location=True)

_duckdb_connections = {}
_connection_lock = threading.Lock()


def _render_deep(jenv, ctx, obj):
    """Deep Jinja2 rendering of nested data structures."""
    if jenv is None: 
        return obj
    if isinstance(obj, str):
        return jenv.from_string(obj).render(ctx or {})
    if isinstance(obj, dict):
        return {k: _render_deep(jenv, ctx, v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return type(obj)(_render_deep(jenv, ctx, v) for v in obj)
    return obj


def _escape_sql(s):
    """Escape single quotes in SQL string literals."""
    return str(s or "").replace("'", "''")


def _infer_object_store_scope(params, service):
    """Infer cloud storage scope from output_uri_base parameter."""
    base = (params or {}).get("output_uri_base") or ""
    if not isinstance(base, str): 
        return None
    if service == "gcs" and (base.startswith("gs://") or base.startswith("gcs://")):
        # keep bucket only (gs://bucket)
        parts = base.split("/")
        return "/".join(parts[:3])
    return None


def _build_duckdb_secret_prelude(task_config, params, jinja_env, context, fetch_fn):
    """
    Build DuckDB CREATE SECRET prelude statements from credentials configuration.
    
    Args:
        task_config: Task configuration containing credentials
        params: Rendered 'with' parameters dictionary
        jinja_env: Jinja2 environment for template rendering
        context: Context for rendering templates
        fetch_fn: Function to fetch credentials by key
        
    Returns:
        List of SQL statements to create DuckDB secrets and load extensions
    """
    params = dict(params or {})
    step_creds = (task_config or {}).get("credentials") or {}
    with_creds = (params.get("credentials") or {})
    creds_cfg = {**step_creds, **with_creds}
    creds_cfg = _render_deep(jinja_env, context, creds_cfg)
    prelude = []
    need_httpfs = False
    need_pg = False

    for alias, spec in (creds_cfg or {}).items():
        if not isinstance(spec, dict): 
            continue
        key = spec.get("key")
        rec = {}
        if key:
            rec = fetch_fn(key) or {}
        merged = {**rec, **{k:v for k,v in spec.items() if k != "key"}}
        service = (merged.get("service") or merged.get("type") or "").lower()

        # Infer service by fields if not provided
        if not service:
            if {"db_host","db_name","db_user","db_password"} & set(merged.keys()):
                service = "postgres"
            elif {"key_id","secret_key"} <= set(merged.keys()):
                service = "gcs"

        secret_name = merged.get("secret_name") or alias

        if service == "gcs":
            need_httpfs = True
            key_id = merged.get("key_id")
            secret = merged.get("secret_key")
            if not (key_id and secret):
                raise ValueError(f"GCS secret '{alias}' missing key_id/secret_key (HMAC required).")
            scope = merged.get("scope") or _infer_object_store_scope(params, "gcs")
            stmt = (
                f"CREATE OR REPLACE SECRET {secret_name} (\n"
                f"  TYPE gcs,\n"
                f"  KEY_ID '{_escape_sql(key_id)}',\n"
                f"  SECRET '{_escape_sql(secret)}'"
                + (f",\n  SCOPE '{_escape_sql(scope)}'" if scope else "")
                + "\n);"
            )
            prelude.append(stmt)

        elif service == "postgres":
            need_pg = True
            host = merged.get("db_host") or merged.get("host")
            port = int(merged.get("db_port") or merged.get("port") or 5432)
            db   = merged.get("db_name") or merged.get("database") or merged.get("dbname")
            user = merged.get("db_user") or merged.get("user") or merged.get("username")
            pwd  = merged.get("db_password") or merged.get("password")
            sslm = merged.get("sslmode")
            for val in (host, db, user, pwd):
                if val in (None, ""):
                    raise ValueError(f"Postgres secret '{alias}' incomplete (need host, db_name, db_user, db_password).")
            stmt = (
                f"CREATE OR REPLACE SECRET {secret_name} (\n"
                f"  TYPE postgres,\n"
                f"  HOST '{_escape_sql(host)}',\n"
                f"  PORT {port},\n"
                f"  DATABASE '{_escape_sql(db)}',\n"
                f"  USER '{_escape_sql(user)}',\n"
                f"  PASSWORD '{_escape_sql(pwd)}'"
                + (f",\n  SSLMODE '{_escape_sql(sslm)}'" if sslm else "")
                + "\n);"
            )
            prelude.append(stmt)

    if need_httpfs:
        prelude.insert(0, "INSTALL httpfs; LOAD httpfs;")
    if need_pg:
        prelude.insert(0, "INSTALL postgres; LOAD postgres;")

    return prelude


@contextmanager
def get_duckdb_connection(duckdb_file_path):
    """Context manager for shared DuckDB connections to maintain attachments"""
    logger.debug("=== DUCKDB.GET_DUCKDB_CONNECTION: Function entry ===")
    logger.debug(f"DUCKDB.GET_DUCKDB_CONNECTION: duckdb_file_path={duckdb_file_path}")

    with _connection_lock:
        if duckdb_file_path not in _duckdb_connections:
            logger.debug(f"DUCKDB.GET_DUCKDB_CONNECTION: Creating new DuckDB connection for {duckdb_file_path}")
            _duckdb_connections[duckdb_file_path] = duckdb.connect(duckdb_file_path)
        else:
            logger.debug(f"DUCKDB.GET_DUCKDB_CONNECTION: Reusing existing DuckDB connection for {duckdb_file_path}")
        conn = _duckdb_connections[duckdb_file_path]

    try:
        logger.debug("DUCKDB.GET_DUCKDB_CONNECTION: Yielding connection")
        yield conn
    finally:
        pass


def execute_duckdb_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Dict[str, Any],
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute a DuckDB task.

    Args:
        task_config: The task configuration
        context: The context for rendering templates
        jinja_env: The Jinja2 environment for template rendering
        task_with: The rendered 'with' parameters dictionary
        log_event_callback: A callback function to log events

    Returns:
        A dictionary of the task result
    """
    logger.debug("=== DUCKDB.EXECUTE_DUCKDB_TASK: Function entry ===")
    logger.debug(f"DUCKDB.EXECUTE_DUCKDB_TASK: Parameters - task_config={task_config}, task_with={task_with}")

    task_id = str(uuid.uuid4())
    task_name = task_config.get('task', 'duckdb_task')
    start_time = datetime.datetime.now()

    logger.debug(f"DUCKDB.EXECUTE_DUCKDB_TASK: Generated task_id={task_id}")
    logger.debug(f"DUCKDB.EXECUTE_DUCKDB_TASK: Task name={task_name}")
    logger.debug(f"DUCKDB.EXECUTE_DUCKDB_TASK: Start time={start_time.isoformat()}")

    try:
        last_sql_command = None
        wanted_keys_dbg = []
        fetched_keys_dbg = []
        ingested_secret_names = set()

        # Get base64 encoded commands (only method supported)
        command_b64 = task_config.get('command_b64', '')
        commands_b64 = task_config.get('commands_b64', '')

        # Decode base64 commands
        commands = ''
        if command_b64:
            import base64
            try:
                commands = base64.b64decode(command_b64.encode('ascii')).decode('utf-8')
                logger.debug(f"DUCKDB.EXECUTE_DUCKDB_TASK: Decoded base64 command, length={len(commands)} chars")
            except Exception as e:
                logger.error(f"DUCKDB.EXECUTE_DUCKDB_TASK: Failed to decode base64 command: {e}")
                raise ValueError(f"Invalid base64 command encoding: {e}")
        elif commands_b64:
            import base64
            try:
                commands = base64.b64decode(commands_b64.encode('ascii')).decode('utf-8')
                logger.debug(f"DUCKDB.EXECUTE_DUCKDB_TASK: Decoded base64 commands, length={len(commands)} chars")
            except Exception as e:
                logger.error(f"DUCKDB.EXECUTE_DUCKDB_TASK: Failed to decode base64 commands: {e}")
                raise ValueError(f"Invalid base64 commands encoding: {e}")
        else:
            raise ValueError("No command_b64 or commands_b64 field found - DuckDB tasks require base64 encoded commands")

        # Pre-render task_with values so templates like {{ get_gcs_credential... }} resolve before being used in commands
        processed_task_with = task_with
        try:
            if isinstance(task_with, (dict, list, str)):
                processed_task_with = render_template(jinja_env, task_with, context)
        except Exception:
            processed_task_with = task_with
        # Coerce stringified dicts/lists (e.g., "{'key': 'val'}") into Python objects
        try:
            import json as _json
            import ast as _ast
            def _coerce_val(v):
                if isinstance(v, str):
                    s = v.strip()
                    if (s.startswith('{') and s.endswith('}')) or (s.startswith('[') and s.endswith(']')):
                        try:
                            return _json.loads(s)
                        except Exception:
                            try:
                                return _ast.literal_eval(s)
                            except Exception:
                                return v
                return v
            if isinstance(processed_task_with, dict):
                processed_task_with = {k: _coerce_val(v) for k, v in processed_task_with.items()}
        except Exception:
            pass
        try:
            logger.info(f"DUCKDB.EXECUTE_DUCKDB_TASK: processed_task_with keys={list((processed_task_with or {}).keys())}")
            if isinstance(processed_task_with, dict):
                _g = processed_task_with.get('gcs')
                logger.info(f"DUCKDB.EXECUTE_DUCKDB_TASK: gcs entry type={type(_g)} value={(str(_g)[:200] if _g is not None else None)}")
                _creds_dbg = processed_task_with.get('credentials')
                try:
                    logger.debug(f"DUCKDB: with.credentials type={type(_creds_dbg)} keys={list((_creds_dbg or {}).keys()) if isinstance(_creds_dbg, dict) else None}")
                except Exception:
                    pass
        except Exception:
            pass

        # Warn when a GCS bucket is present but output base still targets local storage
        try:
            out_base = ''
            if isinstance(processed_task_with, dict):
                out_base = str(processed_task_with.get('output_uri_base') or '').strip()
            wl = context.get('work') or context
            wl_obj = wl.get('workload') if isinstance(wl, dict) else {}
            gcs_bucket = None
            if isinstance(wl_obj, dict):
                gcs_bucket = wl_obj.get('gcs_bucket') or wl_obj.get('bucket')
            # Default local markers and cloud markers
            local_like = not out_base or out_base.lower().startswith('data') or out_base.startswith('/') or out_base.lower().startswith('./')
            cloud_like = out_base.lower().startswith('gs://') or out_base.lower().startswith('s3://') or out_base.lower().startswith('file:')
            # Check common env toggle
            def _truthy(v):
                return str(v).lower() in {'1','true','yes','on'}
            enable_gcs_env = _truthy(os.environ.get('NOETL_ENABLE_GCS', 'false'))
            # Normalize mistaken gcs:// scheme to gs:// and warn
            if isinstance(processed_task_with, dict) and out_base.lower().startswith('gcs://'):
                new_base = 'gs://' + out_base[6:]
                processed_task_with['output_uri_base'] = new_base
                logger.warning("DUCKDB: output_uri_base uses gcs://; rewriting to gs:// (%s -> %s)", out_base, new_base)
                out_base = new_base
            if gcs_bucket and not cloud_like and (local_like or not out_base):
                logger.warning(
                    f"DUCKDB: output_uri_base appears local ('{out_base or 'data'}') while workload.gcs_bucket='{gcs_bucket}' is set. "
                    f"Files will be written locally. Set NOETL_ENABLE_GCS=true or set with.output_uri_base to 'gs://{gcs_bucket}/<path>', "
                    "or add with.require_cloud_output=true to fail if cloud write is missing."
                )
            elif gcs_bucket and cloud_like and not enable_gcs_env and out_base.lower().startswith('gs://'):
                # Cloud base is set but env flag is off; still proceed, but hint.
                logger.info(
                    f"DUCKDB: output_uri_base uses GCS ('{out_base}'); ensure credentials are configured (credentials: mapping or NOETL_GCS_CREDENTIAL) and httpfs is available."
                )
        except Exception:
            pass

        # Resolve credentials mapping early so users can refer to {{ credentials.<alias>.* }} in SQL
        # without relying on auto-attach/auto-secret logic.
        resolved_creds_for_tpl: Dict[str, Any] = {}
        try:
            creds_cfg0 = task_config.get('credentials')
            # Normalize mapping -> list with alias injected (non-destructive)
            norm_list = []
            if isinstance(creds_cfg0, dict):
                for _alias, _spec in creds_cfg0.items():
                    if isinstance(_spec, dict):
                        ent = dict(_spec)
                        ent.setdefault('alias', _alias)
                        norm_list.append(ent)
            elif isinstance(creds_cfg0, list):
                norm_list = [e for e in creds_cfg0 if isinstance(e, dict)]
            # Fetch each referenced credential and expose a template-friendly view
            if norm_list:
                base_url = os.environ.get('NOETL_SERVER_URL', 'http://localhost:8082').rstrip('/')
                if not base_url.endswith('/api'):
                    base_url = base_url + '/api'
                with httpx.Client(timeout=5.0) as _c:
                    for ent in norm_list:
                        alias = ent.get('alias') or 'cred'
                        ref = ent.get('key') or ent.get('credential') or ent.get('credentialRef')
                        if not isinstance(ref, str) or not ref:
                            continue
                        try:
                            r = _c.get(f"{base_url}/credentials/{ref}?include_data=true")
                            if r.status_code == 200:
                                body = r.json() or {}
                                ctype = (body.get('type') or body.get('credential_type') or '').lower()
                                raw = body.get('data') or {}
                                payload = raw.get('data') if isinstance(raw, dict) and isinstance(raw.get('data'), dict) else raw
                                view = dict(payload) if isinstance(payload, dict) else {}
                                # Provide a libpq connection string for Postgres
                                if ctype.startswith('postgres'):
                                    host = view.get('db_host') or view.get('host')
                                    port = view.get('db_port') or view.get('port')
                                    user = view.get('db_user') or view.get('user')
                                    pwd = view.get('db_password') or view.get('password')
                                    dbn = view.get('db_name') or view.get('dbname') or view.get('database')
                                    if host and port and user and pwd and dbn:
                                        view['connstr'] = f"dbname={dbn} user={user} password={pwd} host={host} port={port}"
                                    # Expose intended DuckDB secret name for this credential alias
                                    view['secret'] = alias
                                resolved_creds_for_tpl[alias] = view
                        except Exception:
                            continue
        except Exception:
            resolved_creds_for_tpl = {}

        if isinstance(commands, str):
            tpl_ctx = {**context, **(processed_task_with or {})}
            # Expose resolved credentials under 'credentials' for native DuckDB ATTACH/CREATE SECRET usage
            if 'credentials' not in tpl_ctx:
                tpl_ctx['credentials'] = resolved_creds_for_tpl
            commands_rendered = render_template(jinja_env, commands, tpl_ctx)
            try:
                logger.info(f"DUCKDB.EXECUTE_DUCKDB_TASK: commands_rendered (first 400 chars)={commands_rendered[:400]}")
            except Exception:
                pass
            cmd_lines = []
            for line in commands_rendered.split('\n'):
                s = line.strip()
                # Skip common SQL comment line prefixes (DuckDB supports -- and /* ... */)
                if not s:
                    continue
                if s.startswith('--') or s.startswith('#'):
                    continue
                cmd_lines.append(s)
            commands_text = ' '.join(cmd_lines)
            from . import sql_split
            commands = sql_split(commands_text)

        # Extract cloud URI scopes mentioned in the commands (for explicit DuckDB SECRET scoping)
        # Support gs://, gcs:// (normalize to gs://), and s3://
        uri_scopes = {"gs": set(), "s3": set()}
        try:
            import re as _re_extract
            for _cmd in commands if isinstance(commands, list) else []:
                for m in _re_extract.finditer(r"\b(gs|gcs|s3)://([^/'\s)]+)(/|\b)", _cmd):
                    scheme = m.group(1)
                    bucket = m.group(2)
                    if scheme == 'gcs':
                        scheme = 'gs'
                    # Use bucket-level scope; DuckDB matches on prefix
                    scope = f"{scheme}://{bucket}"
                    uri_scopes.setdefault(scheme, set()).add(scope)
        except Exception:
            pass
        try:
            logger.debug(f"DUCKDB: uri_scopes detected gs={sorted(list(uri_scopes.get('gs', [])))} s3={sorted(list(uri_scopes.get('s3', [])))}")
        except Exception:
            pass

        bucket = (processed_task_with or {}).get('bucket', context.get('bucket', ''))
        blob_path = task_with.get('blob', '')
        file_path = task_with.get('file', '')
        table = task_with.get('table', '')

        event_id = None
        if log_event_callback:
            logger.debug(f"DUCKDB.EXECUTE_DUCKDB_TASK: Writing task_start event log")
            event_id = log_event_callback(
                'task_start', task_id, task_name, 'duckdb',
                'in_progress', 0, context, None,
                {'with_params': processed_task_with}, None
            )

        duckdb_data_dir = os.environ.get("NOETL_DATA_DIR", "./data")
        execution_id = context.get("execution_id") or context.get("jobId") or (context.get("job", {}).get("uuid") if isinstance(context.get("job"), dict) else None) or "default"
        if isinstance(execution_id, str) and ('{{' in execution_id or '}}' in execution_id):
            execution_id = render_template(jinja_env, execution_id, context)

        custom_db_path = task_config.get('database')
        if custom_db_path:
            if '{{' in custom_db_path or '}}' in custom_db_path:
                custom_db_path = render_template(jinja_env, custom_db_path, {**context, **(processed_task_with or {})})
            duckdb_file = custom_db_path
        else:
            duckdb_file = os.path.join(duckdb_data_dir, "noetldb", f"duckdb_{execution_id}.duckdb")

        os.makedirs(os.path.dirname(duckdb_file), exist_ok=True)
        logger.info(f"Connecting to DuckDB at {duckdb_file} for execution {execution_id}")
        duckdb_con = duckdb.connect(duckdb_file)

        # Process unified auth and create DuckDB secrets before any user SQL
        params = dict(processed_task_with or {})
        auto_secrets = params.get("auto_secrets", True)
        
        if auto_secrets:
            try:
                # Use the new unified auth system
                resolved_auth = resolve_auth_map(task_config, params, jinja_env, context)
                logger.debug(f"DUCKDB: resolved unified auth with {len(resolved_auth)} aliases")
                
                if resolved_auth:
                    # Get required extensions and install them
                    required_extensions = get_required_extensions(resolved_auth)
                    for ext in required_extensions:
                        try:
                            logger.debug(f"DUCKDB: installing/loading extension: {ext}")
                            duckdb_con.execute(f"INSTALL {ext};")
                            duckdb_con.execute(f"LOAD {ext};")
                        except Exception as ext_e:
                            logger.warning(f"DUCKDB: failed to install/load {ext}: {ext_e}")
                    
                    # Generate and execute DuckDB secret creation statements
                    secret_statements = get_duckdb_secrets(resolved_auth)
                    for stmt in secret_statements:
                        # Log statement without revealing secrets
                        redacted_stmt = stmt
                        import re
                        redacted_stmt = re.sub(r"(SECRET|PASSWORD|KEY_ID)\s*'[^']*'", r"\1 '[REDACTED]'", stmt)
                        logger.info(f"DUCKDB: executing unified auth secret: {redacted_stmt[:150]}...")
                        duckdb_con.execute(stmt)
                    
                    if secret_statements:
                        logger.info(f"DUCKDB: unified auth system created {len(secret_statements)} DuckDB secrets")
                    
                    # Expose resolved auth in template context for user SQL
                    if isinstance(commands, str):
                        tpl_ctx = {**context, **(processed_task_with or {})}
                        tpl_ctx['auth'] = resolved_auth  # New unified auth access
                        commands_rendered = render_template(jinja_env, commands, tpl_ctx)
                        logger.info(f"DUCKDB: commands_rendered (first 400 chars)={commands_rendered[:400]}")
                        cmd_lines = []
                        for line in commands_rendered.split('\n'):
                            s = line.strip()
                            if not s or s.startswith('--') or s.startswith('#'):
                                continue
                            cmd_lines.append(s)
                        commands_text = ' '.join(cmd_lines)
                        from . import sql_split
                        commands = sql_split(commands_text)
                else:
                    logger.debug("DUCKDB: no unified auth configuration found")
            except Exception as e:
                logger.warning(f"DUCKDB: unified auth processing failed: {e}")
                # Fall back to legacy system
                logger.debug("DUCKDB: falling back to legacy credential system")
        
        # Legacy fallback: maintain old behavior if unified auth not used
        if not auto_secrets or ('auth' not in task_config and 'credentials' not in task_config):
            # Resolve credentials mapping early so users can refer to {{ credentials.<alias>.* }} in SQL
            # without relying on auto-attach/auto-secret logic.
            resolved_creds_for_tpl: Dict[str, Any] = {}
            try:
                creds_cfg0 = task_config.get('credentials')
                # Normalize mapping -> list with alias injected (non-destructive)
                norm_list = []
                if isinstance(creds_cfg0, dict):
                    for _alias, _spec in creds_cfg0.items():
                        if isinstance(_spec, dict):
                            ent = dict(_spec)
                            ent.setdefault('alias', _alias)
                            norm_list.append(ent)
                elif isinstance(creds_cfg0, list):
                    norm_list = [e for e in creds_cfg0 if isinstance(e, dict)]
                # Fetch each referenced credential and expose a template-friendly view
                if norm_list:
                    base_url = os.environ.get('NOETL_SERVER_URL', 'http://localhost:8082').rstrip('/')
                    if not base_url.endswith('/api'):
                        base_url = base_url + '/api'
                    with httpx.Client(timeout=5.0) as _c:
                        for ent in norm_list:
                            alias = ent.get('alias') or 'cred'
                            ref = ent.get('key') or ent.get('credential') or ent.get('credentialRef')
                            if not isinstance(ref, str) or not ref:
                                continue
                            try:
                                r = _c.get(f"{base_url}/credentials/{ref}?include_data=true")
                                if r.status_code == 200:
                                    body = r.json() or {}
                                    ctype = (body.get('type') or body.get('credential_type') or '').lower()
                                    raw = body.get('data') or {}
                                    payload = raw.get('data') if isinstance(raw, dict) and isinstance(raw.get('data'), dict) else raw
                                    view = dict(payload) if isinstance(payload, dict) else {}
                                    # Provide a libpq connection string for Postgres
                                    if ctype.startswith('postgres'):
                                        host = view.get('db_host') or view.get('host')
                                        port = view.get('db_port') or view.get('port')
                                        user = view.get('db_user') or view.get('user')
                                        pwd = view.get('db_password') or view.get('password')
                                        dbn = view.get('db_name') or view.get('dbname') or view.get('database')
                                        if host and port and user and pwd and dbn:
                                            view['connstr'] = f"dbname={dbn} user={user} password={pwd} host={host} port={port}"
                                        # Expose intended DuckDB secret name for this credential alias
                                        view['secret'] = alias
                                    resolved_creds_for_tpl[alias] = view
                            except Exception:
                                continue
            except Exception:
                resolved_creds_for_tpl = {}

            if isinstance(commands, str):
                tpl_ctx = {**context, **(processed_task_with or {})}
                # Expose resolved credentials under 'credentials' for legacy compatibility
                if 'credentials' not in tpl_ctx:
                    tpl_ctx['credentials'] = resolved_creds_for_tpl
                commands_rendered = render_template(jinja_env, commands, tpl_ctx)
                try:
                    logger.info(f"DUCKDB: legacy commands_rendered (first 400 chars)={commands_rendered[:400]}")
                except Exception:
                    pass
                cmd_lines = []
                for line in commands_rendered.split('\n'):
                    s = line.strip()
                    if not s or s.startswith('--') or s.startswith('#'):
                        continue
                    cmd_lines.append(s)
                commands_text = ' '.join(cmd_lines)
                from . import sql_split
                commands = sql_split(commands_text)

        # Optional: attach multiple external databases from credentials mapping/list
        # New preferred: task_config['credentials'] as a mapping of alias -> { key: <credential_name> }
        #                'kind' becomes optional and may be derived from the credential record type.
        # Back-compat: with.credentials can be a list or mapping too (old shape with inline payloads is rejected)
        # Supported kinds: postgres|mysql|sqlite (attach) and gcs_hmac/s3_hmac (configure cloud access via DuckDB Secrets)
        try:
            creds_cfg = task_config.get('credentials') or (processed_task_with or {}).get('credentials')
            if isinstance(creds_cfg, dict):
                # Convert mapping { alias: { ... } } to list with alias injected
                _tmp = []
                for _alias, _spec in creds_cfg.items():
                    if isinstance(_spec, dict):
                        _ent = dict(_spec)
                        _ent.setdefault('alias', _alias)
                        _tmp.append(_ent)
                creds_cfg = _tmp
            if isinstance(creds_cfg, list):
                for ent in creds_cfg:
                    try:
                        if not isinstance(ent, dict):
                            continue
                        alias = ent.get('alias') or ent.get('db_alias') or 'ext_db'
                        kind = (ent.get('kind') or ent.get('db_type') or '').lower()
                        dsn = ent.get('dsn') or ent.get('db_conn_string')
                        spec = ent.get('spec') if isinstance(ent.get('spec'), dict) else {}
                        cred_ref = ent.get('key') or ent.get('credential') or ent.get('credentialRef')

                        # Reject inline secret payloads in credentials entries (use key: alias instead)
                        forbidden_inline_keys = {'key_id','secret','secret_key','access_key_id','secret_access_key','db_user','db_password','db_host','db_name','dbname'}
                        if any(k in ent for k in forbidden_inline_keys):
                            raise ValueError("duckdb.credentials: inline secret fields are not allowed; use entries like { alias: { key: <credential_name> } }")

                        # Resolve credential by name/id from server when provided
                        cred_data = None
                        cred_type = None
                        if cred_ref:
                            try:
                                base = os.environ.get('NOETL_SERVER_URL', 'http://localhost:8082').rstrip('/')
                                if not base.endswith('/api'):
                                    base = base + '/api'
                                url = f"{base}/credentials/{cred_ref}?include_data=true"
                                with httpx.Client(timeout=5.0) as _c:
                                    _r = _c.get(url)
                                    if _r.status_code == 200:
                                        body = _r.json() or {}
                                        raw = body.get('data') or {}
                                        payload = raw.get('data') if isinstance(raw, dict) and isinstance(raw.get('data'), dict) else raw
                                        cred_data = payload if isinstance(payload, dict) else None
                                        cred_type = (body.get('type') or body.get('credential_type') or '').lower()
                            except Exception:
                                cred_data = None

                        # Explicitly configure DuckDB Secrets for cloud access
                        use_kind = kind or cred_type or ''
                        if use_kind in ('gcs', 'gcs_hmac', 's3', 's3_hmac'):
                            # Prefer explicit values from entry/spec/cred store
                            src = {}
                            if isinstance(cred_data, dict):
                                src.update(cred_data)
                            if isinstance(spec, dict):
                                src.update(spec)
                            key_id = ent.get('key_id') or src.get('key_id')
                            secret = ent.get('secret_key') or ent.get('secret') or src.get('secret_key') or src.get('secret')
                            region = ent.get('region') or src.get('region') or 'auto'
                            endpoint = ent.get('endpoint') or src.get('endpoint')
                            url_style = ent.get('url_style') or src.get('url_style') or 'path'
                            use_ssl = ent.get('use_ssl') if ent.get('use_ssl') is not None else (src.get('use_ssl') if src.get('use_ssl') is not None else True)
                            # Determine provider/scheme and candidate scopes from parsed commands
                            provider = 'GCS' if use_kind in ('gcs','gcs_hmac') else None
                            schemes = ['gs'] if provider == 'GCS' else ['s3']
                            scopes = []
                            for sch in schemes:
                                scopes.extend(sorted(uri_scopes.get(sch, [])))
                            # If caller provided a specific scope, respect it
                            ent_scope = ent.get('scope') or (src.get('scope') if isinstance(src, dict) else None)
                            if ent_scope:
                                scopes = [ent_scope]
                            # Build a stable secret name
                            safe_alias = re.sub(r"[^a-zA-Z0-9_]+", "_", str(alias))
                            secret_base = f"noetl_{safe_alias}"
                            if not key_id or not secret:
                                logger.warning(f"DUCKDB: missing key/secret for cloud credentials entry '{alias}', skipping secret creation")
                                continue
                            try:
                                # Ensure extension registering secrets is loaded for GCS/S3
                                duckdb_con.execute("LOAD httpfs;")
                            except Exception:
                                pass
                            # Create a single secret named exactly as the credentials alias
                            parts = [
                                "TYPE S3",
                            ]
                            if provider:
                                parts.append(f"PROVIDER {provider}")
                            parts.append(f"KEY_ID '{key_id}'")
                            parts.append(f"SECRET '{secret}'")
                            if endpoint or provider == 'GCS':
                                parts.append(f"ENDPOINT '{endpoint or 'storage.googleapis.com'}'")
                            if region:
                                parts.append(f"REGION '{region}'")
                            if url_style:
                                parts.append(f"URL_STYLE '{url_style}'")
                            parts.append(f"USE_SSL {'true' if use_ssl else 'false'}")
                            # Prefer explicit entry scope; otherwise use the first detected scope in SQL; otherwise unscoped
                            chosen_scope = ent_scope or (scopes[0] if scopes else None)
                            if chosen_scope:
                                parts.append(f"SCOPE '{chosen_scope}'")
                            secret_name = safe_alias
                            ddl = f"CREATE OR REPLACE SECRET {secret_name} (\n        {', '.join(parts)}\n    );"
                            logger.info(f"DUCKDB: configured secret '{secret_name}' for provider {provider or 'S3'}")
                            duckdb_con.execute(ddl)
                            continue

                        conn_string = dsn or ''
                        # Capture discrete Postgres fields when available for SECRET creation
                        _pg_host = _pg_port = _pg_user = _pg_pwd = _pg_dbn = None
                        if not conn_string:
                            # Build from spec/cred_data
                            src = {}
                            try:
                                if isinstance(cred_data, dict):
                                    src.update(cred_data)
                                if isinstance(spec, dict):
                                    src.update(spec)
                            except Exception:
                                pass
                            if (use_kind or kind or '').startswith('postgres'):
                                host = src.get('host') or src.get('db_host') or os.environ.get('POSTGRES_HOST', 'localhost')
                                port = src.get('port') or src.get('db_port') or os.environ.get('POSTGRES_PORT', '5434')
                                user = src.get('user') or src.get('db_user') or os.environ.get('POSTGRES_USER', 'noetl')
                                pwd = src.get('password') or src.get('db_password') or os.environ.get('POSTGRES_PASSWORD', 'noetl')
                                dbn = src.get('dbname') or src.get('database') or src.get('db_name') or os.environ.get('POSTGRES_DB', 'noetl')
                                _pg_host, _pg_port, _pg_user, _pg_pwd, _pg_dbn = host, port, user, pwd, dbn
                                conn_string = f"dbname={dbn} user={user} password={pwd} host={host} port={port}"
                            elif (use_kind or kind or '') == 'sqlite':
                                path = src.get('path') or src.get('db_path') or os.path.join(duckdb_data_dir, 'sqlite', 'noetl.db')
                                conn_string = path
                            elif (use_kind or kind or '') == 'mysql':
                                host = src.get('host') or src.get('db_host') or os.environ.get('MYSQL_HOST', 'localhost')
                                port = src.get('port') or src.get('db_port') or os.environ.get('MYSQL_PORT', '3306')
                                user = src.get('user') or src.get('db_user') or os.environ.get('MYSQL_USER', 'noetl')
                                pwd = src.get('password') or src.get('db_password') or os.environ.get('MYSQL_PASSWORD', 'noetl')
                                dbn = src.get('dbname') or src.get('database') or src.get('db_name') or os.environ.get('MYSQL_DB', 'noetl')
                                conn_string = f"host={host} port={port} user={user} password={pwd} dbname={dbn}"
                            else:
                                conn_string = src.get('dsn') or ''

                        if not conn_string:
                            continue

                        # Install required extension and ATTACH
                        if (use_kind or kind or '').startswith('postgres'):
                            duckdb_con.execute("INSTALL postgres;")
                            duckdb_con.execute("LOAD postgres;")
                            # Prefer using a named SECRET matching the alias if present (created in auto-secret phase)
                            safe_alias = re.sub(r"[^a-zA-Z0-9_]+", "_", str(alias))
                            attach_opts = f" (TYPE postgres, SECRET {safe_alias})"
                        elif (use_kind or kind or '') == 'mysql':
                            duckdb_con.execute("INSTALL mysql;")
                            duckdb_con.execute("LOAD mysql;")
                            attach_opts = " (TYPE mysql)"
                        elif (use_kind or kind or '') == 'sqlite':
                            attach_opts = ""
                        else:
                            attach_opts = ""
                        try:
                            test_query = (
                                f"SELECT 1 FROM {alias}.information_schema.tables LIMIT 1" if kind in ['postgres','mysql']
                                else f"SELECT 1 FROM {alias}.sqlite_master LIMIT 1"
                            )
                            duckdb_con.execute(test_query)
                        except Exception:
                            attach_conn = '' if attach_opts.find('SECRET ') != -1 else conn_string
                            duckdb_con.execute(f"ATTACH '{attach_conn}' AS {alias}{attach_opts};")
                            logger.info(f"Attached {kind} database as '{alias}'")
                    except Exception as _ent_err:
                        logger.warning(f"DUCKDB: Failed to attach credential entry {ent}: {_ent_err}")
        except Exception:
            logger.debug("DUCKDB: credentials attachment phase skipped or failed", exc_info=True)

        db_type = task_with.get('db_type', 'postgres')
        db_alias = task_with.get('db_alias', 'postgres_db')

        if db_type.lower() == 'postgres':
            logger.info("Installing and loading Postgres extension")
            duckdb_con.execute("INSTALL postgres;")
            duckdb_con.execute("LOAD postgres;")
        elif db_type.lower() == 'mysql':
            logger.info("Installing and loading MySQL extension")
            duckdb_con.execute("INSTALL mysql;")
            duckdb_con.execute("LOAD mysql;")
        elif db_type.lower() == 'sqlite':
            logger.info("SQLite support is built-in to DuckDB, no extension needed")
        else:
            logger.info(f"Using custom database type: {db_type}, no specific extension loaded")

        # Auto-resolve cloud credentials if URIs are present but no step-level mapping provided
        try:
            # GCS
            if uri_scopes.get('gs'):
                cred_name = (
                    task_config.get('gcs_credential') or task_with.get('gcs_credential') or
                    task_config.get('cloud_credential') or task_with.get('cloud_credential') or
                    os.environ.get('NOETL_GCS_CREDENTIAL')
                )
                try:
                    _env_gcs = os.environ.get('NOETL_GCS_CREDENTIAL')
                    logger.debug(f"DUCKDB: auto-resolve GCS cred_name={cred_name} env.NOETL_GCS_CREDENTIAL={_env_gcs}")
                except Exception:
                    pass
                if cred_name:
                    try:
                        base = os.environ.get('NOETL_SERVER_URL', 'http://localhost:8082').rstrip('/')
                        if not base.endswith('/api'):
                            base = base + '/api'
                        url = f"{base}/credentials/{cred_name}?include_data=true"
                        with httpx.Client(timeout=5.0) as _c:
                            _r = _c.get(url)
                            if _r.status_code == 200:
                                body = _r.json() or {}
                                raw = body.get('data') or {}
                                payload = raw.get('data') if isinstance(raw, dict) and isinstance(raw.get('data'), dict) else raw
                                payload = payload if isinstance(payload, dict) else {}
                                key_id = payload.get('key_id')
                                secret = payload.get('secret_key') or payload.get('secret')
                                endpoint = payload.get('endpoint') or 'storage.googleapis.com'
                                region = payload.get('region') or 'auto'
                                url_style = payload.get('url_style') or 'path'
                                scope_from_cred = payload.get('scope')
                                if key_id and secret:
                                    try:
                                        duckdb_con.execute("LOAD httpfs;")
                                    except Exception:
                                        pass
                                    scopes = [scope_from_cred] if isinstance(scope_from_cred, str) and scope_from_cred else sorted(uri_scopes.get('gs') or [])
                                    for sc in scopes:
                                        scope_tag = re.sub(r"[^a-zA-Z0-9_]+", "_", sc)
                                        sname = f"noetl_auto_gcs_{scope_tag}"
                                        ddl_gcs = f"""
                                            CREATE OR REPLACE SECRET {sname} (
                                                TYPE GCS,
                                                KEY_ID '{key_id}',
                                                SECRET '{secret}',
                                                SCOPE '{sc}'
                                            );
                                        """
                                        try:
                                            duckdb_con.execute(ddl_gcs)
                                            logger.info(f"DUCKDB: auto-configured GCS secret {sname} for {sc}")
                                        except Exception:
                                            ddl_s3prov = f"""
                                                CREATE OR REPLACE SECRET {sname} (
                                                    TYPE S3,
                                                    PROVIDER GCS,
                                                    KEY_ID '{key_id}',
                                                    SECRET '{secret}',
                                                    REGION 'auto',
                                                    ENDPOINT 'storage.googleapis.com',
                                                    URL_STYLE 'path',
                                                    SCOPE '{sc}'
                                                );
                                            """
                                            duckdb_con.execute(ddl_s3prov)
                                            logger.info(f"DUCKDB: auto-configured GCS secret (provider fallback) {sname} for {sc}")
                    except Exception as _gcs_auto_e:
                        logger.warning(f"DUCKDB: failed to auto-configure GCS credentials from '{cred_name}': {_gcs_auto_e}")

            # S3
            if uri_scopes.get('s3'):
                cred_name = (
                    task_config.get('s3_credential') or task_with.get('s3_credential') or
                    task_config.get('cloud_credential') or task_with.get('cloud_credential') or
                    os.environ.get('NOETL_S3_CREDENTIAL')
                )
                try:
                    _env_s3 = os.environ.get('NOETL_S3_CREDENTIAL')
                    logger.debug(f"DUCKDB: auto-resolve S3 cred_name={cred_name} env.NOETL_S3_CREDENTIAL={_env_s3}")
                except Exception:
                    pass
                if cred_name:
                    try:
                        base = os.environ.get('NOETL_SERVER_URL', 'http://localhost:8082').rstrip('/')
                        if not base.endswith('/api'):
                            base = base + '/api'
                        url = f"{base}/credentials/{cred_name}?include_data=true"
                        with httpx.Client(timeout=5.0) as _c:
                            _r = _c.get(url)
                            if _r.status_code == 200:
                                body = _r.json() or {}
                                raw = body.get('data') or {}
                                payload = raw.get('data') if isinstance(raw, dict) and isinstance(raw.get('data'), dict) else raw
                                payload = payload if isinstance(payload, dict) else {}
                                key_id = payload.get('key_id') or payload.get('access_key_id')
                                secret = payload.get('secret_key') or payload.get('secret_access_key') or payload.get('secret')
                                endpoint = payload.get('endpoint') or 's3.amazonaws.com'
                                region = payload.get('region') or 'auto'
                                url_style = payload.get('url_style') or 'path'
                                scope_from_cred = payload.get('scope')
                                if key_id and secret:
                                    try:
                                        duckdb_con.execute("LOAD httpfs;")
                                    except Exception:
                                        pass
                                    scopes = [scope_from_cred] if isinstance(scope_from_cred, str) and scope_from_cred else sorted(uri_scopes.get('s3') or [])
                                    for sc in scopes:
                                        scope_tag = re.sub(r"[^a-zA-Z0-9_]+", "_", sc)
                                        sname = f"noetl_auto_s3_{scope_tag}"
                                        ddl = f"""
                                            CREATE OR REPLACE SECRET {sname} (
                                                TYPE S3,
                                                KEY_ID '{key_id}',
                                                SECRET '{secret}',
                                                REGION '{region}',
                                                ENDPOINT '{endpoint}',
                                                URL_STYLE '{url_style}',
                                                USE_SSL true,
                                                SCOPE '{sc}'
                                            );
                                        """
                                        logger.info(f"DUCKDB: auto-configured S3 secret {sname} from credential '{cred_name}' for {sc}")
                                        duckdb_con.execute(ddl)
                    except Exception as _s3_auto_e:
                        logger.warning(f"DUCKDB: failed to auto-configure S3 credentials from '{cred_name}': {_s3_auto_e}")
        except Exception:
            logger.debug("DUCKDB: auto-configure cloud credentials fallback skipped or failed", exc_info=True)

        # Back-compat single HMAC keys still supported (create explicit scoped secret if URIs are present)
        key_id = task_with.get('key_id')
        secret_key = task_with.get('secret_key')
        if key_id and secret_key:
            try:
                duckdb_con.execute("LOAD httpfs;")
            except Exception:
                pass
            scheme_scopes = sorted(uri_scopes.get('gs', set())) or sorted(uri_scopes.get('s3', set()))
            secret_name = "noetl_backcompat_hmac"
            if scheme_scopes:
                for sc in scheme_scopes:
                    scope_tag = re.sub(r"[^a-zA-Z0-9_]+", "_", sc)
                    sname = f"{secret_name}_{scope_tag}" if len(scheme_scopes) > 1 else secret_name
                    ddl = f"""
                        CREATE OR REPLACE SECRET {sname} (
                            TYPE GCS,
                            KEY_ID '{key_id}',
                            SECRET '{secret_key}',
                            SCOPE '{sc}'
                        );
                    """
                    logger.info(f"DUCKDB: creating back-compat scoped secret {sname} -> {sc}")
                    duckdb_con.execute(ddl)
            else:
                ddl = f"""
                    CREATE OR REPLACE SECRET {secret_name} (
                        TYPE GCS,
                        KEY_ID '{key_id}',
                        SECRET '{secret_key}'
                    );
                """
                logger.info("DUCKDB: creating back-compat unscoped secret for HMAC")
                duckdb_con.execute(ddl)

        if db_type.lower() == 'postgres':
            pg_host = task_with.get('db_host', os.environ.get('POSTGRES_HOST', 'localhost'))
            pg_port = task_with.get('db_port', os.environ.get('POSTGRES_PORT', '5434'))
            pg_user = task_with.get('db_user', os.environ.get('POSTGRES_USER', 'noetl'))
            pg_password = task_with.get('db_password', os.environ.get('POSTGRES_PASSWORD', 'noetl'))
            pg_db = task_with.get('db_name', os.environ.get('POSTGRES_DB', 'noetl'))
            pg_conn_string = f"dbname={pg_db} user={pg_user} password={pg_password} host={pg_host} port={pg_port}"
            conn_string = pg_conn_string
        elif db_type.lower() == 'sqlite':
            sqlite_path = task_with.get('db_path', os.path.join(duckdb_data_dir, 'sqlite', 'noetl.db'))
            conn_string = sqlite_path
        elif db_type.lower() == 'mysql':
            mysql_host = task_with.get('db_host', os.environ.get('MYSQL_HOST', 'localhost'))
            mysql_port = task_with.get('db_port', os.environ.get('MYSQL_PORT', '3306'))
            mysql_user = task_with.get('db_user', os.environ.get('MYSQL_USER', 'noetl'))
            mysql_password = task_with.get('db_password', os.environ.get('MYSQL_PASSWORD', 'noetl'))
            mysql_db = task_with.get('db_name', os.environ.get('MYSQL_DB', 'noetl'))
            mysql_conn_string = f"host={mysql_host} port={mysql_port} user={mysql_user} password={mysql_password} dbname={mysql_db}"
            conn_string = mysql_conn_string
        else:
            conn_string = task_with.get('db_conn_string', '')
            if not conn_string:
                logger.warning(f"No connection string provided for database type: {db_type}. Using in-memory DuckDB.")
                conn_string = "memory"

        read_only = task_with.get('db_read_only', False)
        attach_options = ""
        if read_only:
            attach_options += " (READ_ONLY)"
        elif db_type.lower() in ['postgres', 'mysql']:
            attach_options += f" (TYPE {db_type.lower()})"

        # Determine which alias names are referenced in commands and ensure those are attached too.
        # This keeps backward compatibility when playbooks use 'pg_db' while default alias is 'postgres_db'.
        referenced_aliases = set()
        try:
            if isinstance(commands, list):
                for _c in commands:
                    if not isinstance(_c, str):
                        continue
                    if 'pg_db.' in _c:
                        referenced_aliases.add('pg_db')
                    if 'postgres_db.' in _c:
                        referenced_aliases.add('postgres_db')
        except Exception:
            pass

        # Always include configured alias; for postgres also include any referenced alias tokens
        aliases_to_attach = [db_alias]
        if db_type.lower() == 'postgres':
            for ra in sorted(referenced_aliases):
                if ra not in aliases_to_attach:
                    aliases_to_attach.append(ra)

        # Attach each required alias idempotently
        for _alias in aliases_to_attach:
            try:
                test_query = (
                    f"SELECT 1 FROM {_alias}.sqlite_master LIMIT 1" if db_type.lower() == 'sqlite'
                    else f"SELECT 1 FROM {_alias}.information_schema.tables LIMIT 1"
                )
                duckdb_con.execute(test_query)
                logger.info(f"Database '{_alias}' is already attached.")
            except Exception:
                try:
                    logger.info(f"Attaching {db_type} database as '{_alias}'.")
                    attach_sql = f"ATTACH '{conn_string}' AS {_alias}{attach_options};"
                    logger.debug(f"ATTACH SQL: {attach_sql}")
                    duckdb_con.execute(attach_sql)
                except Exception as attach_error:
                    logger.error(f"Error attaching database alias '{_alias}': {attach_error}.")
                    raise

        results = {}
        # Track COPY targets for verification and better error reporting
        copy_cloud_targets = []  # list of dicts: { path, fmt }
        if commands:
            for i, cmd in enumerate(commands):
                if isinstance(cmd, str) and ('{{' in cmd or '}}' in cmd):
                    # Render with full context (includes with: and resolved credentials if any)
                    _local_ctx = {**context, **(processed_task_with or {})}
                    try:
                        if 'credentials' not in _local_ctx:
                            _local_ctx['credentials'] = resolved_creds_for_tpl
                    except Exception:
                        pass
                    cmd = render_template(jinja_env, cmd, _local_ctx)

                logger.info(f"Executing DuckDB command: {cmd}")

                decimal_separator = (processed_task_with or {}).get('decimal_separator')
                if decimal_separator and decimal_separator != '.':
                    cast_pattern = r'CAST\s*\(\s*([^\s]+)\s+AS\s+NUMERIC[^)]*\)'
                    def replace_cast(match):
                        column = match.group(1)
                        return f"CAST(REPLACE({column}, '{decimal_separator}', '.') AS NUMERIC)"
                    cmd = re.sub(cast_pattern, replace_cast, cmd, flags=re.IGNORECASE)

                if cmd.strip().upper().startswith("ATTACH"):
                    try:
                        attach_parts = cmd.strip().split(" AS ")
                        if len(attach_parts) >= 2:
                            db_alias_with_options = attach_parts[1].strip()
                            db_alias = db_alias_with_options.split()[0].rstrip(';')
                            try:
                                test_query = f"SELECT 1 FROM {db_alias}.information_schema.tables LIMIT 1"
                                duckdb_con.execute(test_query)
                                logger.info(f"Database '{db_alias}' is already attached, skipping ATTACH command.")
                                results[f"command_{i}"] = {"status": "skipped", "message": f"Database '{db_alias}' is already attached."}
                                continue
                            except Exception:
                                logger.info(f"Attaching database as '{db_alias}'.")

                        result = duckdb_con.execute(cmd).fetchall()
                        results[f"command_{i}"] = {"status": "success", "message": f"Database attached"}
                    except Exception as attach_error:
                        logger.error(f"Error in ATTACH command: {attach_error}.")
                        results[f"command_{i}"] = {"status": "error", "message": f"ATTACH operation failed: {str(attach_error)}"}
                elif cmd.strip().upper().startswith("DETACH"):
                    try:
                        detach_parts = cmd.strip().split()
                        if len(detach_parts) >= 2:
                            detach_alias = detach_parts[1].rstrip(';')
                            logger.info(f"Detaching database '{detach_alias}'.")

                        result = duckdb_con.execute(cmd).fetchall()
                        results[f"command_{i}"] = {"status": "success", "message": f"Database detached"}
                    except Exception as detach_error:
                        logger.warning(f"Error in DETACH command: {detach_error}.")
                        results[f"command_{i}"] = {"status": "warning", "message": f"DETACH operation failed: {str(detach_error)}"}
                else:
                    # Skip duplicate httpfs extension management in user SQL to avoid resetting secret context
                    try:
                        _u = cmd.strip().upper().replace("  ", " ")
                        if _u in {"INSTALL HTTPFS", "LOAD HTTPFS", "INSTALL GCS", "LOAD GCS", "INSTALL S3", "LOAD S3"} or \
                           _u.startswith("INSTALL HTTPFS") or _u.startswith("LOAD HTTPFS") or \
                           _u.startswith("INSTALL GCS") or _u.startswith("LOAD GCS") or \
                           _u.startswith("INSTALL S3") or _u.startswith("LOAD S3"):
                            logger.info(f"Skipping duplicate httpfs/gcs/s3 extension command: {cmd}")
                            results[f"command_{i}"] = {"status": "skipped", "message": "Skipped duplicate httpfs/gcs/s3 extension load/install"}
                            continue
                        # First-one-wins guard for CREATE SECRET: if secret ingested already, skip redefinition to keep context stable
                        import re as _re_sec
                        _m = _re_sec.match(r"^CREATE\s+(OR\s+REPLACE\s+)?SECRET\s+([a-zA-Z0-9_]+)\s*\(", _u)
                        if _m:
                            secret_name = _m.group(2)
                            try:
                                # ingested_secret_names may not exist on older builds of this plugin
                                if 'ingested_secret_names' in locals() and secret_name in ingested_secret_names:
                                    logger.info("Skipping CREATE SECRET for already-ingested secret '%s'", secret_name)
                                    results[f"command_{i}"] = {"status": "skipped", "message": f"Secret '{secret_name}' already ingested"}
                                    continue
                            except Exception:
                                pass
                    except Exception:
                        pass
                    # Normalize COPY paths
                    # 1) Ensure file/URI is quoted to avoid parser issues on ':' (e.g., gs://)
                    # 2) If the path is an absolute local path (starts with '/'), rewrite to NOETL_DATA_DIR
                    try:
                        import re as _re
                        import os as _os
                        _cmd_upper = cmd.strip().upper()
                        if _cmd_upper.startswith("COPY "):
                            # Quote unquoted path
                            def _quote_copy_path(_cmd: str, _kw: str) -> str:
                                pattern = _re.compile(rf"^(COPY\s+[^\s]+\s+{_kw}\s+)([^\s\(]+)(\s*\()", _re.IGNORECASE)
                                m = pattern.search(_cmd)
                                if m:
                                    path = m.group(2)
                                    if not (path.startswith("'") or path.startswith('"')):
                                        quoted = f"'{path}'"
                                        _cmd = _cmd[:m.start(2)] + quoted + _cmd[m.end(2):]
                                return _cmd
                            if " TO " in _cmd_upper:
                                cmd = _quote_copy_path(cmd, "TO")
                            if " FROM " in _cmd_upper:
                                cmd = _quote_copy_path(cmd, "FROM")

                            # Rewrite absolute local paths to live under NOETL_DATA_DIR
                            def _normalize_copy_local_path(_cmd: str) -> str:
                                # Match COPY <obj> (TO|FROM) <path> (
                                pat = _re.compile(r'^(COPY\s+[^\s]+\s+)(TO|FROM)\s+(\'([^\']*)\'|"([^"]*)"|([^\s\(]+))(\s*\()', _re.IGNORECASE)
                                m = pat.search(_cmd)
                                if not m:
                                    return _cmd
                                kw = (m.group(2) or '').upper()
                                raw = m.group(3)
                                path = m.group(4) or m.group(5) or m.group(6) or ''
                                # Normalize scheme gcs:// to gs:// for DuckDB
                                if path.lower().startswith('gcs://'):
                                    path = 'gs://' + path[6:]
                                    # Replace inside the command while preserving quotes
                                    if raw.startswith("'") and raw.endswith("'"):
                                        quoted = f"'{path}'"
                                    elif raw.startswith('"') and raw.endswith('"'):
                                        quoted = f'"{path}"'
                                    else:
                                        quoted = f"'{path}'"
                                    _cmd = _cmd[:m.start(3)] + quoted + _cmd[m.end(3):]
                                    # recompute raw for further handling
                                    raw = quoted
                                # Leave URIs or file: scheme unchanged
                                if '://' in path or path.startswith('file:'):
                                    # Capture cloud targets for later verification when writing
                                    if kw == 'TO' and (path.startswith('gs://') or path.startswith('s3://')):
                                        # detect format
                                        fm = _re.search(r"\(.*?FORMAT\s+([A-Z]+).*?\)", _cmd, _re.IGNORECASE)
                                        fmt = (fm.group(1).upper() if fm else None)
                                        copy_cloud_targets.append({"path": path, "fmt": fmt})
                                    return _cmd
                                # Only rewrite absolute paths
                                if path.startswith('/'):
                                    base = duckdb_data_dir
                                    norm = _os.path.join(base, path.lstrip('/'))
                                    # Ensure parent dir exists for writes
                                    if kw == 'TO':
                                        try:
                                            _os.makedirs(_os.path.dirname(norm), exist_ok=True)
                                        except Exception:
                                            pass
                                    # Replace while preserving quotes
                                    if raw.startswith("'") and raw.endswith("'"):
                                        repl = f"'{norm}'"
                                    elif raw.startswith('"') and raw.endswith('"'):
                                        repl = f'"{norm}"'
                                    else:
                                        repl = f"'{norm}'"
                                    _cmd = _cmd[:m.start(3)] + repl + _cmd[m.end(3):]
                                return _cmd

                            cmd = _normalize_copy_local_path(cmd)
                            # If critical statements still contain unresolved templates, surface as error
                            if ('{{' in cmd or '}}' in cmd):
                                raise ValueError(f"Unresolved template variables in COPY command: {cmd}")
                    except Exception:
                        pass
                    # Fail early if unresolved templates remain in critical commands like ATTACH
                    try:
                        _cmd_upper = cmd.strip().upper()
                        if ('{{' in cmd or '}}' in cmd) and (_cmd_upper.startswith('ATTACH') or _cmd_upper.startswith('CREATE SECRET')):
                            raise ValueError(
                                f"Unresolved template variables in critical SQL: {cmd}. "
                                "Suggest defining 'credentials:' bindings or ensure context includes required values."
                            )
                    except Exception as _unres_err:
                        raise

                    cursor = duckdb_con.execute(cmd)
                    result = cursor.fetchall()

                    if cmd.strip().upper().startswith("SELECT") or "RETURNING" in cmd.upper():
                        column_names = [desc[0] for desc in cursor.description] if cursor.description else []
                        result_data = []
                        for row in result:
                            row_dict = {}
                            for j, col_name in enumerate(column_names):
                                if isinstance(row[j], dict) or (isinstance(row[j], str) and (row[j].startswith('{') or row[j].startswith('['))):
                                    try:
                                        row_dict[col_name] = row[j]
                                    except:
                                        row_dict[col_name] = row[j]
                                elif isinstance(row[j], Decimal):
                                    row_dict[col_name] = float(row[j])
                                else:
                                    row_dict[col_name] = row[j]
                            result_data.append(row_dict)

                        results[f"command_{i}"] = {
                            "status": "success",
                            "rows": result_data,
                            "row_count": len(result),
                            "columns": column_names
                        }
                    else:
                        results[f"command_{i}"] = {
                            "status": "success",
                            "message": f"Command executed successfully",
                            "raw_result": result
                        }

            # Post-execution verification: ensure cloud COPY targets exist when requested
            try:
                if copy_cloud_targets:
                    try:
                        duckdb_con.execute("LOAD httpfs;")
                    except Exception:
                        pass
                    for tgt in copy_cloud_targets:
                        p = tgt.get('path') or ''
                        fmt = (tgt.get('fmt') or '').upper()
                        verify_sql = None
                        if fmt == 'PARQUET':
                            verify_sql = f"SELECT 1 FROM read_parquet('{p}') LIMIT 1"
                        elif fmt == 'CSV':
                            verify_sql = f"SELECT 1 FROM read_csv_auto('{p}') LIMIT 1"
                        else:
                            # Try parquet first, then CSV
                            try:
                                duckdb_con.execute(f"SELECT 1 FROM read_parquet('{p}') LIMIT 1").fetchall()
                                verify_sql = None
                                continue
                            except Exception:
                                verify_sql = f"SELECT 1 FROM read_csv_auto('{p}') LIMIT 1"
                        if verify_sql:
                            duckdb_con.execute(verify_sql).fetchall()
                        # Optional: reveal which secret was selected by DuckDB (no sensitive values exposed)
                        try:
                            require_cloud = bool((processed_task_with or {}).get('require_cloud_output') or task_config.get('require_cloud_output'))
                        except Exception:
                            require_cloud = False
                        if require_cloud:
                            # Decide provider for which_secret based on URL scheme
                            scheme = 's3'
                            lp = p.lower()
                            if lp.startswith('gs://') or lp.startswith('gcs://'):
                                scheme = 'gcs'
                            try:
                                cur = duckdb_con.execute(f"SELECT * FROM which_secret('{p}', '{scheme}')")
                                row = cur.fetchone()
                                sel = row[0] if row else None
                                if sel:
                                    logger.info(f"DUCKDB: which_secret selected '{sel}' for {p}")
                                else:
                                    raise ValueError(f"No secret selected by DuckDB for {p} (provider {scheme}). Check scope matches path and credentials are registered.")
                            except Exception as _ws_err:
                                # If which_secret is missing or incompatible, log debug and continue; read-back already verified
                                logger.debug(f"DUCKDB: which_secret not available: {_ws_err}")
                else:
                    # Optional safety: if caller requires cloud output but no cloud COPY detected
                    require_cloud = False
                    try:
                        require_cloud = bool((processed_task_with or {}).get('require_cloud_output') or task_config.get('require_cloud_output'))
                    except Exception:
                        require_cloud = False
                    if require_cloud:
                        raise ValueError("No cloud COPY targets detected (gs:// or s3://) while require_cloud_output=true.")
            except Exception as _verify_err:
                logger.error(f"Cloud COPY verification failed: {_verify_err}")
                raise

        elif bucket and blob_path and table:
            temp_table = f"temp_{table}_{int(time.time())}"
            if bucket and blob_path:
                logger.info(f"Reading data from bucket {bucket}, blob {blob_path}")
                duckdb_con.execute("INSTALL httpfs;")
                duckdb_con.execute("LOAD httpfs;")
                if bucket.startswith('gs://') or blob_path.startswith('gs://'):
                    full_path = f"{bucket}/{blob_path}" if not bucket.startswith('gs://') else f"{blob_path}"
                    if not full_path.startswith('gs://'):
                        full_path = f"gs://{full_path}"
                    logger.info(f"Reading from GCS: {full_path}")
                    duckdb_con.execute("INSTALL gcs;")
                    duckdb_con.execute("LOAD gcs;")
                elif bucket.startswith('s3://') or blob_path.startswith('s3://'):
                    full_path = f"{bucket}/{blob_path}" if not bucket.startswith('s3://') else f"{blob_path}"
                    if not full_path.startswith('s3://'):
                        full_path = f"s3://{full_path}"
                    logger.info(f"Reading from S3: {full_path}")
                    duckdb_con.execute("INSTALL s3;")
                    duckdb_con.execute("LOAD s3;")
                else:
                    full_path = file_path if file_path else os.path.join(duckdb_data_dir, blob_path)
                    logger.info(f"Reading from local file: {full_path}")

                header = task_with.get('header', False)
                header_option = "TRUE" if header else "FALSE"

                duckdb_con.execute(f"""
                    CREATE TABLE {temp_table} AS 
                    SELECT * FROM read_csv('{full_path}', header={header_option}, auto_detect=TRUE);
                """)

                row_count = duckdb_con.execute(f"SELECT COUNT(*) FROM {temp_table}").fetchone()[0]
                logger.info(f"Read {row_count} rows from {full_path} into {temp_table}")

                schema_info = duckdb_con.execute(f"DESCRIBE {temp_table}").fetchall()
                columns = []
                for col_info in schema_info:
                    col_name = col_info[0]
                    col_type = col_info[1]
                    if col_type in ('INTEGER', 'BIGINT', 'SMALLINT', 'TINYINT'):
                        pg_type = 'INTEGER'
                    elif col_type in ('DOUBLE', 'REAL', 'FLOAT'):
                        pg_type = 'DOUBLE PRECISION'
                    elif col_type == 'VARCHAR':
                        pg_type = 'TEXT'
                    elif col_type == 'BOOLEAN':
                        pg_type = 'BOOLEAN'
                    elif col_type.startswith('TIMESTAMP'):
                        pg_type = 'TIMESTAMP'
                    elif col_type.startswith('DATE'):
                        pg_type = 'DATE'
                    else:
                        pg_type = 'TEXT'
                    columns.append(f'"{col_name}" {pg_type}')

                columns_str = ', '.join(columns)
                duckdb_con.execute(f"""
                    CREATE TABLE IF NOT EXISTS postgres_db.{table} ({columns_str})
                """)
                duckdb_con.execute(f"""
                    INSERT INTO postgres_db.{table}
                    SELECT * FROM {temp_table}
                """)
                pg_row_count = duckdb_con.execute(f"SELECT COUNT(*) FROM postgres_db.{table}").fetchone()[0]
                logger.info(f"Inserted {pg_row_count} rows into PostgreSQL table {table}")
                duckdb_con.execute(f"DROP TABLE IF EXISTS {temp_table}")

                results = {
                    "source": full_path,
                    "rows_read": row_count,
                    "rows_inserted": pg_row_count,
                    "target_table": table
                }

        duckdb_con.close()
        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()

        try:
            json_results = json.dumps(results, cls=DateTimeEncoder)
            parsed_results = json.loads(json_results)

            if log_event_callback:
                log_event_callback(
                    'task_complete', task_id, task_name, 'duckdb',
                    'success', duration, context, parsed_results,
                    {'with_params': task_with}, event_id
                )

            return {
                'id': task_id,
                'status': 'success',
                'data': parsed_results
            }
        except Exception as json_error:
            logger.warning(f"Error serializing results with DateTimeEncoder: {str(json_error)}. Returning original results.")

            if log_event_callback:
                log_event_callback(
                    'task_complete', task_id, task_name, 'duckdb',
                    'success', duration, context, str(results),
                    {'with_params': task_with}, event_id
                )

            return {
                'id': task_id,
                'status': 'success',
                'data': str(results)
            }

    except Exception as e:
        if "Object of type datetime is not JSON serializable" in str(e):
            try:
                error_msg = "Original error: datetime serialization issue. Using custom encoder to handle datetime objects."
                logger.warning(error_msg)
                json_results = json.dumps(results, cls=DateTimeEncoder)
                parsed_results = json.loads(json_results)

                end_time = datetime.datetime.now()
                duration = (end_time - start_time).total_seconds()

                if log_event_callback:
                    log_event_callback(
                        'task_complete', task_id, task_name, 'duckdb',
                        'success', duration, context, parsed_results,
                        {'with_params': task_with}, event_id
                    )

                return {
                    'id': task_id,
                    'status': 'success',
                    'data': parsed_results
                }
            except Exception as json_error:
                error_msg = f"Failed to handle datetime serialization: {str(json_error)}"
                logger.error(error_msg, exc_info=True)
        else:
            error_msg = str(e)

        logger.error(f"DuckDB task execution error: {error_msg}.", exc_info=True)
        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()
        logger.debug(f"DUCKDB.EXECUTE_DUCKDB_TASK: Task duration={duration} seconds (error path)")

        if log_event_callback:
            logger.debug(f"DUCKDB.EXECUTE_DUCKDB_TASK: Writing task_error event log")
            log_event_callback(
                'task_error', task_id, task_name, 'duckdb',
                'error', duration, context, None,
                {'error': error_msg, 'with_params': task_with}, None
            )

        # Include Python traceback so the worker can forward it and EventService persists it
        tb_text = traceback.format_exc()
        return {
            'id': task_id,
            'status': 'error',
            'error': error_msg,
            'traceback': tb_text
        }


__all__ = ['execute_duckdb_task', 'get_duckdb_connection']
