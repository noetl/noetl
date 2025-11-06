"""
Secret manager plugin for NoETL.

This package provides a thin adapter for secret manager task execution.
The actual secret retrieval is delegated to external secret management
systems (Google Cloud Secret Manager, AWS Secrets Manager, etc.) through
a secret_manager instance provided at runtime.

Usage:
    from noetl.plugin.secret import execute_secrets_task
    
    result = execute_secrets_task(
        task_config={
            'provider': 'google',
            'project_id': 'my-project',
            'secret_name': 'api-key'
        },
        context={'execution_id': 'exec-123'},
        secret_manager=secret_manager_instance,
        task_with={}
    )

Note:
    This plugin acts as an adapter between NoETL's task execution framework
    and external secret management systems. The secret_manager parameter is
    provided by the worker at runtime and implements the actual secret
    retrieval logic.
"""

from noetl.plugin.shared.secrets.executor import execute_secrets_task

__all__ = ['execute_secrets_task']
