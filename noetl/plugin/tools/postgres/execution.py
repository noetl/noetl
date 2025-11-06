"""
PostgreSQL SQL execution logic with transaction handling.

This module handles:
- Database connection management
- SQL statement execution with proper transaction handling
- CALL statement special handling (autocommit mode)
- Result data extraction and formatting
"""

import psycopg
from typing import Dict, List
from decimal import Decimal
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def connect_to_postgres(connection_string: str, host: str, port: str, database: str) -> psycopg.Connection:
    """
    Establish connection to PostgreSQL database.
    
    Args:
        connection_string: PostgreSQL connection string
        host: Database host (for logging)
        port: Database port (for logging)
        database: Database name (for logging)
        
    Returns:
        PostgreSQL connection object
        
    Raises:
        Exception: If connection fails
    """
    logger.info(f"Connecting to Postgres at {host}:{port}/{database}")
    try:
        conn = psycopg.connect(connection_string)
        return conn
    except Exception as e:
        # Redact password from error logging
        safe_conn_string = connection_string
        if "password=" in connection_string:
            parts = connection_string.split("password=")
            if len(parts) > 1:
                after_pwd = parts[1].split(" ")[0]
                safe_conn_string = connection_string.replace(f"password={after_pwd}", "password=***")
        logger.error(f"Failed to connect to PostgreSQL with connection string: {safe_conn_string}")
        raise


def execute_sql_statements(conn: psycopg.Connection, commands: List[str]) -> Dict[str, Dict]:
    """
    Execute multiple SQL statements and collect results.
    
    This function handles:
    - SELECT statements and statements with RETURNING clause
    - CALL statements (using autocommit mode)
    - DML statements (INSERT, UPDATE, DELETE)
    - DDL statements (CREATE, ALTER, DROP)
    
    Args:
        conn: PostgreSQL connection object
        commands: List of SQL statement strings to execute
        
    Returns:
        Dictionary mapping command indices to result dictionaries containing:
        - status: 'success' or 'error'
        - rows: List of row dictionaries (for SELECT/RETURNING)
        - row_count: Number of rows affected
        - columns: List of column names
        - message: Status message
    """
    results = {}
    
    for i, cmd in enumerate(commands):
        logger.info(f"Executing Postgres command: {cmd}")
        is_select = cmd.strip().upper().startswith("SELECT")
        is_call = cmd.strip().upper().startswith("CALL")
        returns_data = is_select or "RETURNING" in cmd.upper()
        original_autocommit = conn.autocommit
        
        try:
            if is_call:
                # CALL statements require autocommit mode
                conn.autocommit = True
                with conn.cursor() as cursor:
                    cursor.execute(cmd)
                    has_results = cursor.description is not None

                    if has_results:
                        result_data = _fetch_result_rows(cursor)
                        column_names = [desc[0] for desc in cursor.description]
                        
                        results[f"command_{i}"] = {
                            "status": "success",
                            "rows": result_data,
                            "row_count": len(result_data),
                            "columns": column_names
                        }
                    else:
                        results[f"command_{i}"] = {
                            "status": "success",
                            "message": "Procedure executed successfully."
                        }
            else:
                # Regular statements use transaction
                with conn.transaction():
                    with conn.cursor() as cursor:
                        cursor.execute(cmd)
                        has_results = cursor.description is not None

                        if has_results:
                            result_data = _fetch_result_rows(cursor)
                            column_names = [desc[0] for desc in cursor.description]
                            
                            results[f"command_{i}"] = {
                                "status": "success",
                                "rows": result_data,
                                "row_count": len(result_data),
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

    return results


def _fetch_result_rows(cursor) -> List[Dict]:
    """
    Fetch and format result rows from cursor.
    
    Handles special data types:
    - Decimal -> float
    - JSON strings -> preserve as-is
    - Other types -> preserve as-is
    
    Args:
        cursor: PostgreSQL cursor object with executed query
        
    Returns:
        List of row dictionaries with column name keys
    """
    column_names = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    result_data = []
    
    for row in rows:
        row_dict = {}
        for j, col_name in enumerate(column_names):
            value = row[j]
            
            # Handle JSON/dict types
            if isinstance(value, dict) or (isinstance(value, str) and (
                    value.startswith('{') or value.startswith('['))):
                try:
                    row_dict[col_name] = value
                except:
                    row_dict[col_name] = value
            # Convert Decimal to float for JSON serialization
            elif isinstance(value, Decimal):
                row_dict[col_name] = float(value)
            else:
                row_dict[col_name] = value
        
        result_data.append(row_dict)
    
    return result_data
