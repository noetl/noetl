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

from noetl.render import render_template
from noetl.common import DateTimeEncoder
from noetl.logger import setup_logger

import duckdb

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
        commands = task_config.get('command', task_config.get('commands', []))

        if isinstance(commands, str):
            commands_rendered = render_template(jinja_env, commands, {**context, **task_with})
            cmd_lines = []
            for line in commands_rendered.split('\n'):
                line = line.strip()
                if line and not line.startswith('--'):
                    cmd_lines.append(line)
            commands_text = ' '.join(cmd_lines)
            from . import sql_split
            commands = sql_split(commands_text)

        bucket = task_with.get('bucket', context.get('bucket', ''))
        blob_path = task_with.get('blob', '')
        file_path = task_with.get('file', '')
        table = task_with.get('table', '')

        event_id = None
        if log_event_callback:
            logger.debug(f"DUCKDB.EXECUTE_DUCKDB_TASK: Writing task_start event log")
            event_id = log_event_callback(
                'task_start', task_id, task_name, 'duckdb',
                'in_progress', 0, context, None,
                {'with_params': task_with}, None
            )

        duckdb_data_dir = os.environ.get("NOETL_DATA_DIR", "./data")
        execution_id = context.get("execution_id") or context.get("jobId") or (context.get("job", {}).get("uuid") if isinstance(context.get("job"), dict) else None) or "default"
        if isinstance(execution_id, str) and ('{{' in execution_id or '}}' in execution_id):
            execution_id = render_template(jinja_env, execution_id, context)
        
        custom_db_path = task_config.get('database')
        if custom_db_path:
            if '{{' in custom_db_path or '}}' in custom_db_path:
                custom_db_path = render_template(jinja_env, custom_db_path, {**context, **task_with})
            duckdb_file = custom_db_path
        else:
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
                    CREATE OR REPLACE SECRET gcs_secret (
                        TYPE S3,
                        PROVIDER GCS,
                        KEY_ID '{key_id}',
                        SECRET '{secret_key}',
                        REGION 'auto',
                        ENDPOINT 'storage.googleapis.com',
                        URL_STYLE 'path',
                        USE_SSL true
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
                        cmd = re.sub(r"{{[^}]*\|\s*default\(['\"]([^'\"]*)['\"].*?}}", r"\1", cmd)
                        cmd = re.sub(r"default\('([^']*)'\)", r'default("\1")', cmd)
                        cmd = re.sub(r"(HOST|DATABASE|USER|PASSWORD|ENDPOINT|REGION|URL_STYLE|KEY_ID|SECRET_KEY) '([^']*)'", r'\1 "\2"', cmd)

                logger.info(f"Executing DuckDB command: {cmd}")

                decimal_separator = task_with.get('decimal_separator')
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

        return {
            'id': task_id,
            'status': 'error',
            'error': error_msg
        }


__all__ = ['execute_duckdb_task', 'get_duckdb_connection']
