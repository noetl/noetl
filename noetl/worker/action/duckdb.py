import os
import re
import uuid
import datetime
import threading
from contextlib import contextmanager
from typing import Dict, Any
from decimal import Decimal

from jinja2 import Environment

from noetl.common import DateTimeEncoder, make_serializable
from noetl.logger import setup_logger
from noetl.render import render_template

try:
    import duckdb
    DUCKDB_AVAILABLE = True
except Exception:
    DUCKDB_AVAILABLE = False

logger = setup_logger(__name__, include_location=True)

_duckdb_connections: Dict[str, Any] = {}
_connection_lock = threading.Lock()


@contextmanager
def get_duckdb_connection(duckdb_file_path: str):
    """Context manager for shared DuckDB connections to maintain attachments"""
    logger.debug("=== DUCKDB.GET_CONNECTION: Function entry ===")
    logger.debug(f"DUCKDB.GET_CONNECTION: duckdb_file_path={duckdb_file_path}")

    with _connection_lock:
        if duckdb_file_path not in _duckdb_connections:
            logger.debug(f"DUCKDB.GET_CONNECTION: Creating new DuckDB connection for {duckdb_file_path}")
            _duckdb_connections[duckdb_file_path] = duckdb.connect(duckdb_file_path)
        else:
            logger.debug(f"DUCKDB.GET_CONNECTION: Reusing existing DuckDB connection for {duckdb_file_path}")
        conn = _duckdb_connections[duckdb_file_path]

    try:
        logger.debug("DUCKDB.GET_CONNECTION: Yielding connection")
        yield conn
    finally:
        pass


def sql_split(sql_text: str):
    commands = []
    current_command = []
    in_single_quote = False
    in_double_quote = False
    i = 0

    while i < len(sql_text):
        char = sql_text[i]

        if char == "'" and not in_double_quote:
            if i > 0 and sql_text[i - 1] == '\\':
                pass
            else:
                in_single_quote = not in_single_quote
        elif char == '"' and not in_single_quote:
            if i > 0 and sql_text[i - 1] == '\\':
                pass
            else:
                in_double_quote = not in_double_quote
        elif char == ';' and not in_single_quote and not in_double_quote:
            cmd = ''.join(current_command).strip()
            if cmd:
                commands.append(cmd)
            current_command = []
            i += 1
            continue

        current_command.append(char)
        i += 1

    cmd = ''.join(current_command).strip()
    if cmd:
        commands.append(cmd)

    return commands


