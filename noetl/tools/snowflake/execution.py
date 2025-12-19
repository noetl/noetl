"""
Snowflake SQL execution module.

Handles database connections and SQL statement execution for Snowflake.
Supports both password-based and key-pair authentication.
"""

from typing import Dict, List, Optional
from decimal import Decimal
from datetime import datetime, date, time
import snowflake.connector
from snowflake.connector import DictCursor
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def connect_to_snowflake(
    account: str,
    user: str,
    password: Optional[str] = None,
    private_key: Optional[str] = None,
    private_key_passphrase: Optional[str] = None,
    warehouse: str = 'COMPUTE_WH',
    database: str = None,
    schema: str = 'PUBLIC',
    role: str = None,
    authenticator: str = 'snowflake'
) -> snowflake.connector.SnowflakeConnection:
    """
    Establish connection to Snowflake.
    
    Supports two authentication methods:
    1. Password-based: Provide password parameter
    2. Key-pair: Provide private_key (and optional private_key_passphrase)
    
    Args:
        account: Snowflake account identifier (e.g., 'xy12345.us-east-1')
        user: Snowflake username
        password: Snowflake password (for password auth)
        private_key: RSA private key in PEM format (for key-pair auth)
        private_key_passphrase: Optional passphrase for encrypted private key
        warehouse: Snowflake warehouse name (default: COMPUTE_WH)
        database: Snowflake database name (optional)
        schema: Snowflake schema name (default: PUBLIC)
        role: Snowflake role (optional)
        authenticator: Authentication method (default: snowflake)
        
    Returns:
        Snowflake connection object
        
    Raises:
        snowflake.connector.Error: If connection fails
        ValueError: If neither password nor private_key is provided
    """
    connection_params = {
        'account': account,
        'user': user,
        'warehouse': warehouse,
    }
    
    # Determine authentication method
    if private_key:
        logger.info(f"Using key-pair authentication for Snowflake account: {account}")
        
        # Parse private key
        try:
            # Handle passphrase if provided
            passphrase_bytes = private_key_passphrase.encode() if private_key_passphrase else None
            
            # Load the private key
            private_key_bytes = private_key.encode()
            p_key = serialization.load_pem_private_key(
                private_key_bytes,
                password=passphrase_bytes,
                backend=default_backend()
            )
            
            # Convert to DER format for Snowflake connector
            pkb = p_key.private_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            )
            
            connection_params['private_key'] = pkb
            logger.debug("Private key successfully parsed and converted to DER format")
            
        except Exception as e:
            logger.error(f"Failed to parse private key: {e}")
            raise ValueError(f"Invalid private key format: {e}")
    
    elif password:
        logger.info(f"Using password authentication for Snowflake account: {account}")
        connection_params['password'] = password
        connection_params['authenticator'] = authenticator
    
    else:
        raise ValueError("Either 'password' or 'private_key' must be provided for Snowflake authentication")
    
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
                # Normalize values for JSON serialization (Decimal, datetime, etc.)
                serialized_rows = [_serialize_row(row) for row in rows]
                results[statement_key] = {
                    'status': 'success',
                    'row_count': len(rows),
                    'result': serialized_rows,
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


def _serialize_value(value):
    """Convert Snowflake values to JSON-serializable types."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return value


def _serialize_row(row: dict) -> dict:
    """Serialize a DictCursor row to JSON-friendly types."""
    return {k: _serialize_value(v) for k, v in row.items()}
