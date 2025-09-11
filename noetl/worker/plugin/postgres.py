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

    # Validate configuration first - these errors should not be caught
    # Get database connection parameters - must be provided in task 'with' parameters only
    pg_host_raw = task_with.get('db_host')
    if not pg_host_raw:
        raise ValueError("Database host not provided. Set 'db_host' in task 'with' parameters.")
    
    pg_port_raw = task_with.get('db_port')
    if not pg_port_raw:
        raise ValueError("Database port not provided. Set 'db_port' in task 'with' parameters.")
    
    pg_user_raw = task_with.get('db_user')
    if not pg_user_raw:
        raise ValueError("Database user not provided. Set 'db_user' in task 'with' parameters.")
    
    pg_password_raw = task_with.get('db_password')
    if not pg_password_raw:
        raise ValueError("Database password not provided. Set 'db_password' in task 'with' parameters.")
    
    pg_db_raw = task_with.get('db_name')
    if not pg_db_raw:
        raise ValueError("Database name not provided. Set 'db_name' in task 'with' parameters.")

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
            commands_rendered = render_template(jinja_env, commands, {**context, **processed_task_with})
            commands = []
            current_command = []
            dollar_quote = False
            dollar_quote_tag = ""

            cmd_lines = []
            for line in commands_rendered.split('\n'):
                line = line.strip()
                if line and not line.startswith('--'):
                    cmd_lines.append(line)

            commands_text = ' '.join(cmd_lines)
            i = 0
            while i < len(commands_text):
                char = commands_text[i]
                if char == '$' and (i + 1 < len(commands_text)) and (commands_text[i+1].isalnum() or commands_text[i+1] == '$'):
                    j = i + 1
                    while j < len(commands_text) and (commands_text[j].isalnum() or commands_text[j] == '_' or commands_text[j] == '$'):
                        j += 1
                    optional_tag = commands_text[i:j]
                    if dollar_quote and optional_tag == dollar_quote_tag:
                        dollar_quote = False
                        dollar_quote_tag = ""
                    elif not dollar_quote:
                        dollar_quote = True
                        dollar_quote_tag = optional_tag

                    current_command.append(commands_text[i:j])
                    i = j
                    continue
                if char == ';' and not dollar_quote:
                    current_cmd = ''.join(current_command).strip()
                    if current_cmd:
                        commands.append(current_cmd)
                    current_command = []
                else:
                    current_command.append(char)
                i += 1
            current_cmd = ''.join(current_command).strip()
            if current_cmd:
                commands.append(current_cmd)

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

        return {
            'id': task_id,
            'status': 'error',
            'error': error_msg
        }