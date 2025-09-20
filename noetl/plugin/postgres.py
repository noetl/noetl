import os
import re
import uuid
import datetime
import psycopg
import json
from typing import Dict
from decimal import Decimal
from jinja2 import Environment
from noetl.core.common import DateTimeEncoder, make_serializable
from noetl.core.logger import setup_logger, log_error
from noetl.core.dsl.render import render_template
from noetl.worker.secrets import fetch_credential_by_key
from noetl.worker.auth_resolver import resolve_auth
from noetl.worker.auth_compatibility import transform_credentials_to_auth, validate_auth_transition

logger = setup_logger(__name__, include_location=True)


def execute_postgres_task(task_config: Dict, context: Dict, jinja_env: Environment, task_with: Dict, log_event_callback=None) -> Dict:
    """
    Execute a Postgres task.

    Args:
        task_config: The task configuration
        context: The context for rendering templates
        jinja_env: The Jinja2 environment for template rendering
        task_with: The rendered 'with' parameters dictionary
        log_event_callback: A callback function to log events

    Returns:
        A dictionary of the task result
    """
    task_id = str(uuid.uuid4())
    task_name = task_config.get('task', 'postgres_task')
    start_time = datetime.datetime.now()

    # Apply backwards compatibility transformation for deprecated 'credentials' field
    validate_auth_transition(task_config, task_with)
    task_config, task_with = transform_credentials_to_auth(task_config, task_with)

    # Resolve unified auth system
    postgres_auth = None
    try:
        # Get auth configuration (single mode for postgres)
        postgres_auth = None
        auth_config = task_config.get('auth') or task_with.get('auth')
        if auth_config:
            logger.debug("POSTGRES: Using unified auth system")
            mode, resolved_items = resolve_auth(auth_config, jinja_env, context)
            
            # For Postgres, we expect single auth mode or use the first resolved item
            resolved_auth = None
            if resolved_items:
                resolved_auth = list(resolved_items.values())[0]
            
            # For Postgres, we expect specific fields in the resolved auth
            if resolved_auth:
                logger.debug(f"POSTGRES: Resolved auth service: '{resolved_auth.service}', payload keys: {list(resolved_auth.payload.keys()) if resolved_auth.payload else 'None'}")
                
                if resolved_auth.service == 'postgres':
                    postgres_auth = resolved_auth.payload
                    logger.debug(f"POSTGRES: Using postgres auth with fields: {list(postgres_auth.keys())}")
                    
                    # Map auth fields to Postgres connection parameters
                    field_mapping = {
                        # Direct field names (already correct)
                        'db_host': 'db_host',
                        'db_port': 'db_port', 
                        'db_user': 'db_user',
                        'db_password': 'db_password',
                        'db_name': 'db_name',
                        # Alternative field names that might need mapping
                        'host': 'db_host',
                        'port': 'db_port',
                        'user': 'db_user',
                        'username': 'db_user',  # Alternative field name
                        'password': 'db_password',
                        'database': 'db_name',
                        'dbname': 'db_name',    # Alternative field name
                        'sslmode': 'sslmode',
                        'dsn': 'db_conn_string',
                        'connection_string': 'db_conn_string'
                    }
                    
                    # Apply resolved auth to task_with (task_with takes precedence)
                    for auth_key, task_key in field_mapping.items():
                        if task_key not in task_with and postgres_auth.get(auth_key) is not None:
                            task_with[task_key] = postgres_auth[auth_key]
                            logger.debug(f"POSTGRES: Mapped {auth_key}={postgres_auth[auth_key]} -> {task_key}")
                else:
                    logger.warning(f"POSTGRES: Expected 'postgres' service, got '{resolved_auth.service}'")
            else:
                logger.debug(f"POSTGRES: Auth resolved but not postgres type: {resolved_auth.service if resolved_auth else 'None'}")
    except Exception as e:
        logger.debug(f"POSTGRES: Unified auth processing failed: {e}", exc_info=True)
    
    # Legacy fallback: resolve single auth/credential reference 
    if not postgres_auth:
        try:
            # Check for legacy credential field (with deprecation warning)
            cred_ref = task_with.get('credential') or task_config.get('credential')
            if cred_ref:
                logger.warning("POSTGRES: 'credential' is deprecated; use 'auth' instead")
            
            # Also try auth if credential not found
            if not cred_ref:
                cred_ref = task_with.get('auth') or task_config.get('auth')
            
            if cred_ref and isinstance(cred_ref, str):
                logger.debug("POSTGRES: Using legacy auth system")
                try:
                    data = fetch_credential_by_key(str(cred_ref))
                except Exception:
                    data = {}
                if isinstance(data, dict):
                    # Map credential fields to Postgres connection parameters
                    field_mapping = {
                        'dsn': 'db_conn_string',
                        'db_conn_string': 'db_conn_string',
                        'db_host': 'db_host', 
                        'host': 'db_host', 
                        'pg_host': 'db_host',
                        'db_port': 'db_port', 
                        'port': 'db_port',
                        'db_user': 'db_user', 
                        'user': 'db_user',
                        'username': 'db_user',
                        'db_password': 'db_password', 
                        'password': 'db_password',
                        'db_name': 'db_name', 
                        'dbname': 'db_name',
                        'database': 'db_name',
                        'sslmode': 'sslmode'
                    }
                    
                    # Apply only missing keys in task_with
                    for src, dst in field_mapping.items():
                        if dst not in task_with and data.get(src) is not None:
                            task_with[dst] = data.get(src)
        except Exception:
            logger.debug("POSTGRES: failed to resolve legacy auth credential", exc_info=True)

    # Validate configuration first - these errors should not be caught
    # Get database connection parameters - must be provided in task 'with' parameters only
    logger.debug(f"POSTGRES: Final task_with keys: {list(task_with.keys())}")
    logger.debug(f"POSTGRES: Final task_with db params: db_host={task_with.get('db_host')}, db_port={task_with.get('db_port')}, db_user={task_with.get('db_user')}, db_password={'***' if task_with.get('db_password') else None}, db_name={task_with.get('db_name')}")
    
    pg_host_raw = task_with.get('db_host')
    pg_port_raw = task_with.get('db_port')
    pg_user_raw = task_with.get('db_user')
    pg_password_raw = task_with.get('db_password')
    pg_db_raw = task_with.get('db_name')
    _missing = []
    if not pg_host_raw: _missing.append('db_host')
    if not pg_port_raw: _missing.append('db_port')
    if not pg_user_raw: _missing.append('db_user')
    if not pg_password_raw: _missing.append('db_password')
    if not pg_db_raw: _missing.append('db_name')
    if _missing:
        raise ValueError(
            "Postgres connection is not configured. Missing: " + ", ".join(_missing) +
            ". Use `auth: <credential_key>` or `auth: {type: postgres, host: ..., user: ..., password: ..., database: ...}` on the step, or provide explicit db_* fields in `with:`."
        )

    # Build a rendering context that includes a 'workload' alias for compatibility
    render_ctx = dict(context) if isinstance(context, dict) else {}
    try:
        if isinstance(context, dict):
            if 'workload' not in render_ctx:
                render_ctx['workload'] = context
            if 'work' not in render_ctx:
                render_ctx['work'] = context
        # Also make with-params visible for simple substitutions if needed
        if isinstance(task_with, dict):
            for _k, _v in task_with.items():
                if _k not in render_ctx:
                    render_ctx[_k] = _v
    except Exception:
        # Best-effort enrichment; fall back to whatever context we have
        pass

    # Render database connection parameters with strict mode to catch undefined variables
    pg_host = render_template(jinja_env, pg_host_raw, render_ctx, strict_keys=True) if isinstance(pg_host_raw, str) and '{{' in pg_host_raw else pg_host_raw
    pg_port = render_template(jinja_env, pg_port_raw, render_ctx, strict_keys=True) if isinstance(pg_port_raw, str) and '{{' in pg_port_raw else pg_port_raw
    pg_user = render_template(jinja_env, pg_user_raw, render_ctx, strict_keys=True) if isinstance(pg_user_raw, str) and '{{' in pg_user_raw else pg_user_raw
    pg_password = render_template(jinja_env, pg_password_raw, render_ctx, strict_keys=True) if isinstance(pg_password_raw, str) and '{{' in pg_password_raw else pg_password_raw
    pg_db = render_template(jinja_env, pg_db_raw, render_ctx, strict_keys=True) if isinstance(pg_db_raw, str) and '{{' in pg_db_raw else pg_db_raw
    
    # Validate rendered values
    if not pg_host or str(pg_host).strip() == '':
        raise ValueError("Database host is empty after rendering")
    if not pg_port or str(pg_port).strip() == '':
        raise ValueError("Database port is empty after rendering")
    if not pg_user or str(pg_user).strip() == '':
        raise ValueError("Database user is empty after rendering")
    if not pg_password or str(pg_password).strip() == '':
        raise ValueError("Database password is empty after rendering")
    if not pg_db or str(pg_db).strip() == '':
        raise ValueError("Database name is empty after rendering")

    if 'db_conn_string' in task_with:
        conn_string_raw = task_with.get('db_conn_string')
        pg_conn_string = render_template(jinja_env, conn_string_raw, render_ctx, strict_keys=True) if isinstance(conn_string_raw, str) and '{{' in conn_string_raw else conn_string_raw
        if not pg_conn_string or str(pg_conn_string).strip() == '':
            raise ValueError("Database connection string is empty after rendering")
    else:
        pg_conn_string = f"dbname={pg_db} user={pg_user} password={pg_password} host={pg_host} port={pg_port}"

    try:
        processed_task_with = task_with.copy()
        for key, value in task_with.items():
            if isinstance(value, str):
                processed_value = value.replace('<', '\\<').replace('>', '\\>')
                processed_value = processed_value.replace("'", "''")
                processed_task_with[key] = processed_value
                if value != processed_value:
                    logger.debug(f"Escaped special characters in {key} for SQL compatibility")
            else:
                # Keep non-string values as-is (integers, booleans, etc.)
                processed_task_with[key] = value

        # Get base64 encoded commands (only method supported)
        command_b64 = task_config.get('command_b64', '')
        commands_b64 = task_config.get('commands_b64', '')
        
        # Decode base64 commands
        commands = ''
        if command_b64:
            import base64
            try:
                commands = base64.b64decode(command_b64.encode('ascii')).decode('utf-8')
                logger.debug(f"POSTGRES.EXECUTE_POSTGRES_TASK: Decoded base64 command, length={len(commands)} chars")
            except Exception as e:
                logger.error(f"POSTGRES.EXECUTE_POSTGRES_TASK: Failed to decode base64 command: {e}")
                raise ValueError(f"Invalid base64 command encoding: {e}")
        elif commands_b64:
            import base64
            try:
                commands = base64.b64decode(commands_b64.encode('ascii')).decode('utf-8')
                logger.debug(f"POSTGRES.EXECUTE_POSTGRES_TASK: Decoded base64 commands, length={len(commands)} chars")
            except Exception as e:
                logger.error(f"POSTGRES.EXECUTE_POSTGRES_TASK: Failed to decode base64 commands: {e}")
                raise ValueError(f"Invalid base64 commands encoding: {e}")
        else:
            raise ValueError("No command_b64 or commands_b64 field found - PostgreSQL tasks require base64 encoded commands")

        if isinstance(commands, str):
            logger.debug(f"POSTGRES: Rendering commands with context keys: {list(context.keys()) if isinstance(context, dict) else type(context)}")
            if isinstance(context, dict) and 'result' in context:
                result_val = context['result']
                logger.debug(f"POSTGRES: Found 'result' in context - type: {type(result_val)}, keys: {list(result_val.keys()) if isinstance(result_val, dict) else 'not dict'}")
            else:
                logger.debug("POSTGRES: No 'result' found in context")
            
            commands_rendered = render_template(jinja_env, commands, {**context, **processed_task_with})
            # Remove comment-only lines and squash whitespace for robust splitting
            cmd_lines = []
            for line in commands_rendered.split('\n'):
                s = line.strip()
                if s and not s.startswith('--'):
                    cmd_lines.append(s)
            commands_text = ' '.join(cmd_lines)

            # Split on semicolons, respecting single/double quotes and dollar-quoted strings
            commands = []
            current = []
            in_single = False
            in_double = False
            dollar_quote = False
            dollar_tag = ""
            i = 0
            n = len(commands_text)
            while i < n:
                ch = commands_text[i]
                # Handle dollar-quoted strings when not inside standard quotes
                if not in_single and not in_double and ch == '$':
                    j = i + 1
                    while j < n and (commands_text[j].isalnum() or commands_text[j] in ['_', '$']):
                        j += 1
                    tag = commands_text[i:j]
                    if dollar_quote and tag == dollar_tag:
                        dollar_quote = False
                        dollar_tag = ""
                    elif not dollar_quote and tag.startswith('$') and tag.endswith('$'):
                        dollar_quote = True
                        dollar_tag = tag
                    current.append(commands_text[i:j])
                    i = j
                    continue
                # Toggle single/double quotes (ignore when in dollar-quote)
                if not dollar_quote and ch == "'" and not in_double:
                    in_single = not in_single
                    current.append(ch)
                    i += 1
                    continue
                if not dollar_quote and ch == '"' and not in_single:
                    in_double = not in_double
                    current.append(ch)
                    i += 1
                    continue
                # Statement split
                if ch == ';' and not in_single and not in_double and not dollar_quote:
                    stmt = ''.join(current).strip()
                    if stmt:
                        commands.append(stmt)
                    current = []
                    i += 1
                    continue
                current.append(ch)
                i += 1
            stmt = ''.join(current).strip()
            if stmt:
                commands.append(stmt)

        event_id = None
        if log_event_callback:
            event_id = log_event_callback(
                'task_start', task_id, task_name, 'postgres',
                'in_progress', 0, context, None,
                {'with_params': task_with}, None
            )

        logger.info(f"Connecting to Postgres at {pg_host}:{pg_port}/{pg_db}")

        try:
            conn = psycopg.connect(pg_conn_string)
        except Exception as e:
            safe_conn_string = pg_conn_string.replace(f"password={pg_password}", "password=***")
            logger.error(f"Failed to connect to PostgreSQL with connection string: {safe_conn_string}")
            raise

        results = {}
        if commands:
            for i, cmd in enumerate(commands):
                logger.info(f"Executing Postgres command: {cmd}")
                is_select = cmd.strip().upper().startswith("SELECT")
                is_call = cmd.strip().upper().startswith("CALL")
                returns_data = is_select or "RETURNING" in cmd.upper()
                original_autocommit = conn.autocommit
                try:
                    if is_call:
                        conn.autocommit = True
                        with conn.cursor() as cursor:
                            cursor.execute(cmd)
                            has_results = cursor.description is not None

                            if has_results:
                                column_names = [desc[0] for desc in cursor.description]
                                rows = cursor.fetchall()
                                result_data = []
                                for row in rows:
                                    row_dict = {}
                                    for j, col_name in enumerate(column_names):
                                        if isinstance(row[j], dict) or (isinstance(row[j], str) and (
                                                row[j].startswith('{') or row[j].startswith('['))):
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
                                    "row_count": len(rows),
                                    "columns": column_names
                                }
                            else:
                                results[f"command_{i}"] = {
                                    "status": "success",
                                    "message": f"Procedure executed successfully."
                                }

                    else:
                        with conn.transaction():
                            with conn.cursor() as cursor:
                                cursor.execute(cmd)
                                has_results = cursor.description is not None

                                if has_results:
                                    column_names = [desc[0] for desc in cursor.description]
                                    rows = cursor.fetchall()
                                    result_data = []
                                    for row in rows:
                                        row_dict = {}
                                        for j, col_name in enumerate(column_names):
                                            if isinstance(row[j], dict) or (isinstance(row[j], str) and (
                                                    row[j].startswith('{') or row[j].startswith('['))):
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
                                        "row_count": len(rows),
                                        "columns": column_names
                                    }
                                else:
                                    results[f"command_{i}"] = {
                                        "status": "success",
                                        "row_count": cursor.rowcount,
                                        "message": f"Command executed. {cursor.rowcount} rows affected."
                                    }

                except Exception as cmd_error:
                    logger.error(f"Error executing Postgres command: {cmd_error}")
                    results[f"command_{i}"] = {
                        "status": "error",
                        "message": str(cmd_error)
                    }

                finally:
                    conn.autocommit = original_autocommit

        conn.close()

        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()

        has_error = False
        error_message = ""
        for cmd_key, cmd_result in results.items():
            if cmd_result.get('status') == 'error':
                has_error = True
                error_message += f"{cmd_key}: {cmd_result.get('message')}; "

        task_status = 'error' if has_error else 'success'

        if log_event_callback:
            log_event_callback(
                'task_complete' if not has_error else 'task_error',
                task_id, task_name, 'postgres',
                task_status, duration, context, results,
                {'with_params': task_with}, event_id
            )

        if has_error:
            try:
                log_error(
                    error=Exception(error_message),
                    error_type="postgres_execution",
                    template_string=str(commands),
                    context_data=make_serializable(context),
                    input_data=make_serializable(task_with),
                    execution_id=context.get('execution_id'),
                    step_id=task_id,
                    step_name=task_name
                )
            except Exception as e:
                logger.error(f"Failed to log error to database: {e}")

            return {
                'id': task_id,
                'status': 'error',
                'error': error_message.strip(),
                'data': results
            }
        else:
            return {
                'id': task_id,
                'status': 'success',
                'data': results
            }

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Postgres task execution error: {error_msg}", exc_info=True)
        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()

        if log_event_callback:
            log_event_callback(
                'task_error', task_id, task_name, 'postgres',
                'error', duration, context, None,
                {'error': error_msg, 'with_params': task_with}, None
            )

        # Best-effort traceback for worker to propagate
        import traceback as _tb
        tb_text = _tb.format_exc()
        return {
            'id': task_id,
            'status': 'error',
            'error': error_msg,
            'traceback': tb_text
        }
