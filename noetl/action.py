import os
import uuid
import datetime
import httpx
import duckdb
import psycopg
import json
from typing import Dict, Any
from jinja2 import Environment
from noetl.common import render_template, setup_logger
from noetl.common import DateTimeEncoder



logger = setup_logger(__name__, include_location=True)

def execute_http_task(task_config: Dict, context: Dict, jinja_env: Environment, mock_mode: bool = False, log_event_callback=None) -> Dict:
    """
    Execute an HTTP task.

    Args:
        task_config: The task configuration
        context: The context to use for rendering templates
        jinja_env: The Jinja2 environment for template rendering
        mock_mode: Whether to use mock mode for testing
        log_event_callback: A callback function to log events

    Returns:
        A dictionary of the task result
    """

    task_id = str(uuid.uuid4())
    task_name = task_config.get('task', 'http_task')
    start_time = datetime.datetime.now()

    try:
        method = task_config.get('method', 'GET').upper()
        endpoint = render_template(jinja_env, task_config.get('endpoint', ''), context)
        params = render_template(jinja_env, task_config.get('params', {}), context)
        payload = render_template(jinja_env, task_config.get('payload', {}), context)

        logger.info(f"HTTP {method} request to {endpoint}")

        event_id = None
        if log_event_callback:
            event_id = log_event_callback(
                'task_start', task_id, task_name, 'http',
                'in_progress', 0, context, None,
                {'method': method, 'endpoint': endpoint}, None
            )

        if mock_mode:
            response_data = {"data": "mocked_response", "status": "success"}

            if 'forecast' in endpoint:
                temp_data = [20, 22, 25, 28, 30, 26, 24]
                max_temp = max(temp_data)
                temp_threshold = context.get('temperature_threshold', 25)
                alert = max_temp > temp_threshold

                response_data = {
                    "data": {
                        "hourly": {
                            "temperature_2m": temp_data,
                            "precipitation_probability": [0, 10, 20, 30, 20, 10, 0],
                            "windspeed_10m": [10, 12, 15, 18, 22, 19, 14]
                        }
                    },
                    "alert": alert,
                    "max_temp": max_temp
                }
            elif 'districts' in endpoint:
                response_data = {
                    "data": [
                        {"name": "Downtown", "population": 50000},
                        {"name": "North", "population": 25000},
                        {"name": "East", "population": 30000},
                        {"name": "Mordor", "population": 666}
                    ]
                }

            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()

            if log_event_callback:
                log_event_callback(
                    'task_complete', task_id, task_name, 'http',
                    'success', duration, context, response_data,
                    {'method': method, 'endpoint': endpoint}, event_id
                )

            return {
                'id': task_id,
                'status': 'success',
                'data': response_data
            }
        else:
            headers = render_template(jinja_env, task_config.get('headers', {}), context)
            timeout = task_config.get('timeout', 30)

            try:
                with httpx.Client(timeout=timeout) as client:
                    if method == 'GET':
                        response = client.get(endpoint, params=params, headers=headers)
                    elif method == 'POST':
                        response = client.post(endpoint, json=payload, params=params, headers=headers)
                    elif method == 'PUT':
                        response = client.put(endpoint, json=payload, params=params, headers=headers)
                    elif method == 'DELETE':
                        response = client.delete(endpoint, params=params, headers=headers)
                    elif method == 'PATCH':
                        response = client.patch(endpoint, json=payload, params=params, headers=headers)
                    else:
                        raise ValueError(f"Unsupported HTTP method: {method}")
                    response.raise_for_status()
                    try:
                        response_data = response.json()
                    except ValueError:
                        response_data = {"text": response.text}

                    response_data = {
                        "data": response_data,
                        "status_code": response.status_code,
                        "headers": dict(response.headers)
                    }

                    end_time = datetime.datetime.now()
                    duration = (end_time - start_time).total_seconds()

                    if log_event_callback:
                        log_event_callback(
                            'task_complete', task_id, task_name, 'http',
                            'success', duration, context, response_data,
                            {'method': method, 'endpoint': endpoint}, event_id
                        )

                    return {
                        'id': task_id,
                        'status': 'success',
                        'data': response_data
                    }

            except httpx.HTTPStatusError as e:
                error_msg = f"HTTP error: {e.response.status_code} - {e.response.text}"
                raise Exception(error_msg)
            except httpx.RequestError as e:
                error_msg = f"Request error: {str(e)}"
                raise Exception(error_msg)

    except Exception as e:
        error_msg = str(e)
        logger.error(f"HTTP task error: {error_msg}")
        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()

        if log_event_callback:
            log_event_callback(
                'task_error', task_id, task_name, 'http',
                'error', duration, context, None,
                {'error': error_msg}, None
            )

        return {
            'id': task_id,
            'status': 'error',
            'error': error_msg
        }

