"""
Authentication and credential management for DuckDB.
"""

from noetl.plugin.tools.duckdb.auth.resolver import resolve_credentials, resolve_unified_auth
from noetl.plugin.tools.duckdb.auth.secrets import generate_duckdb_secrets  
from noetl.plugin.tools.duckdb.auth.legacy import build_legacy_credential_prelude