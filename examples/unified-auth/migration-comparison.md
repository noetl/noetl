# Migration Comparison: Old vs New Auth Syntax

This file demonstrates the differences between the deprecated authentication syntax and the new unified auth system.

## Postgres Plugin Migration

### Before (Deprecated - Still Works with Warnings)
```yaml
- step: old_postgres_step
  type: postgres
  credential: pg_production        # ❌ Deprecated field
  command_b64: "..."
```

### After (Unified Auth - Recommended)
```yaml
- step: new_postgres_step
  type: postgres
  auth:                           # ✅ New unified syntax
    type: postgres
    credential: pg_production
  command_b64: "..."
```

## HTTP Plugin Migration

### Before (Deprecated)
```yaml
- step: old_http_step
  type: http
  method: GET
  endpoint: https://api.example.com/data
  headers:
    Authorization: "Bearer {{ secrets.token }}"  # ❌ Manual header management
```

### After (Unified Auth)
```yaml
- step: new_http_step
  type: http
  method: GET
  endpoint: https://api.example.com/data
  auth:                                         # ✅ Automatic header injection
    type: bearer
    env: API_TOKEN
```

## DuckDB Plugin Migration

### Before (Deprecated)
```yaml
- step: old_duckdb_step
  type: duckdb
  credentials:                    # ❌ Deprecated field
    db:
      key: postgres_main
      service: postgres
    storage:
      key: gcs_hmac
      service: gcs
  command_b64: "..."
```

### After (Unified Auth)
```yaml
- step: new_duckdb_step
  type: duckdb
  auth:                          # ✅ New unified syntax
    db:
      type: postgres
      credential: postgres_main
    storage:
      type: gcs
      credential: gcs_hmac
  command_b64: "..."
```

## Complex Migration Example

Here's a complete playbook showing before and after patterns:

### BEFORE (Deprecated Syntax)
```yaml
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: deprecated_auth_example
  path: examples/deprecated-auth

workflow:
  - step: fetch_data
    type: http
    method: GET
    endpoint: https://api.weather.com/data
    headers:
      Authorization: "Bearer {{ secrets.weather_token }}"    # Manual
      X-Client-ID: "noetl-client"
    next:
      - step: store_in_duckdb

  - step: store_in_duckdb
    type: duckdb
    credentials:                                            # Deprecated
      db:
        key: analytics_db
        service: postgres
      storage:
        key: data_lake
        service: gcs
    command_b64: "..."
    next:
      - step: save_results

  - step: save_results
    type: postgres
    credential: results_db                                  # Deprecated
    command_b64: "..."
```

### AFTER (Unified Auth Syntax)
```yaml
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: unified_auth_example
  path: examples/unified-auth

workflow:
  - step: fetch_data
    type: http
    method: GET
    endpoint: https://api.weather.com/data
    headers:
      X-Client-ID: "noetl-client"
    auth:                                                  # ✅ Unified auth
      type: bearer
      env: WEATHER_API_TOKEN
    next:
      - step: store_in_duckdb

  - step: store_in_duckdb
    type: duckdb
    auth:                                                  # ✅ Unified auth
      db:
        type: postgres
        credential: analytics_db
      storage:
        type: gcs
        credential: data_lake
    command_b64: "..."
    next:
      - step: save_results

  - step: save_results
    type: postgres
    auth:                                                  # ✅ Unified auth
      type: postgres
      credential: results_db
    command_b64: "..."
```

## Key Differences Summary

| Aspect | Old Syntax | New Syntax |
|--------|------------|------------|
| Postgres | `credential: key` | `auth: {type: postgres, credential: key}` |
| HTTP Auth | Manual headers | `auth: {type: bearer/basic/api_key, ...}` |
| DuckDB | `credentials: {alias: {key, service}}` | `auth: {alias: {type, credential}}` |
| Validation | Minimal | Plugin-specific arity checking |
| Sources | Credential store only | credential/env/secret/inline |
| Security | Manual redaction | Automatic secret redaction |
| Templates | Limited support | Full Jinja2 integration |

## Migration Checklist

When migrating from old to new syntax:

- [ ] Replace `credential:` with `auth: {type: ..., credential: ...}`
- [ ] Replace `credentials:` with `auth:` and update structure
- [ ] Add `type` field to all auth configurations
- [ ] Remove manual Authorization headers (HTTP plugin handles automatically)
- [ ] Update DuckDB credential aliases to use new structure
- [ ] Test that authentication still works
- [ ] Verify no sensitive data in logs (automatic redaction)
- [ ] Remove deprecation warnings from logs

## Backwards Compatibility

The system maintains full backwards compatibility:

- Old syntax still works but generates warnings
- Automatic transformation of deprecated fields
- Gradual migration supported
- No breaking changes in v1.x

Deprecation warnings will appear like:
```
COMPATIBILITY: Step 'my_task' uses deprecated 'credentials' field. 
Please migrate to 'auth' field. See https://docs.noetl.io/migration/auth-unified
```