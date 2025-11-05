"""
Save action executor package for NoETL.

This package handles 'save' type tasks which persist data to various storage
backends by delegating to appropriate plugins (postgres, duckdb, python, http).

Package Structure:
    - config.py: Configuration extraction and parsing
    - rendering.py: Template rendering for data and parameters
    - postgres.py: PostgreSQL storage delegation
    - python.py: Python storage delegation
    - duckdb.py: DuckDB storage delegation
    - http.py: HTTP storage delegation
    - executor.py: Main save task orchestrator
"""

from noetl.plugin.shared.storage.executor import execute_save_task

__all__ = ['execute_save_task']