def execute_duckdb_task(task_config: Dict, context: Dict, jinja_env: Environment, task_with: Dict, log_event_callback=None) -> Dict:
    """
    Execute a DuckDB task.
    """
    logger.debug("=== DUCKDB.EXECUTE_TASK: Function entry ===")
    logger.debug(f"DUCKDB.EXECUTE_TASK: Parameters - task_config={task_config}, task_with={task_with}")

    if not DUCKDB_AVAILABLE:
        task_id = str(uuid.uuid4())
        task_name = task_config.get('task', 'duckdb_task')
        error_msg = "DuckDB is not installed. Install it with 'pip install noetl[duckdb]'."
        logger.error(error_msg)

        if log_event_callback:
            log_event_callback(
                'task_error', task_id, task_name, 'duckdb',
                'error', 0, context, None,
                {'error': error_msg, 'with_params': task_with}, None
            )

        return {
            'id': task_id,
            'status': 'error',
            'error': error_msg
        }

    task_id = str(uuid.uuid4())
    task_name = task_config.get('task', 'duckdb_task')
    start_time = datetime.datetime.now()

    logger.debug(f"DUCKDB.EXECUTE_TASK: Generated task_id={task_id}")
    logger.debug(f"DUCKDB.EXECUTE_TASK: Task name={task_name}")
    logger.debug(f"DUCKDB.EXECUTE_TASK: Start time={start_time.isoformat()}")

    try:
        commands = task_config.get('command', task_config.get('commands', []))

        if isinstance(commands, str):
            commands_rendered = render_template(jinja_env, commands, {**context, **task_with})
            cmd_lines = []
            for line in commands_rendered.split('\n'):
                line = line.strip()
                if line and not line.startswith('--'):
                    cmd_lines.append(line)
            commands_text = ' '.join(cmd_lines)
            commands = sql_split(commands_text)

        bucket = task_with.get('bucket', context.get('bucket', ''))
        blob_path = task_with.get('blob', '')
        file_path = task_with.get('file', '')
        table = task_with.get('table', '')

        event_id = None
        if log_event_callback:
            logger.debug(f"DUCKDB.EXECUTE_TASK: Writing task_start event log")
            event_id = log_event_callback(
                'task_start', task_id, task_name, 'duckdb',
                'in_progress', 0, context, None,
                {'with_params': task_with}, None
            )
            logger.debug(f"DUCKDB.EXECUTE_TASK: Task start event_id={event_id}")

        duckdb_file = task_with.get('db', context.get('duckdb_file', ':memory:'))
        if duckdb_file == '':
            duckdb_file = ':memory:'
        duckdb_file = str(duckdb_file)

        with get_duckdb_connection(duckdb_file) as conn:
            cur = conn.cursor()
            logger.debug(f"DUCKDB.EXECUTE_TASK: Connected to DuckDB at {duckdb_file}")

            poll_timeout = float(task_with.get('poll_timeout', 60))
            poll_interval = float(task_with.get('poll_interval', 5))

            result_data = None

            for cmd in commands:
                cmd = cmd.strip()
                if not cmd:
                    continue

                logger.debug(f"DUCKDB.EXECUTE_TASK: Executing command: {cmd}")

                match = re.match(r"ATTACH\s+'([^']+)'\s+AS\s+([^\s;]+)", cmd, re.IGNORECASE)
                if match:
                    file_path_to_attach = match.group(1)
                    schema = match.group(2)
                    logger.debug(f"DUCKDB.EXECUTE_TASK: Attaching database {file_path_to_attach} as schema {schema}")
                    cur.execute(cmd)
                    continue

                if cmd.upper().startswith('COPY '):
                    if 'TO ' in cmd.upper():
                        cur.execute(cmd)
                        continue
                    else:
                        logger.error("COPY TO operation is currently not supported in the new implementation.")
                        raise Exception("COPY TO operation is currently not supported in the new implementation.")

                def replace_cast(match):
                    value = match.group(1)
                    return f"'{value}'::TIMESTAMP"

                cmd = re.sub(r"CAST\('([^']+)' AS TIMESTAMP\)", replace_cast, cmd, flags=re.IGNORECASE)

                cur.execute(cmd)

                if cur.description:
                    try:
                        records = cur.fetchall()
                        result_data = [
                            {k: (float(v) if isinstance(v, Decimal) else v) for k, v in zip([col[0] for col in cur.description], row)}
                            for row in records
                        ]
                        logger.debug(f"DUCKDB.EXECUTE_TASK: Query returned {len(result_data)} records")
                    except Exception as e:
                        logger.error(f"DUCKDB.EXECUTE_TASK: Error fetching results: {e}")
                else:
                    result_data = {'message': 'Command executed successfully'}

            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()

            if log_event_callback:
                logger.debug(f"DUCKDB.EXECUTE_TASK: Writing task_complete event log")
                log_event_callback(
                    'task_complete', task_id, task_name, 'duckdb',
                    'success', duration, context, result_data,
                    {'with_params': task_with}, event_id
                )

            result = {
                'id': task_id,
                'status': 'success',
                'data': result_data
            }
            logger.debug(f"DUCKDB.EXECUTE_TASK: Returning success result={json_dumps(result)}")
            logger.debug("=== DUCKDB.EXECUTE_TASK: Function exit (success) ===")
            return result

    except Exception as e:
        error_msg = str(e)
        logger.error(f"DUCKDB.EXECUTE_TASK: Exception - {error_msg}", exc_info=True)

        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()

        if log_event_callback:
            logger.debug(f"DUCKDB.EXECUTE_TASK: Writing task_error event log")
            log_event_callback(
                'task_error', task_id, task_name, 'duckdb',
                'error', duration, context, None,
                {'error': error_msg, 'with_params': task_with}, event_id
            )

        return {
            'id': task_id,
            'status': 'error',
            'error': error_msg
        }


def json_dumps(data: Any) -> str:
    try:
        import json
        return json.dumps(make_serializable(data), cls=DateTimeEncoder)
    except Exception:
        try:
            return json.dumps(data)
        except Exception:
            return str(data)


__all__ = [
    "execute_duckdb_task",
    "get_duckdb_connection",
    "sql_split",
]
