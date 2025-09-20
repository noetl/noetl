# Migration: Unified Auth System

This guide covers migrating from the previous three-part credential system (`auth`, `credentials`, `secret`) to the new unified `auth` dictionary approach.

## Overview

The new unified system consolidates all authentication into a single `auth:` attribute that maps aliases to typed credential specifications. This provides:

- **Consistency**: Single auth attribute for all scenarios
- **Type Safety**: Explicit credential types (postgres, hmac, bearer, etc.)
- **Flexibility**: Supports simple string references and complex multi-credential scenarios
- **Template Access**: All fields accessible via `{{ auth.<alias>.<field> }}`

## Migration Patterns

### Single Credential (Postgres)

**Before:**
```yaml
- step: create_table
  type: postgres
  auth: {pg: {type: postgres, key: pg_local}}  # Use dictionary format consistently
  command: CREATE TABLE users (id SERIAL, name TEXT);
```

**After:**
```yaml
- step: create_table
  type: postgres
  auth:
    pg:
      type: postgres
      key: pg_local
  command: CREATE TABLE users (id SERIAL, name TEXT);
```

### Multiple Credentials (DuckDB)

**Before:**
```yaml
- step: aggregate_data
  type: duckdb
  credentials:
    pg_db:      { key: pg_local }
    gcs_secret: { key: gcs_hmac_local }
  commands: |
    ATTACH '{{ credentials.pg_db.connstr }}' AS pg_db (TYPE postgres);
    CREATE SECRET gcs_secret (
      TYPE gcs,
      KEY_ID '{{ credentials.gcs_secret.key_id }}',
      SECRET '{{ credentials.gcs_secret.secret_key }}'
    );
```

**After:**
```yaml
- step: aggregate_data
  type: duckdb
  auth:
    pg_db:
      type: postgres
      key: pg_local
    gcs_secret:
      type: hmac
      service: gcs
      key: gcs_hmac_local
      scope: "gs://{{ workload.gcs_bucket }}"
  commands: |
    -- Secrets are auto-created, just reference them
    ATTACH '' AS pg_db (TYPE postgres, SECRET pg_db);
    
    -- GCS secret auto-created with scope
    COPY data TO 'gs://mybucket/data.parquet' (FORMAT PARQUET);
```

### External Secret Manager

**Before:**
```yaml
- step: api_call
  type: http
  method: GET
  endpoint: "https://api.example.com/data"
  headers:
    Authorization: "Bearer {{ secret.api_service_token }}"
```

**After:**
```yaml
- step: api_call
  type: http
  method: GET
  endpoint: "https://api.example.com/data"
  auth:
    api:
      type: bearer
      key: api_service_token
      provider: secret_manager
  # Headers are auto-generated from auth
```

Or access explicitly in templates:
```yaml
- step: api_call
  type: http
  method: GET
  endpoint: "https://api.example.com/data"
  auth:
    api:
      type: bearer
      key: api_service_token
  headers:
    Authorization: "Bearer {{ auth.api.token }}"
```

### Save Storage

**Before:**
```yaml
save:
  storage: postgres  # Legacy nested structure converted
  auth: {pg: {type: postgres, key: pg_local}}  # Use dictionary format consistently
  table: results
```

**After:**
```yaml
save:
  storage: postgres
  auth:
    pg:
      type: postgres
      key: pg_local
  table: results
```

## Credential Types and Fields

### postgres
```yaml
auth:
  pg:
    type: postgres
    key: pg_local
    # Optional overrides (from credential record):
    # db_host: localhost
    # db_port: 5432
    # db_name: mydb
    # db_user: user
    # db_password: password
    # sslmode: require
```

### hmac (GCS/S3 compatible)
```yaml
auth:
  gcs:
    type: hmac
    service: gcs  # or s3
    key: gcs_hmac_local
    scope: "gs://{{ workload.bucket }}"
    # Optional overrides:
    # key_id: HMAC_KEY_ID
    # secret_key: HMAC_SECRET
    # region: us-east-1 (for S3)
```

### bearer (API tokens)
```yaml
auth:
  api:
    type: bearer
    key: api_service_token
    provider: secret_manager  # or credential_store (default)
    # Optional override:
    # token: explicit_token_value
```

### basic (Username/password)
```yaml
auth:
  basic:
    type: basic
    key: basic_auth_cred
    # Optional overrides:
    # username: user
    # password: pass
```

### api_key (Custom headers)
```yaml
auth:
  api:
    type: api_key
    key: api_key_cred
    header: "X-API-Key"  # Default: X-API-Key
    # Optional override:
    # value: explicit_api_key
```

### header (Custom headers)
```yaml
auth:
  custom:
    type: header
    name: "X-Custom-Header"
    value: "{{ some_template }}"
```

## Providers

### credential_store (default)
Fetches from NoETL's credential store via the `/credentials/{key}` API.

### secret_manager
Fetches scalar values from external secret managers (HashiCorp Vault, AWS Secrets Manager, etc.).

### inline (not recommended)
Credentials specified directly in the playbook (avoid for production).

## Template Access

All resolved credential fields are available via `{{ auth.<alias>.<field> }}`:

```yaml
auth:
  pg:
    type: postgres
    key: pg_local
  api:
    type: bearer
    key: api_token

# Access in templates:
commands: |
  -- Use postgres connection details
  HOST: {{ auth.pg.db_host }}
  PORT: {{ auth.pg.db_port }}
  
  -- Use API token
  Authorization: Bearer {{ auth.api.token }}
```

## Backward Compatibility

The system maintains backward compatibility for:

- Legacy `credentials:` mappings (converted internally)
- `{{ secret.* }}` template access (deprecated, use `{{ auth.* }}`)

**Note**: Simple string `auth: credential_key` references are deprecated in favor of the consistent dictionary format.

## Plugin Behavior Changes

### DuckDB Plugin
- Auto-creates DuckDB secrets from `auth` dictionary
- Installs required extensions (postgres, httpfs) automatically
- Supports native DuckDB secret usage: `ATTACH '' AS alias (TYPE postgres, SECRET alias)`
- Infers GCS scope from `output_uri_base` when not explicitly set

### Postgres Plugin
- Prefers unified auth over legacy credential resolution
- Supports `use_auth: alias` to select specific auth when multiple postgres auths exist
- Maintains backward compatibility with explicit `db_*` field overrides

### HTTP Plugin
- Auto-generates authentication headers from auth configuration
- Supports bearer, basic, api_key, and custom header authentication
- Redacts sensitive headers in logs automatically

### Save Plugin
- Passes auth configuration through to target storage plugins
- Supports both unified auth dictionary and legacy string references

## Migration Strategy

1. **Phase 1**: Update playbooks to use unified auth syntax while maintaining functionality
2. **Phase 2**: Remove deprecated `credentials:` and `{{ secret.* }}` usage
3. **Phase 3**: Adopt advanced features like multi-type auth and scoped credentials

## Best Practices

- **Use explicit types**: Always specify `type` in auth specifications
- **Leverage auto-creation**: Let DuckDB plugin auto-create secrets rather than manual CREATE SECRET
- **Use scoping**: Specify `scope` for cloud storage credentials to improve security
- **Minimize inline secrets**: Prefer `credential_store` or `secret_manager` providers
- **Test migration**: Validate that migrated playbooks produce identical results
