import os
import uuid
import datetime
import json
from typing import Dict, Any

import psycopg
from jinja2 import Environment

from noetl.logger import setup_logger
from noetl.render import render_template

logger = setup_logger(__name__, include_location=True)


def execute_postgres_task(task_config: Dict, context: Dict, jinja_env: Environment, task_with: Dict, log_event_callback=None) -> Dict:
    """
    Execute a Postgres task.
    """
    task_id = str(uuid.uuid4())
    task_name = task_config.get('task', 'postgres_task')
    start_time = datetime.datetime.now()

    try:
        processed_task_with = task_with.copy()
        for key, value in task_with.items():
            if isinstance(value, str):
                processed_value = value.replace('<', '\\<').replace('>', '\\>')
                processed_value = processed_value.replace("'", "''")
                processed_task_with[key] = processed_value
                if value != processed_value:
                    logger.debug(f"Escaped special characters in {key} for SQL compatibility")

        commands = task_config.get('command', task_config.get('commands', []))
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

        pg_host_raw = task_with.get('db_host', os.environ.get('POSTGRES_HOST', 'localhost'))
        pg_port_raw = task_with.get('db_port', os.environ.get('POSTGRES_PORT', '5434'))
        pg_user_raw = task_with.get('db_user', os.environ.get('POSTGRES_USER', 'noetl'))
        pg_password_raw = task_with.get('db_password', os.environ.get('POSTGRES_PASSWORD', 'noetl'))
        pg_db_raw = task_with.get('db_name', os.environ.get('POSTGRES_DB', 'noetl'))

        pg_host = render_template(jinja_env, pg_host_raw, context) if isinstance(pg_host_raw, str) and '{{' in pg_host_raw else pg_host_raw
        pg_port = render_template(jinja_env, pg_port_raw, context) if isinstance(pg_port_raw, str) and '{{' in pg_port_raw else pg_port_raw
        pg_user = render_template(jinja_env, pg_user_raw, context) if isinstance(pg_user_raw, str) and '{{' in pg_user_raw else pg_user_raw
        pg_password = render_template(jinja_env, pg_password_raw, context) if isinstance(pg_password_raw, str) and '{{' in pg_password_raw else pg_password_raw
        pg_db = render_template(jinja_env, pg_db_raw, context) if isinstance(pg_db_raw, str) and '{{' in pg_db_raw else pg_db_raw

        if 'db_conn_string' in task_with:
            conn_string_raw = task_with.get('db_conn_string')
            pg_conn_string = render_template(jinja_env, conn_string_raw, context) if isinstance(conn_string_raw, str) and '{{' in conn_string_raw else conn_string_raw
        else:
            pg_conn_string = f"dbname={pg_db} user={pg_user} password={pg_password} host={pg_host} port={pg_port}"

        logger.info(f"Connecting to Postgres at {pg_host}:{pg_port}/{pg_db}")

        try:
            conn = psycopg.connect(pg_conn_string)
        except Exception as e:
            safe_conn_string = pg_conn_string.replace(f"password={pg_password}", "password=***")
            logger.error(f"Failed to connect to PostgreSQL with connection string: {safe_conn_string}")
            raise

        result_data = None

        try:
            with conn.cursor() as cur:
                for cmd in commands:
                    cmd = cmd.strip()
                    if not cmd:
                        continue
                    logger.debug(f"POSTGRES.EXECUTE_TASK: Executing command: {cmd}")
                    cur.execute(cmd)
                    if cur.description:
                        columns = [desc[0] for desc in cur.description]
                        rows = cur.fetchall()
                        result_data = [dict(zip(columns, row)) for row in rows]
                    else:
                        result_data = {'message': 'Command executed successfully'}
                conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass

        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()

        if log_event_callback:
            log_event_callback(
                'task_complete', task_id, task_name, 'postgres',
                'success', duration, context, result_data,
                {'with_params': task_with}, event_id
            )

        return {
            'id': task_id,
            'status': 'success',
            'data': result_data
        }

    except Exception as e:
        error_msg = str(e)
        logger.error(f"POSTGRES.EXECUTE_TASK: Exception - {error_msg}", exc_info=True)
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


__all__ = ["execute_postgres_task"]
