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

Usage:
    from noetl.plugin.snowflake import execute_snowflake_task
    
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
"""

from .executor import execute_snowflake_task

__all__ = ['execute_snowflake_task']