def execute_python_task(task_config: Dict, context: Dict, jinja_env: Environment, log_event_callback=None) -> Dict:
    """
    Execute a Python task.

    Args:
        task_config: The task configuration
        context: The context for rendering templates
        jinja_env: The Jinja2 environment for template rendering
        log_event_callback: A callback function to log events

    Returns:
        A dictionary of the task result
    """

    task_id = str(uuid.uuid4())
    task_name = task_config.get('task', 'python_task')
    start_time = datetime.datetime.now()

    try:
        code = task_config.get('code', '')
        task_with = render_template(jinja_env, task_config.get('with', {}), context)

        event_id = None
        if log_event_callback:
            event_id = log_event_callback(
                'task_start', task_id, task_name, 'python',
                'in_progress', 0, context, None,
                {'with_params': task_with}, None
            )

        exec_globals = {
            '__builtins__': __builtins__,
            'logger': logger
        }
        exec_locals = {}
        exec(code, exec_globals, exec_locals)

        if 'main' in exec_locals:
            result_data = exec_locals['main'](**task_with)
            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()

            if log_event_callback:
                log_event_callback(
                    'task_complete', task_id, task_name, 'python',
                    'success', duration, context, result_data,
                    {'with_params': task_with}, event_id
                )

            return {
                'id': task_id,
                'status': 'success',
                'data': result_data
            }
        else:
            error_msg = "Main function must be defined in Python task."
            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()

            if log_event_callback:
                log_event_callback(
                    'task_error', task_id, task_name, 'python',
                    'error', duration, context, None,
                    {'error': error_msg}, event_id
                )

            return {
                'id': task_id,
                'status': 'error',
                'error': error_msg
            }

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Python task execution error: {error_msg}.", exc_info=True)
        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()

        if log_event_callback:
            log_event_callback(
                'task_error', task_id, task_name, 'python',
                'error', duration, context, None,
                {'error': error_msg}, None
            )

        return {
            'id': task_id,
            'status': 'error',
            'error': error_msg
        }



