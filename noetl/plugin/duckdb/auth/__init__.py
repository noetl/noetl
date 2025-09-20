"""
Authentication and credential management for DuckDB.
"""

from .resolver import resolve_credentials, resolve_unified_auth
from .secrets import generate_duckdb_secrets  
from .legacy import build_legacy_credential_prelude