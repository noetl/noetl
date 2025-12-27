"""
Snowflake data transfer module with chunked streaming support.

This module provides efficient data transfer capabilities between Snowflake and PostgreSQL:
- Chunk-by-chunk streaming from Snowflake to PostgreSQL
- Chunk-by-chunk streaming from PostgreSQL to Snowflake
- Configurable batch sizes for memory-efficient operations
- Progress tracking and error handling
"""

import psycopg
import snowflake.connector
from typing import Dict, List, Optional, Callable
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def transfer_snowflake_to_postgres(
    sf_conn: snowflake.connector.SnowflakeConnection,
    pg_conn: psycopg.Connection,
    source_query: str,
    target_table: str = None,
    target_query: str = None,
    chunk_size: int = 1000,
    mode: str = 'append',
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> Dict[str, any]:
    """
    Transfer data from Snowflake to PostgreSQL in chunks.
    
    Args:
        sf_conn: Active Snowflake connection
        pg_conn: Active PostgreSQL connection
        source_query: SQL query to fetch data from Snowflake
        target_table: Target PostgreSQL table name (optional if target_query provided)
        target_query: Custom INSERT/UPSERT query with placeholders (optional, overrides target_table)
                     Example: "INSERT INTO table (col1, col2) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET col2 = EXCLUDED.col2"
        chunk_size: Number of rows per chunk (default: 1000)
        mode: Transfer mode - 'append', 'replace', or 'upsert' (default: 'append', ignored if target_query provided)
        progress_callback: Optional callback function(rows_processed, total_rows)
        
    Returns:
        Dictionary with transfer statistics:
        {
            'status': 'success' or 'error',
            'rows_transferred': int,
            'chunks_processed': int,
            'target_table': str,
            'columns': list,
            'error': str (if error occurred)
        }
    """
    target_name = target_table or 'custom_query'
    logger.info(f"Starting Snowflake -> PostgreSQL transfer to {target_name} | chunk_size={chunk_size} | mode={mode}")
    
    # Validate: must have either target_table or target_query
    if not target_table and not target_query:
        raise ValueError("Either target_table or target_query must be provided")
    
    rows_transferred = 0
    chunks_processed = 0
    
    try:
        # Execute source query
        sf_cursor = sf_conn.cursor()
        sf_cursor.execute(source_query)
        
        # Get column names (lowercase for PostgreSQL compatibility)
        columns = [desc[0].lower() for desc in sf_cursor.description]
        
        logger.info(f"Source columns: {columns}")
        
        # Prepare insert statement
        if target_query:
            # Use custom query provided by user
            insert_sql = target_query
            logger.info(f"Using custom target query: {insert_sql}")
            
            # Validate placeholder count matches column count
            placeholder_count = insert_sql.count('%s')
            if placeholder_count != len(columns):
                logger.warning(f"Placeholder count ({placeholder_count}) doesn't match column count ({len(columns)}). "
                             f"Ensure your target_query has the correct number of %s placeholders.")
        else:
            # Auto-generate insert statement from target_table
            column_list = ', '.join([f'"{col}"' for col in columns])
            placeholders = ', '.join(['%s'] * len(columns))
            
            # Handle transfer mode
            if mode == 'replace':
                logger.info(f"Truncating target table: {target_table}")
                with pg_conn.cursor() as pg_cursor:
                    pg_cursor.execute(f'TRUNCATE TABLE {target_table}')
                pg_conn.commit()
            
            # Build insert statement based on mode
            if mode == 'upsert':
                # For upsert, assume first column is primary key
                pk_column = columns[0]
                update_cols = ', '.join([f'"{col}" = EXCLUDED."{col}"' for col in columns[1:]])
                insert_sql = f"""
                    INSERT INTO {target_table} ({column_list})
                    VALUES ({placeholders})
                    ON CONFLICT ("{pk_column}") DO UPDATE SET {update_cols}
                """
            else:
                insert_sql = f"""
                    INSERT INTO {target_table} ({column_list})
                    VALUES ({placeholders})
                """
            
            logger.debug(f"Auto-generated SQL: {insert_sql}")
        
        # Process data in chunks
        while True:
            chunk = sf_cursor.fetchmany(chunk_size)
            if not chunk:
                break
            
            # Insert chunk into PostgreSQL
            with pg_conn.cursor() as pg_cursor:
                for row in chunk:
                    # Convert Snowflake types to PostgreSQL-compatible types
                    converted_row = [_convert_value(val) for val in row]
                    pg_cursor.execute(insert_sql, converted_row)
            
            pg_conn.commit()
            
            rows_transferred += len(chunk)
            chunks_processed += 1
            
            logger.debug(f"Processed chunk {chunks_processed}: {len(chunk)} rows")
            
            if progress_callback:
                progress_callback(rows_transferred, -1)  # -1 means unknown total
        
        sf_cursor.close()
        
        logger.info(f"Transfer complete: {rows_transferred} rows in {chunks_processed} chunks")
        
        return {
            'status': 'success',
            'rows_transferred': rows_transferred,
            'chunks_processed': chunks_processed,
            'target_table': target_name,
            'columns': columns
        }
        
    except Exception as e:
        logger.error(f"Transfer failed: {e}", exc_info=True)
        return {
            'status': 'error',
            'rows_transferred': rows_transferred,
            'chunks_processed': chunks_processed,
            'target_table': target_name,
            'error': str(e)
        }


def transfer_postgres_to_snowflake(
    pg_conn: psycopg.Connection,
    sf_conn: snowflake.connector.SnowflakeConnection,
    source_query: str,
    target_table: str = None,
    target_query: str = None,
    chunk_size: int = 1000,
    mode: str = 'append',
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> Dict[str, any]:
    """
    Transfer data from PostgreSQL to Snowflake in chunks.
    
    Args:
        pg_conn: Active PostgreSQL connection
        sf_conn: Active Snowflake connection
        source_query: SQL query to fetch data from PostgreSQL
        target_table: Target Snowflake table name (optional if target_query provided)
        target_query: Custom INSERT/MERGE query with placeholders (optional, overrides target_table)
                     Example: "INSERT INTO table (col1, col2) VALUES (%s, %s)"
                     Or: "MERGE INTO table t USING (SELECT %s as id, %s as name) s ON t.id=s.id WHEN MATCHED THEN UPDATE SET name=s.name WHEN NOT MATCHED THEN INSERT (id,name) VALUES (s.id,s.name)"
        chunk_size: Number of rows per chunk (default: 1000)
        mode: Transfer mode - 'append', 'replace', or 'merge' (default: 'append', ignored if target_query provided)
        progress_callback: Optional callback function(rows_processed, total_rows)
        
    Returns:
        Dictionary with transfer statistics:
        {
            'status': 'success' or 'error',
            'rows_transferred': int,
            'chunks_processed': int,
            'target_table': str,
            'columns': list,
            'error': str (if error occurred)
        }
    """
    target_name = target_table or 'custom_query'
    logger.info(f"Starting PostgreSQL -> Snowflake transfer to {target_name} (chunk_size={chunk_size}, mode={mode})")
    
    # Validate: must have either target_table or target_query
    if not target_table and not target_query:
        raise ValueError("Either target_table or target_query must be provided")
    
    rows_transferred = 0
    chunks_processed = 0
    
    try:
        # Execute source query
        with pg_conn.cursor() as pg_cursor:
            pg_cursor.execute(source_query)
            
            # Get column names
            columns = [desc[0] for desc in pg_cursor.description]
            
            logger.info(f"Source columns: {columns}")
            
            # Prepare insert statement
            if target_query:
                # Use custom query provided by user
                insert_sql = target_query
                logger.info(f"Using custom target query: {insert_sql}")
                
                # Validate placeholder count matches column count
                placeholder_count = insert_sql.count('%s')
                if placeholder_count != len(columns):
                    logger.warning(f"Placeholder count ({placeholder_count}) doesn't match column count ({len(columns)}). "
                                 f"Ensure your target_query has the correct number of %s placeholders.")
            else:
                # Auto-generate insert statement from target_table
                column_list = ', '.join(columns)
                placeholders = ', '.join(['%s'] * len(columns))
                
                # Handle transfer mode
                if mode == 'replace':
                    logger.info(f"Truncating target table: {target_table}")
                    sf_cursor = sf_conn.cursor()
                    sf_cursor.execute(f'TRUNCATE TABLE {target_table}')
                    sf_cursor.close()
                
                # Build insert statement
                insert_sql = f"""
                    INSERT INTO {target_table} ({column_list})
                    VALUES ({placeholders})
                """
                
                logger.debug(f"Auto-generated SQL: {insert_sql}")
            
            # Process data in chunks
            while True:
                chunk = pg_cursor.fetchmany(chunk_size)
                if not chunk:
                    break
                
                # Insert chunk into Snowflake
                sf_cursor = sf_conn.cursor()
                for row in chunk:
                    # Convert PostgreSQL types to Snowflake-compatible types
                    converted_row = [_convert_value(val) for val in row]
                    sf_cursor.execute(insert_sql, converted_row)
                sf_cursor.close()
                
                rows_transferred += len(chunk)
                chunks_processed += 1
                
                logger.debug(f"Processed chunk {chunks_processed}: {len(chunk)} rows")
                
                if progress_callback:
                    progress_callback(rows_transferred, -1)
        
        logger.info(f"Transfer complete: {rows_transferred} rows in {chunks_processed} chunks")
        
        return {
            'status': 'success',
            'rows_transferred': rows_transferred,
            'chunks_processed': chunks_processed,
            'target_table': target_name,
            'columns': columns
        }
        
    except Exception as e:
        logger.error(f"Transfer failed: {e}", exc_info=True)
        return {
            'status': 'error',
            'rows_transferred': rows_transferred,
            'chunks_processed': chunks_processed,
            'target_table': target_name,
            'error': str(e)
        }


def _convert_value(value):
    """
    Convert database values to compatible formats.
    
    Handles special types like dates, decimals, etc.
    """
    if value is None:
        return None
    
    # Handle date/datetime objects
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    
    # Handle decimal
    if hasattr(value, '__class__') and value.__class__.__name__ == 'Decimal':
        return float(value)
    
    return value
