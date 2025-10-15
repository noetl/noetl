"""
Unified authentication system for NoETL plugins.

This package provides a unified way to handle authentication across all plugin types,
replacing the previous split between auth (single), credentials (map), and secret (external).

The new system uses a single `auth:` dictionary attribute that maps aliases to typed
credential specifications, supporting various authentication types and providers.
"""

# Export constants
from .constants import AUTH_TYPES, AUTH_PROVIDERS, REDACTED_FIELDS

# Export utilities
from .utils import (
    deep_render_template as _deep_render_template,
    redact_dict as _redact_dict,
    fetch_secret_manager_value as _fetch_secret_manager_value,
)

# Export normalization functions
from .normalize import (
    normalize_postgres_fields as _normalize_postgres_fields,
    normalize_hmac_fields as _normalize_hmac_fields,
)

# Export core resolution
from .resolver import resolve_auth_map, convert_legacy_auth as _convert_legacy_auth

# Export type-specific functions
from .postgres import get_postgres_auth
from .http import build_http_headers
from .duckdb import get_duckdb_secrets, get_required_extensions

__all__ = [
    # Constants
    'AUTH_TYPES',
    'AUTH_PROVIDERS',
    'REDACTED_FIELDS',
    # Core functions
    'resolve_auth_map',
    # Type-specific functions
    'get_postgres_auth',
    'build_http_headers',
    'get_duckdb_secrets',
    'get_required_extensions',
    # Private utilities (exposed for testing)
    '_deep_render_template',
    '_redact_dict',
    '_fetch_secret_manager_value',
    '_normalize_postgres_fields',
    '_normalize_hmac_fields',
    '_convert_legacy_auth',
]
