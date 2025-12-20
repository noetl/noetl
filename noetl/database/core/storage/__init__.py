"""
Sink action executor package for NoETL.

This package handles 'sink' type tasks which persist data to various tool
backends by delegating to appropriate plugins (postgres, duckdb, python, http).

Package Structure:
    - config.py: Configuration extraction and parsing
    - rendering.py: Template rendering for data and parameters
    - postgres.py: PostgreSQL tool delegation
    - python.py: Python tool delegation
    - duckdb.py: DuckDB tool delegation
    - http.py: HTTP tool delegation
    - executor.py: Main sink task orchestrator
"""

from noetl.core.storage.executor import execute_sink_task

__all__ = ['execute_sink_task']
