"""
Snowflake plugin for NoETL.

This package provides Snowflake database task execution capabilities with:
- Unified authentication system support
- Legacy credential fallback
- Base64 encoded SQL command execution
- Multi-statement support with proper quote handling
- Warehouse management
- Result formatting and error handling
- MCP-compliant interface
- Chunked data transfer between Snowflake and PostgreSQL

Usage:
    from noetl.plugin.actions.snowflake import execute_snowflake_task, execute_snowflake_transfer_task
    
    # Execute SQL commands
    result = execute_snowflake_task(
        task_config={'command_b64': '<base64-encoded-sql>'},
        context={'execution_id': 'exec-123'},
        jinja_env=jinja_env,
        task_with={
            'account': 'my_account',
            'warehouse': 'COMPUTE_WH',
            'database': 'MY_DB',
            'schema': 'PUBLIC',
            'user': 'my_user',
            'password': 'my_password'
        }
    )
    
    # Transfer data between Snowflake and PostgreSQL
    result = execute_snowflake_transfer_task(
        task_config={
            'transfer_direction': 'sf_to_pg',
            'source_query': 'SELECT * FROM my_table',
            'target_table': 'public.my_target',
            'chunk_size': 5000,
            'mode': 'append'
        },
        context={'execution_id': 'exec-123'},
        jinja_env=jinja_env,
        task_with={...}
    )
"""

from noetl.plugin.actions.snowflake.executor import execute_snowflake_task, execute_snowflake_transfer_task

__all__ = ['execute_snowflake_task', 'execute_snowflake_transfer_task']
