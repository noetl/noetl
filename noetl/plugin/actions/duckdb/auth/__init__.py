"""
Authentication and credential management for DuckDB.
"""

from noetl.plugin.actions.duckdb.auth.resolver import resolve_credentials, resolve_unified_auth
from noetl.plugin.actions.duckdb.auth.secrets import generate_duckdb_secrets  
from noetl.plugin.actions.duckdb.auth.legacy import build_legacy_credential_prelude