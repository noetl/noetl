"""
Container plugin for NoETL.

This package provides Kubernetes Job-based container task execution capabilities with:
- Kubernetes Job creation and lifecycle management
- ConfigMap-based script and file injection
- Pod log streaming and execution monitoring
- Credential and secret injection via environment variables
- Script loading from file, GCS, S3, HTTP sources
- Resource limits and cleanup management

Usage:
    from noetl.plugin.tools.container import execute_container_task
    
    result = execute_container_task(
        task_config={'runtime': {...}, 'script': {...}, 'env': {...}},
        context={'execution_id': 'exec-123'},
        jinja_env=jinja_env,
        task_with={}
    )
"""

from noetl.plugin.tools.container.executor import execute_container_task

__all__ = ['execute_container_task']
