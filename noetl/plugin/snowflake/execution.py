"""
Snowflake SQL execution module.

Handles database connections and SQL statement execution for Snowflake.
"""

from typing import Dict, List
import snowflake.connector
from snowflake.connector import DictCursor

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def connect_to_snowflake(
    account: str,
    user: str,
    password: str,
    warehouse: str = 'COMPUTE_WH',
    database: str = None,
    schema: str = 'PUBLIC',
    role: str = None,
    authenticator: str = 'snowflake'
) -> snowflake.connector.SnowflakeConnection:
    """
    Establish connection to Snowflake.
    
    Args:
        account: Snowflake account identifier (e.g., 'xy12345.us-east-1')
        user: Snowflake username
        password: Snowflake password
        warehouse: Snowflake warehouse name (default: COMPUTE_WH)
        database: Snowflake database name (optional)
        schema: Snowflake schema name (default: PUBLIC)
        role: Snowflake role (optional)
        authenticator: Authentication method (default: snowflake)
        
    Returns:
        Snowflake connection object
        
    Raises:
        snowflake.connector.Error: If connection fails
    """
    connection_params = {
        'account': account,
        'user': user,
        'password': password,
        'warehouse': warehouse,
        'authenticator': authenticator,
    }
    
    if database:
        connection_params['database'] = database
    if schema:
        connection_params['schema'] = schema
    if role:
        connection_params['role'] = role
    
    logger.info(f"Connecting to Snowflake account: {account}, warehouse: {warehouse}")
    
    try:
        conn = snowflake.connector.connect(**connection_params)
        logger.info("Successfully connected to Snowflake")
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to Snowflake: {e}")
        raise


def execute_sql_statements(
    conn: snowflake.connector.SnowflakeConnection,
    statements: List[str]
) -> Dict[str, Dict]:
    """
    Execute multiple SQL statements and collect results.
    
    Each statement is executed independently. If a statement fails,
    the error is captured and execution continues with the next statement.
    
    Args:
        conn: Active Snowflake connection
        statements: List of SQL statements to execute
        
    Returns:
        Dictionary mapping statement index to execution results:
        {
            'statement_0': {
                'status': 'success',
                'rows_affected': 10,
                'result': [...],
                'query': 'SELECT...'
            },
            'statement_1': {
                'status': 'error',
                'error': 'Error message',
                'query': 'INSERT...'
            },
            ...
        }
    """
    results = {}
    
    for idx, statement in enumerate(statements):
        statement_key = f'statement_{idx}'
        logger.debug(f"Executing statement {idx + 1}/{len(statements)}")
        
        try:
            cursor = conn.cursor(DictCursor)
            cursor.execute(statement)
            
            # Check if statement returns results (SELECT, SHOW, DESCRIBE, etc.)
            if cursor.description:
                rows = cursor.fetchall()
                results[statement_key] = {
                    'status': 'success',
                    'row_count': len(rows),
                    'result': rows,
                    'query': statement[:200] + ('...' if len(statement) > 200 else ''),
                    'columns': [desc[0] for desc in cursor.description] if cursor.description else []
                }
                logger.info(f"Statement {idx + 1} returned {len(rows)} rows")
            else:
                # DML statements (INSERT, UPDATE, DELETE, etc.)
                rows_affected = cursor.rowcount
                results[statement_key] = {
                    'status': 'success',
                    'rows_affected': rows_affected,
                    'query': statement[:200] + ('...' if len(statement) > 200 else '')
                }
                logger.info(f"Statement {idx + 1} affected {rows_affected} rows")
            
            cursor.close()
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Statement {idx + 1} failed: {error_msg}")
            results[statement_key] = {
                'status': 'error',
                'error': error_msg,
                'query': statement[:200] + ('...' if len(statement) > 200 else '')
            }
    
    return results
