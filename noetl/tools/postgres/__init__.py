"""
PostgreSQL plugin for NoETL.

This package provides PostgreSQL database task execution capabilities with:
- Unified authentication system support
- Legacy credential fallback
- Base64 encoded SQL command execution
- Multi-statement support with proper quote handling
- Transaction management
- Result formatting and error handling

Usage:
    from noetl.tools.tools.postgres import execute_postgres_task
    
    result = execute_postgres_task(
        task_config={'command_b64': '<base64-encoded-sql>'},
        context={'execution_id': 'exec-123'},
        jinja_env=jinja_env,
        task_with={
            'db_host': 'localhost',
            'db_port': '5432',
            'db_user': 'user',
            'db_password': 'password',
            'db_name': 'database'
        }
    )
"""

from noetl.tools.postgres.executor import execute_postgres_task

__all__ = ['execute_postgres_task']
