"""
Snowflake Transfer plugin for NoETL.

This package provides data transfer capabilities between Snowflake and PostgreSQL:
- Bidirectional transfer (Snowflake ↔ PostgreSQL)
- Chunked streaming for memory efficiency
- Multiple transfer modes (append, replace, upsert)
- Progress tracking and error handling

Usage:
    # In playbook YAML:
    - step: transfer_data
      type: snowflake_transfer
      direction: sf_to_pg  # or pg_to_sf
      source:
        query: "SELECT * FROM my_table ORDER BY id"
      target:
        table: "public.target_table"
      chunk_size: 1000
      mode: append
      credentials:
        sf: { key: "sf_credential_name" }
        pg: { key: "pg_credential_name" }
"""

from noetl.tools.transfer.snowflake_transfer.executor import execute_snowflake_transfer_action

__all__ = ['execute_snowflake_transfer_action']
