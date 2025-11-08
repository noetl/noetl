"""
SQL processing utilities for DuckDB tasks.
"""

from noetl.plugin.tools.duckdb.sql.rendering import render_commands, clean_sql_text, render_deep, escape_sql
from noetl.plugin.tools.duckdb.sql.execution import execute_sql_commands, serialize_results, create_task_result