def execute_duckdb_task(task_config: Dict, context: Dict, jinja_env: Environment, log_event_callback=None) -> Dict:
    """
    Execute a DuckDB task.

    Args:
        task_config: The task configuration
        context: The context for rendering templates
        jinja_env: The Jinja2 environment for template rendering
        log_event_callback: A callback function to log events

    Returns:
        A dictionary of the task result
    """


    task_id = str(uuid.uuid4())
    task_name = task_config.get('task', 'duckdb_task')
    start_time = datetime.datetime.now()

    try:
        commands = task_config.get('command', task_config.get('commands', []))
        if isinstance(commands, str):
            commands_rendered = render_template(jinja_env, commands, {**context, **task_config.get('with', {})})
            cmd_lines = []
            for line in commands_rendered.split('\n'):
                line = line.strip()
                if line and not line.startswith('--'):
                    cmd_lines.append(line)
            commands_text = ' '.join(cmd_lines)
            commands = [cmd.strip() for cmd in commands_text.split(';') if cmd.strip()]
        task_with = render_template(jinja_env, task_config.get('with', {}), context)
        bucket = task_with.get('bucket', context.get('bucket', ''))
        blob_path = task_with.get('blob', '')
        file_path = task_with.get('file', '')
        table = task_with.get('table', '')

        event_id = None
        if log_event_callback:
            event_id = log_event_callback(
                'task_start', task_id, task_name, 'duckdb',
                'in_progress', 0, context, None,
                {'with_params': task_with}, None
            )

        import time
        duckdb_data_dir = os.environ.get("NOETL_DATA_DIR", "./data")
        execution_id = context.get("execution_id") or context.get("jobId") or (context.get("job", {}).get("uuid") if isinstance(context.get("job"), dict) else None) or "default"
        if isinstance(execution_id, str) and ('{{' in execution_id or '}}' in execution_id):
            execution_id = render_template(jinja_env, execution_id, context)
        duckdb_file = os.path.join(duckdb_data_dir, "noetldb", f"duckdb_{execution_id}.duckdb")
        os.makedirs(os.path.dirname(duckdb_file), exist_ok=True)
        logger.info(f"Connecting to DuckDB at {duckdb_file} for execution {execution_id}")
        duckdb_con = duckdb.connect(duckdb_file)
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
        duckdb_con.execute("INSTALL httpfs;")
        duckdb_con.execute("LOAD httpfs;")
        key_id = task_with.get('key_id')
        secret_key = task_with.get('secret_key')
        if key_id and secret_key:
            logger.info("Setting up S3 credentials for GCS operations")
            try:
                duckdb_con.execute(f"""
                    CREATE OR REPLACE CHAIN gcs_chain (
                        TYPE S3,
                        ENDPOINT 'storage.googleapis.com',
                        REGION 'auto',
                        URL_STYLE 'path',
                        USE_SSL true,
                        KEY_ID '{key_id}',
                        SECRET_KEY '{secret_key}'
                    );
                """)
                logger.info("Successfully created GCS configuration chain")
                try:
                    secrets_list = duckdb_con.execute("SELECT * FROM duckdb_secrets();").fetchall()
                    gcs_secret_exists = any(secret[0] == 'gcs_secret' for secret in secrets_list)

                    if not gcs_secret_exists:
                        logger.info("Creating persistent GCS secret")
                        duckdb_con.execute(f"CREATE PERSISTENT SECRET gcs_secret (TYPE S3, KEY_ID '{key_id}', SECRET '{secret_key}');")
                except Exception as e:
                    logger.warning(f"Error checking or creating GCS secret: {e}. Will continue with chain configuration.")
            except Exception as e:
                logger.warning(f"Error creating GCS chain: {e}. Falling back to individual parameter configuration.")
                duckdb_con.execute("set s3_endpoint='storage.googleapis.com';")
                duckdb_con.execute("set s3_region='auto';")
                duckdb_con.execute("set s3_url_style='path';")
                duckdb_con.execute("set s3_use_ssl=true;")
                duckdb_con.execute(f"set s3_access_key_id='{key_id}';")
                duckdb_con.execute(f"set s3_secret_access_key='{secret_key}';")
                try:
                    secrets_list = duckdb_con.execute("SELECT * FROM duckdb_secrets();").fetchall()
                    gcs_secret_exists = any(secret[0] == 'gcs_secret' for secret in secrets_list)

                    if not gcs_secret_exists:
                        logger.info("Creating persistent GCS secret")
                        duckdb_con.execute(f"CREATE PERSISTENT SECRET gcs_secret (TYPE S3, KEY_ID '{key_id}', SECRET '{secret_key}');")
                except Exception as secret_e:
                    logger.warning(f"Error checking or creating GCS secret: {secret_e}. Will continue with session credentials.")

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
                    cmd = render_template(jinja_env, cmd, context)
                    if "CREATE SECRET" in cmd or "CREATE OR REPLACE CHAIN" in cmd:
                        import re
                        cmd = re.sub(r"{{[^}]*\|\s*default\(['\"]([^'\"]*)['\"].*?}}", r"\1", cmd)
                        cmd = re.sub(r"default\('([^']*)'\)", r'default("\1")', cmd)
                        cmd = re.sub(r"(HOST|DATABASE|USER|PASSWORD|ENDPOINT|REGION|URL_STYLE|KEY_ID|SECRET_KEY) '([^']*)'", r'\1 "\2"', cmd)
                logger.info(f"Executing DuckDB command: {cmd}")
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
                    result = duckdb_con.execute(cmd).fetchall()
                    results[f"command_{i}"] = result

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

        if log_event_callback:
            log_event_callback(
                'task_error', task_id, task_name, 'duckdb',
                'error', duration, context, None,
                {'error': error_msg}, None
            )

        return {
            'id': task_id,
            'status': 'error',
            'error': error_msg
        }

