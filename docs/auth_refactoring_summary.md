# Authentication Module Refactoring Summary

## Overview
Refactored `noetl/plugin/_auth.py` (587 lines) into a modular package structure at `noetl/plugin/auth/` with logical separation of concerns.

**Latest Enhancement**: Added Secret Manager provider support for secure credential retrieval from external secret management systems (Google Secret Manager, AWS Secrets Manager, etc.). See [Secret Manager Auth Provider](./secret_manager_auth_provider.md) for detailed documentation.

## New Package Structure

```
noetl/plugin/auth/
├── __init__.py          # Public API exports
├── constants.py         # AUTH_TYPES, AUTH_PROVIDERS, REDACTED_FIELDS
├── utils.py             # Helper utilities (template rendering, redaction, secret fetching)
├── normalize.py         # Field normalization functions (postgres, HMAC)
├── resolver.py          # Core auth resolution logic
├── postgres.py          # PostgreSQL-specific functions
├── http.py              # HTTP authentication functions
└── duckdb.py            # DuckDB-specific functions
```

## Module Breakdown

### 1. **constants.py** (27 lines)
- `AUTH_TYPES`: Supported authentication types (postgres, hmac, s3, bearer, basic, header, api_key, oauth2_client_credentials)
- `AUTH_PROVIDERS`: Supported providers (credential_store, secret_manager, inline)
- `REDACTED_FIELDS`: Fields to redact in logs

### 2. **utils.py** (120+ lines)
- `deep_render_template()`: Recursively render Jinja templates in nested objects
- `redact_dict()`: Create redacted copy of dictionary for safe logging
- `fetch_secret_manager_value()`: Fetch secrets from external secret management systems with OAuth and caching
- `_fetch_google_secret()`: Google Secret Manager API integration with base64 decoding

### 3. **normalize.py** (73 lines)
- `normalize_postgres_fields()`: Normalize postgres credential fields to standard names
- `normalize_hmac_fields()`: Normalize HMAC credential fields for GCS/S3

### 4. **resolver.py** (250+ lines)
- `convert_legacy_auth()`: Convert legacy auth/credentials/secret formats to unified format
- `resolve_auth_map()`: Main resolution function that merges, renders, and resolves auth configurations
- **Secret Manager Provider**: Detects `provider: secret_manager` and fetches credentials from external stores
- **OAuth2 Client Credentials**: Supports multi-value secrets (client_id + client_secret)
- **Credential Caching**: Integrates with CredentialCache for 1-hour TTL execution-scoped caching

### 5. **postgres.py** (37 lines)
- `get_postgres_auth()`: Extract postgres authentication from resolved auth map

### 6. **http.py** (56 lines)
- `build_http_headers()`: Build HTTP headers from resolved auth map (bearer, basic, api_key, header)

### 7. **duckdb.py** (155 lines)
- `get_duckdb_secrets()`: Generate DuckDB CREATE SECRET statements
- `get_required_extensions()`: Get list of DuckDB extensions required for auth types

### 8. **__init__.py** (52 lines)
- Exports public API
- Marks internal functions with `_` prefix
- Maintains backward compatibility

## Public API

```python
from noetl.plugin.auth import (
    # Constants
    AUTH_TYPES,
    AUTH_PROVIDERS,
    REDACTED_FIELDS,
    
    # Core functions
    resolve_auth_map,
    
    # Type-specific functions
    get_postgres_auth,
    build_http_headers,
    get_duckdb_secrets,
    get_required_extensions,
    
    # Private utilities (for testing)
    _deep_render_template,
    _redact_dict,
    _fetch_secret_manager_value,
    _normalize_postgres_fields,
    _normalize_hmac_fields,
    _convert_legacy_auth,
)
```

## Migration Path

### Before
```python
from noetl.plugin._auth import resolve_auth_map, get_postgres_auth
```

### After
```python
from noetl.plugin.auth import resolve_auth_map, get_postgres_auth
```

## Changes Made

1. **Split monolithic file**: Separated 587-line `_auth.py` into 7 focused modules
2. **Logical organization**: Grouped related functions by concern (constants, utils, normalization, resolution, type-specific)
3. **Updated imports**: Changed all references from `noetl.plugin._auth` to `noetl.plugin.auth`
4. **Updated tests**: Fixed all mock patch paths in `tests/test_unified_auth.py`
5. **Backward compatibility**: Maintained the same public API surface
6. **Removed old file**: Deleted `noetl/plugin/_auth.py` after successful migration
7. **Secret Manager Provider**: Added external secret management system integration with OAuth and caching
8. **OAuth2 Client Credentials**: Added support for multi-value secrets (client_id + client_secret)
9. **Template Context Injection**: Resolved credentials automatically available in Jinja2 templates

## Latest Features (v1.5.0)

### Secret Manager Provider
- Fetch credentials from external secret stores (Google Secret Manager, AWS Secrets Manager)
- OAuth-based authentication with automatic token resolution
- Execution-scoped credential caching (1-hour TTL)
- Support for single-value (API keys) and multi-value (OAuth credentials) secrets
- Template integration: `{{ auth.alias.field }}` access

### OAuth2 Client Credentials
- New auth type: `oauth2_client_credentials`
- Separate key fields: `client_id_key` and `client_secret_key`
- Automatic fetching of both values from Secret Manager
- Integration with HTTP OAuth token requests

### Example Usage
```yaml
auth:
  amadeus:
    type: oauth2_client_credentials
    provider: secret_manager
    client_id_key: projects/123/secrets/client-id/versions/1
    client_secret_key: projects/123/secrets/client-secret/versions/1
    oauth_credential: google_oauth

data:
  grant_type: client_credentials
  client_id: '{{ auth.amadeus.client_id }}'
  client_secret: '{{ auth.amadeus.client_secret }}'
```

See [Secret Manager Auth Provider](./secret_manager_auth_provider.md) for complete documentation.

## Test Results

✅ **29/29 tests passing** in `tests/test_unified_auth.py`
- Auth helpers tests
- Legacy conversion tests
- Auth resolution tests
- PostgreSQL auth tests
- HTTP auth tests
- DuckDB auth tests
- Environment integration tests

## Verification

✅ Server loads successfully with refactored auth package
✅ All 85 routes properly registered
✅ No breaking changes to public API
✅ All imports updated correctly
✅ Test mocks updated to new module paths

## Benefits

1. **Maintainability**: Easier to locate and modify specific functionality
2. **Testability**: Smaller, focused modules are easier to test
3. **Readability**: Clear separation of concerns makes code easier to understand
4. **Scalability**: New auth types can be added as separate modules
5. **Reusability**: Individual functions can be imported without loading entire module
6. **Documentation**: Each module has a clear, focused purpose

## Files Modified

- **Created**: 8 new files in `noetl/plugin/auth/` package
- **Updated**: `tests/test_unified_auth.py` (import paths and mock patches)
- **Removed**: `noetl/plugin/_auth.py`

## No Breaking Changes

The refactoring maintains 100% backward compatibility:
- Same function signatures
- Same return types
- Same behavior
- Only import paths changed from `_auth` to `auth`
