"""
Transfer Plugin - Universal data transfer between different systems.

Supports transferring data between:
- Snowflake <-> PostgreSQL
- Future: BigQuery, Redshift, MySQL, etc.

The transfer plugin uses a generic source/target pattern where:
- Source defines the data source (type, auth, query)
- Target defines the data destination (type, auth, table or query)
- Direction is inferred from source/target types
- No need for explicit auth mappings - each side has its own auth
"""

from noetl.plugin.tools.transfer.executor import execute_transfer_action

__all__ = ["execute_transfer_action"]
