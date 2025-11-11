"""
PostgreSQL SQL execution with async connection pooling and transaction handling.

This module provides the core execution logic for PostgreSQL operations with:
- Connection pooling per credential (managed by noetl.core.db.pool)
- Async/await execution model
- Transaction management
- CALL statement special handling (autocommit mode)
- Result data extraction and formatting
- Automatic connection retry via pool
"""

from typing import Dict, List, Optional
from decimal import Decimal
from datetime import datetime, date, time
from psycopg import AsyncConnection
from noetl.core.logger import setup_logger
from .pool import get_connection
logger = setup_logger(__name__, include_location=True)


async def execute_sql_with_pool(
    connection_string: str,
    commands: List[str],
    host: str = "unknown",
    port: str = "unknown",
    database: str = "unknown"
) -> Dict[str, Dict]:
    """
    Execute SQL statements using connection pool.
    
    This is the main async entry point for executing PostgreSQL commands.
    Uses connection pooling to avoid connection overhead and improve reliability.
    
    Args:
        connection_string: PostgreSQL connection string
        commands: List of SQL statement strings to execute
        host: Database host (for logging)
        port: Database port (for logging)
        database: Database name (for logging)
        
    Returns:
        Dictionary mapping command indices to result dictionaries
        
    Raises:
        Exception: If connection or execution fails
    """
    logger.debug(f"Executing {len(commands)} SQL commands on {host}:{port}/{database}")
    
    try:
        async with get_connection(connection_string, pool_name=f"pg_{database}") as conn:
            return await execute_sql_statements_async(conn, commands)
    except Exception as e:
        logger.exception(f"Failed to execute SQL with pool: {e}")
        raise


async def execute_sql_statements_async(
    conn: AsyncConnection,
    commands: List[str]
) -> Dict[str, Dict]:
    """
    Execute multiple SQL statements asynchronously and collect results.
    
    This function handles:
    - SELECT statements and statements with RETURNING clause
    - CALL statements (using autocommit mode)
    - DML statements (INSERT, UPDATE, DELETE)
    - DDL statements (CREATE, ALTER, DROP)
    
    Args:
        conn: Async PostgreSQL connection object
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
        logger.info(f"Executing Postgres command: {cmd[:100]}{'...' if len(cmd) > 100 else ''}")
        is_select = cmd.strip().upper().startswith("SELECT")
        is_call = cmd.strip().upper().startswith("CALL")
        returns_data = is_select or "RETURNING" in cmd.upper()
        original_autocommit = conn.autocommit
        
        try:
            if is_call:
                # CALL statements require autocommit mode
                await conn.set_autocommit(True)
                async with conn.cursor() as cursor:
                    await cursor.execute(cmd)
                    has_results = cursor.description is not None

                    if has_results:
                        result_data = await _fetch_result_rows_async(cursor)
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
                async with conn.transaction():
                    async with conn.cursor() as cursor:
                        await cursor.execute(cmd)
                        has_results = cursor.description is not None

                        if has_results:
                            result_data = await _fetch_result_rows_async(cursor)
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
            logger.error(f"Exception type: {type(cmd_error).__name__}, repr: {repr(cmd_error)}")
            results[f"command_{i}"] = {
                "status": "error",
                "message": str(cmd_error)
            }
        finally:
            await conn.set_autocommit(original_autocommit)

    return results


async def _fetch_result_rows_async(cursor) -> List[Dict]:
    """
    Fetch and format result rows from async cursor.
    
    Handles special data types:
    - Decimal -> float
    - datetime/date/time -> ISO format string
    - JSON strings -> preserve as-is
    - Other types -> preserve as-is
    
    Args:
        cursor: Async PostgreSQL cursor object with executed query
        
    Returns:
        List of row dictionaries with column name keys
    """

    
    rows = await cursor.fetchall()
    logger.debug(f"Fetched {len(rows)} rows")
    result_data = []
    
    # Rows are already dicts due to row_factory=dict_row in pool config
    for row in rows:
        logger.debug(f"Processing row type: {type(row)}, row: {row}")
        row_dict = {}
        for col_name, value in row.items():
            # Handle JSON/dict types
            if isinstance(value, dict) or (isinstance(value, str) and (
                    value.startswith('{') or value.startswith('['))):
                row_dict[col_name] = value
            # Convert Decimal to float for JSON serialization
            elif isinstance(value, Decimal):
                row_dict[col_name] = float(value)
            # Convert datetime objects to ISO format strings for JSON serialization
            elif isinstance(value, (datetime, date, time)):
                row_dict[col_name] = value.isoformat()
            else:
                row_dict[col_name] = value
        
        result_data.append(row_dict)
    
    return result_data
