"""
PostgreSQL SQL execution with direct connections and transaction handling.

This module provides the core execution logic for PostgreSQL operations with:
- Direct connection per execution (no pooling on worker side)
- Async/await execution model
- Transaction management with automatic rollback on error
- CALL statement special handling (autocommit mode)
- Result data extraction and formatting
- Proper connection cleanup
"""

from typing import Dict, List, Optional
from decimal import Decimal
from datetime import datetime, date, time
from psycopg import AsyncConnection
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


async def execute_sql_with_pool(
    connection_string: str,
    commands: List[str],
    host: str = "unknown",
    port: str = "unknown",
    database: str = "unknown"
) -> Dict[str, Dict]:
    """
    Execute SQL statements using a direct connection (no pooling).
    
    Opens a fresh connection for each execution, executes commands,
    and properly closes the connection afterward. This ensures clean
    state and proper error handling without pool corruption issues.
    
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
    from psycopg import AsyncConnection
    from psycopg.rows import dict_row
    
    logger.debug(f"Executing {len(commands)} SQL commands on {host}:{port}/{database}")
    
    conn = None
    try:
        # Open a fresh connection for this execution
        conn = await AsyncConnection.connect(
            connection_string,
            autocommit=False,
            row_factory=dict_row
        )
        
        # Execute commands
        results = await execute_sql_statements_async(conn, commands)
        
        return results
        
    except Exception as e:
        logger.exception(f"Failed to execute SQL: {e}")
        # Attempt rollback on error
        if conn is not None:
            try:
                await conn.rollback()
                logger.debug("Rolled back transaction after error")
            except Exception as rollback_error:
                logger.error(f"Failed to rollback transaction: {rollback_error}")
        raise
        
    finally:
        # Always close the connection
        if conn is not None:
            try:
                await conn.close()
                logger.debug(f"Closed connection to {host}:{port}/{database}")
            except Exception as close_error:
                logger.error(f"Failed to close connection: {close_error}")


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
            logger.error(f"Error executing Postgres command {i}: {cmd_error}")
            results[f"command_{i}"] = {
                "status": "error",
                "message": str(cmd_error)
            }
            # Continue to next command - don't break
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