def execute_postgres_task(task_config: Dict, context: Dict, jinja_env: Environment, log_event_callback=None) -> Dict:
    """
    Execute a Postgres task.

    Args:
        task_config: The task configuration
        context: The context for rendering templates
        jinja_env: The Jinja2 environment for template rendering
        log_event_callback: A callback function to log events

    Returns:
        A dictionary of the task result
    """
    task_id = str(uuid.uuid4())
    task_name = task_config.get('task', 'postgres_task')
    start_time = datetime.datetime.now()

    try:
        commands = task_config.get('command', task_config.get('commands', []))
        if isinstance(commands, str):
            commands_rendered = render_template(jinja_env, commands, {**context, **task_config.get('with', {})})
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

        task_with = render_template(jinja_env, task_config.get('with', {}), context)

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

        results = {}

        if commands:
            for i, cmd in enumerate(commands):
                logger.info(f"Executing Postgres command: {cmd}")
                is_select = cmd.strip().upper().startswith("SELECT")
                is_call = cmd.strip().upper().startswith("CALL")
                returns_data = is_select or "RETURNING" in cmd.upper() or is_call

                try:
                    with conn.cursor() as cursor:
                        cursor.execute(cmd)

                        if returns_data:
                            column_names = [desc[0] for desc in cursor.description] if cursor.description else []
                            rows = cursor.fetchall()
                            result_data = []
                            for row in rows:
                                row_dict = {}
                                for i, col_name in enumerate(column_names):
                                    if isinstance(row[i], dict) or (isinstance(row[i], str) and (row[i].startswith('{') or row[i].startswith('['))):
                                        try:
                                            row_dict[col_name] = row[i]
                                        except:
                                            row_dict[col_name] = row[i]
                                    else:
                                        row_dict[col_name] = row[i]
                                result_data.append(row_dict)

                            results[f"command_{i}"] = {
                                "status": "success",
                                "rows": result_data,
                                "row_count": len(rows),
                                "columns": column_names
                            }
                        else:
                            conn.commit()
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
        conn.close()

        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()

        if log_event_callback:
            log_event_callback(
                'task_complete', task_id, task_name, 'postgres',
                'success', duration, context, results,
                {'with_params': task_with}, event_id
            )

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
                {'error': error_msg}, None
            )

        return {
            'id': task_id,
            'status': 'error',
            'error': error_msg
        }



def execute_secrets_task(task_config: Dict, context: Dict, secret_manager, log_event_callback=None) -> Dict:
    """
    Execute a secret's task.

    Args:
        task_config: The task configuration
        context: The context to use for rendering templates
        secret_manager: The SecretManager instance
        log_event_callback: A callback function to log events

    Returns:
        A dictionary of the task result
    """
    def log_event_wrapper(event_type, task_id, task_name, node_type, status, duration,
                          context, output_result, metadata, parent_event_id):
        if log_event_callback:
            return log_event_callback(
                event_type, task_id, task_name, node_type,
                status, duration, context, output_result,
                metadata, parent_event_id
            )
        return None

    return secret_manager.get_secret(task_config, context, log_event_wrapper)

