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

logger = setup_logger(__name__, include_location=True)

_duckdb_connections = {}
_connection_lock = threading.Lock()


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
        except Exception:
            pass

        if isinstance(commands, str):
            commands_rendered = render_template(jinja_env, commands, {**context, **(processed_task_with or {})})
            try:
                logger.info(f"DUCKDB.EXECUTE_DUCKDB_TASK: commands_rendered (first 400 chars)={commands_rendered[:400]}")
            except Exception:
                pass
            cmd_lines = []
            for line in commands_rendered.split('\n'):
                line = line.strip()
                if line and not line.startswith('--'):
                    cmd_lines.append(line)
            commands_text = ' '.join(cmd_lines)
            from . import sql_split
            commands = sql_split(commands_text)

        # Extract cloud URI scopes mentioned in the commands (for explicit DuckDB SECRET scoping)
        uri_scopes = {"gs": set(), "s3": set()}
        try:
            import re as _re_extract
            for _cmd in commands if isinstance(commands, list) else []:
                for m in _re_extract.finditer(r"\b(gs|s3)://([^/'\s)]+)(/|\b)", _cmd):
                    scheme = m.group(1)
                    bucket = m.group(2)
                    # Use bucket-level scope; DuckDB matches on prefix
                    scope = f"{scheme}://{bucket}"
                    uri_scopes.setdefault(scheme, set()).add(scope)
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

        # Ensure httpfs is available BEFORE secrets are created (secret types are registered by extensions)
        try:
            duckdb_con.execute("INSTALL httpfs;")
            duckdb_con.execute("LOAD httpfs;")
        except Exception as _httpfs_e:
            logger.warning(f"DUCKDB: failed to install/load httpfs: {_httpfs_e}")

        # Optional: attach multiple external databases from credentials mapping/list
        # Step-level preferred: task_config['credentials'] as a mapping of alias -> { kind, credential, spec, dsn }
        # Back-compat: with.credentials can be a list or mapping too
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
                        kind = (ent.get('kind') or ent.get('db_type') or 'postgres').lower()
                        dsn = ent.get('dsn') or ent.get('db_conn_string')
                        spec = ent.get('spec') if isinstance(ent.get('spec'), dict) else {}
                        cred_ref = ent.get('credential') or ent.get('credentialRef')

                        # Resolve credential by name/id from server when provided
                        cred_data = None
                        if cred_ref and not dsn:
                            try:
                                base = os.environ.get('NOETL_SERVER_URL', 'http://localhost:8082').rstrip('/')
                                if not base.endswith('/api'):
                                    base = base + '/api'
                                url = f"{base}/credentials/{cred_ref}?include_data=true"
                                with httpx.Client(timeout=5.0) as _c:
                                    _r = _c.get(url)
                                    if _r.status_code == 200:
                                        body = _r.json() or {}
                                        cred_data = (body.get('data') or {}) if isinstance(body, dict) else None
                            except Exception:
                                cred_data = None

                        # Explicitly configure DuckDB Secrets for cloud access
                        if kind in ('gcs', 'gcs_hmac', 's3', 's3_hmac'):
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
                            provider = 'GCS' if kind in ('gcs','gcs_hmac') else None
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
                            created_any = False
                            if scopes:
                                for sc in scopes:
                                    secret_name = f"{secret_base}"
                                    # When multiple scopes, differentiate names to avoid collisions
                                    if len(scopes) > 1:
                                        scope_tag = re.sub(r"[^a-zA-Z0-9_]+", "_", sc)
                                        secret_name = f"{secret_base}_{scope_tag}"
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
                                    parts.append(f"SCOPE '{sc}'")
                                    ddl = f"CREATE OR REPLACE SECRET {secret_name} (\n        {', '.join(parts)}\n    );"
                                    logger.info(f"DUCKDB: creating scoped secret {secret_name} for {sc}")
                                    duckdb_con.execute(ddl)
                                    created_any = True
                            else:
                                # Create an unscoped secret; callers must still reference exact URI in commands
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
                                ddl = f"CREATE OR REPLACE SECRET {secret_base} (\n        {', '.join(parts)}\n    );"
                                logger.info(f"DUCKDB: creating unscoped secret {secret_base}")
                                duckdb_con.execute(ddl)
                                created_any = True
                            if created_any:
                                logger.info(f"DUCKDB: cloud credentials configured via DuckDB Secret(s) for alias '{alias}'")
                            continue

                        conn_string = dsn or ''
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
                            if kind == 'postgres':
                                host = src.get('host') or src.get('db_host') or os.environ.get('POSTGRES_HOST', 'localhost')
                                port = src.get('port') or src.get('db_port') or os.environ.get('POSTGRES_PORT', '5434')
                                user = src.get('user') or src.get('db_user') or os.environ.get('POSTGRES_USER', 'noetl')
                                pwd = src.get('password') or src.get('db_password') or os.environ.get('POSTGRES_PASSWORD', 'noetl')
                                dbn = src.get('dbname') or src.get('database') or src.get('db_name') or os.environ.get('POSTGRES_DB', 'noetl')
                                conn_string = f"dbname={dbn} user={user} password={pwd} host={host} port={port}"
                            elif kind == 'sqlite':
                                path = src.get('path') or src.get('db_path') or os.path.join(duckdb_data_dir, 'sqlite', 'noetl.db')
                                conn_string = path
                            elif kind == 'mysql':
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
                        if kind == 'postgres':
                            duckdb_con.execute("INSTALL postgres;")
                            duckdb_con.execute("LOAD postgres;")
                            attach_opts = " (TYPE postgres)"
                        elif kind == 'mysql':
                            duckdb_con.execute("INSTALL mysql;")
                            duckdb_con.execute("LOAD mysql;")
                            attach_opts = " (TYPE mysql)"
                        elif kind == 'sqlite':
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
                            duckdb_con.execute(f"ATTACH '{conn_string}' AS {alias}{attach_opts};")
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
                                cred_data = (body.get('data') or {}) if isinstance(body, dict) else {}
                                key_id = cred_data.get('key_id')
                                secret = cred_data.get('secret_key') or cred_data.get('secret')
                                endpoint = cred_data.get('endpoint') or 'storage.googleapis.com'
                                region = cred_data.get('region') or 'auto'
                                url_style = cred_data.get('url_style') or 'path'
                                if key_id and secret:
                                    try:
                                        duckdb_con.execute("LOAD httpfs;")
                                    except Exception:
                                        pass
                                    for sc in sorted(uri_scopes.get('gs') or []):
                                        scope_tag = re.sub(r"[^a-zA-Z0-9_]+", "_", sc)
                                        sname = f"noetl_auto_gcs_{scope_tag}"
                                        ddl = f"""
                                            CREATE OR REPLACE SECRET {sname} (
                                                TYPE S3,
                                                PROVIDER GCS,
                                                KEY_ID '{key_id}',
                                                SECRET '{secret}',
                                                REGION '{region}',
                                                ENDPOINT '{endpoint}',
                                                URL_STYLE '{url_style}',
                                                USE_SSL true,
                                                SCOPE '{sc}'
                                            );
                                        """
                                        logger.info(f"DUCKDB: auto-configured GCS secret {sname} from credential '{cred_name}' for {sc}")
                                        duckdb_con.execute(ddl)
                    except Exception as _gcs_auto_e:
                        logger.warning(f"DUCKDB: failed to auto-configure GCS credentials from '{cred_name}': {_gcs_auto_e}")

            # S3
            if uri_scopes.get('s3'):
                cred_name = (
                    task_config.get('s3_credential') or task_with.get('s3_credential') or
                    task_config.get('cloud_credential') or task_with.get('cloud_credential') or
                    os.environ.get('NOETL_S3_CREDENTIAL')
                )
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
                                cred_data = (body.get('data') or {}) if isinstance(body, dict) else {}
                                key_id = cred_data.get('key_id') or cred_data.get('access_key_id')
                                secret = cred_data.get('secret_key') or cred_data.get('secret_access_key') or cred_data.get('secret')
                                endpoint = cred_data.get('endpoint') or 's3.amazonaws.com'
                                region = cred_data.get('region') or 'auto'
                                url_style = cred_data.get('url_style') or 'path'
                                if key_id and secret:
                                    try:
                                        duckdb_con.execute("LOAD httpfs;")
                                    except Exception:
                                        pass
                                    for sc in sorted(uri_scopes.get('s3') or []):
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
                            TYPE S3,
                            PROVIDER GCS,
                            KEY_ID '{key_id}',
                            SECRET '{secret_key}',
                            REGION 'auto',
                            ENDPOINT 'storage.googleapis.com',
                            URL_STYLE 'path',
                            USE_SSL true,
                            SCOPE '{sc}'
                        );
                    """
                    logger.info(f"DUCKDB: creating back-compat scoped secret {sname} -> {sc}")
                    duckdb_con.execute(ddl)
            else:
                ddl = f"""
                    CREATE OR REPLACE SECRET {secret_name} (
                        TYPE S3,
                        PROVIDER GCS,
                        KEY_ID '{key_id}',
                        SECRET '{secret_key}',
                        REGION 'auto',
                        ENDPOINT 'storage.googleapis.com',
                        URL_STYLE 'path',
                        USE_SSL true
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

        try:
            test_query = f"SELECT 1 FROM {db_alias}.sqlite_master LIMIT 1" if db_type.lower() == 'sqlite' else f"SELECT 1 FROM {db_alias}.information_schema.tables LIMIT 1"
            duckdb_con.execute(test_query)
            logger.info(f"Database '{db_alias}' is already attached.")
        except Exception as e:
            try:
                logger.info(f"Attaching {db_type} database as '{db_alias}'.")
                attach_sql = f"ATTACH '{conn_string}' AS {db_alias}{attach_options};"
                logger.debug(f"ATTACH SQL: {attach_sql}")
                duckdb_con.execute(attach_sql)
            except Exception as attach_error:
                logger.error(f"Error attaching database: {attach_error}.")
                raise

        results = {}
        if commands:
            for i, cmd in enumerate(commands):
                if isinstance(cmd, str) and ('{{' in cmd or '}}' in cmd):
                    # Render templates only; avoid post-processing that may strip quotes needed by DuckDB
                    cmd = render_template(jinja_env, cmd, context)

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
                    # Normalize COPY paths: ensure file/URI is quoted to avoid parser issues on ':' (e.g., gs://)
                    try:
                        import re as _re
                        _cmd_upper = cmd.strip().upper()
                        if _cmd_upper.startswith("COPY "):
                            # Handle COPY <table> TO <path> ( ... ) and COPY <table> FROM <path> ...
                            def _quote_copy_path(_cmd: str, _kw: str) -> str:
                                # Match 'COPY <obj> <KW> <path> (' capturing <path> as non-space/non-parenthesis
                                # Keep minimalistic to avoid heavy parsing
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
                    except Exception:
                        pass
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
