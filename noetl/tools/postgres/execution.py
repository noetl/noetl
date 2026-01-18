"""
PostgreSQL SQL execution with direct connections and transaction handling.

This module provides the core execution logic for PostgreSQL operations with:
- Direct connection per execution (no pooling on worker side)
- Async execution model using psycopg AsyncConnection
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


async def execute_sql_with_connection(
    connection_string: str,
    commands: List[str],
    host: str = "unknown",
    port: str = "unknown",
    database: str = "unknown",
    pool: bool = False,
    pool_name: str = None,
    pool_params: dict = None
) -> Dict[str, Dict]:
    """
    Execute SQL statements using connection pool OR direct connection.
    
    Args:
        connection_string: PostgreSQL connection string
        commands: List of SQL statement strings to execute
        host: Database host (for logging)
        port: Database port (for logging)
        database: Database name (for logging)
        pool: If true, use connection pooling; if false, use direct connection (default: false - direct connection)
        pool_name: Name for the pool (for sharing or scoping). If None, derived from database name
        pool_params: Dict of pool configuration parameters (timeout, min_size, max_size, max_waiting, max_lifetime, max_idle)
        
    Returns:
        Dictionary mapping command indices to result dictionaries
        
    Raises:
        Exception: If connection or execution fails
    """
    from .pool import get_plugin_connection
    from psycopg import AsyncConnection
    import time
    
    conn_id = f"{host}:{port}/{database}-{int(time.time() * 1000)}"
    pool_params = pool_params or {}
    
    if pool:
        # Use connection pool (explicitly requested)
        pool_timeout = pool_params.get('timeout')
        effective_pool_name = pool_name or f"pg_{database}"
        logger.debug(f"[CONN-{conn_id}] Getting pooled connection '{effective_pool_name}' (timeout={pool_timeout}s) to {host}:{port}/{database}, executing {len(commands)} SQL commands")
        
        try:
            async with get_plugin_connection(connection_string, pool_name=effective_pool_name, **pool_params) as conn:
                conn_pid = conn.info.backend_pid if conn and conn.info else 'unknown'
                logger.debug(f"[CONN-{conn_id}] Using pooled connection PID: {conn_pid}")
                
                results = await execute_sql_statements_async(conn, commands)
                logger.debug(f"[CONN-{conn_id}] SQL execution completed, returning connection to pool")
                return results
        except Exception as e:
            logger.exception(f"[CONN-{conn_id}] Failed to execute SQL on {database}: {e}")
            raise
    else:
        # Use direct connection (for very long-running queries)
        logger.info(f"[CONN-{conn_id}] Opening direct connection (no pool) to {host}:{port}/{database}, executing {len(commands)} SQL commands")
        
        try:
            from psycopg.rows import dict_row
            conn = await AsyncConnection.connect(connection_string, row_factory=dict_row)
            conn_pid = conn.info.backend_pid if conn and conn.info else 'unknown'
            logger.debug(f"[CONN-{conn_id}] Using direct connection PID: {conn_pid}")
            
            try:
                results = await execute_sql_statements_async(conn, commands)
                logger.info(f"[CONN-{conn_id}] SQL execution completed, closing direct connection")
                return results
            finally:
                await conn.close()
                logger.debug(f"[CONN-{conn_id}] Direct connection closed")
        except Exception as e:
            logger.exception(f"[CONN-{conn_id}] Failed to execute SQL on {database}: {e}")
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
    conn_pid = conn.info.backend_pid if conn and conn.info else 'unknown'
    logger.debug(f"[PID-{conn_pid}] Executing {len(commands)} statements on connection")
    results = {}
    
    for i, cmd in enumerate(commands):
        logger.info(f"[PID-{conn_pid}] Executing Postgres command {i+1}/{len(commands)}: {cmd[:100]}{'...' if len(cmd) > 100 else ''}")
        normalized = cmd.strip().upper()
        is_select = normalized.startswith("SELECT")
        is_call = normalized.startswith("CALL")
        is_autocommit_ddl = (
            normalized.startswith("CREATE DATABASE")
            or normalized.startswith("DROP DATABASE")
            or normalized.startswith("ALTER DATABASE")
        )
        returns_data = is_select or "RETURNING" in cmd.upper()
        original_autocommit = conn.autocommit
        
        try:
            if is_call or is_autocommit_ddl:
                # CALL and database-level DDL require autocommit mode
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
    
    # Rows are already dicts due to row_factory=dict_row in connection config
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