def execute_task(task_config: Dict, task_name: str, context: Dict, jinja_env: Environment,
                 secret_manager=None, mock_mode: bool = False, log_event_callback=None) -> Dict:
    """
    Execute a task type.

    Args:
        task_config: The task configuration
        task_name: The name of the task
        context: The context for rendering templates
        jinja_env: The Jinja2 environment for template rendering
        secret_manager: The SecretManager instance
        mock_mode: Flag to use mock mode for testing
        log_event_callback: A callback function to log events

    Returns:
        A dictionary of the task result
    """

    if not task_config:
        task_id = str(uuid.uuid4())
        error_msg = f"Task not found: {task_name}"

        if log_event_callback:
            log_event_callback(
                'task_error', task_id, task_name, 'unknown',
                'error', 0, context, None,
                {'error': error_msg}, None
            )

        return {
            'id': task_id,
            'status': 'error',
            'error': error_msg
        }

    task_type = task_config.get('type', 'http')
    task_id = str(uuid.uuid4())
    start_time = datetime.datetime.now()

    event_id = None
    if log_event_callback:
        event_id = log_event_callback(
            'task_execute', task_id, task_name, f'task.{task_type}',
            'in_progress', 0, context, None,
            {'task_type': task_type}, None
        )

    task_with = {}
    if 'with' in task_config:
        task_with = render_template(jinja_env, task_config.get('with'), context)
        context.update(task_with)

    if task_type == 'http':
        result = execute_http_task(task_config, context, jinja_env, mock_mode, log_event_callback)
    elif task_type == 'python':
        result = execute_python_task(task_config, context, jinja_env, log_event_callback)
    elif task_type == 'duckdb':
        result = execute_duckdb_task(task_config, context, jinja_env, log_event_callback)
    elif task_type == 'postgres':
        result = execute_postgres_task(task_config, context, jinja_env, log_event_callback)
    elif task_type == 'secrets':
        if not secret_manager:
            error_msg = "SecretManager is required for secrets tasks."

            if log_event_callback:
                log_event_callback(
                    'task_error', task_id, task_name, f'task.{task_type}',
                    'error', 0, context, None,
                    {'error': error_msg}, event_id
                )

            return {
                'id': task_id,
                'status': 'error',
                'error': error_msg
            }

        result = execute_secrets_task(task_config, context, secret_manager, log_event_callback)
    else:
        error_msg = f"Unsupported task type: {task_type}"

        if log_event_callback:
            log_event_callback(
                'task_error', task_id, task_name, f'task.{task_type}',
                'error', 0, context, None,
                {'error': error_msg}, event_id
            )

        result = {
            'id': task_id,
            'status': 'error',
            'error': error_msg
        }

    if 'return' in task_config and result['status'] == 'success':
        transformed_result = render_template(jinja_env, task_config['return'], {
            **context,
            'result': result['data'],
            'status': result['status']
        })

        result['data'] = transformed_result

    end_time = datetime.datetime.now()
    duration = (end_time - start_time).total_seconds()

    if log_event_callback:
        log_event_callback(
            'task_complete', task_id, task_name, f'task.{task_type}',
            result['status'], duration, context, result.get('data'),
            {'task_type': task_type}, event_id
        )

    return result

def report_event(event_data: Dict, server_url: str) -> Dict:
    """
    Report an event to the server.

    Args:
        event_data: The event data to report
        server_url: The URL of the server

    Returns:
        The server response
    """
    timeout = 5.0

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(f"{server_url}/events", json=event_data)
            response.raise_for_status()
            report_event.failure_count = 0
            return response.json()
    except Exception as e:
        if not hasattr(report_event, 'failure_count'):
            report_event.failure_count = 0
        report_event.failure_count += 1

        logger.error(f"Error reporting event to server (failure {report_event.failure_count}): {e}.")

        if report_event.failure_count > 3:
            logger.warning(f"Too many failures ({report_event.failure_count}). Disabling event reporting.")
            return {"status": "error", "error": "Event reporting disabled. Too many failures."}

        return {"status": "error", "error": str(e)}
