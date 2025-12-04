# NoETL Unified Authentication Migration Guide

## Overview

NoETL v1.0+ introduces a unified authentication system that consolidates all authentication patterns under a single `auth` attribute. This replaces the previous split between `auth`, `credentials`, and other plugin-specific authentication methods.

## Key Benefits

- **Single Syntax**: One `auth` attribute for all plugins and authentication types
- **Flexible Sources**: Support for credential store, environment variables, secret managers, and inline configuration  
- **Multi-Auth**: DuckDB supports multiple authentication aliases for different services
- **Type Safety**: Strong validation with plugin-specific requirements
- **Security**: Automatic redaction of sensitive information in logs

## Migration Path

### 1. Single Authentication (Postgres, HTTP)

**Before (Deprecated):**
```yaml
- step: query_database
  tool: postgres
  credential: my_postgres_cred  # ❌ Deprecated
  command_b64: "..."
```

**After (Unified):**
```yaml
- step: query_database  
  tool: postgres
  auth:                    # ✅ New unified syntax
    type: postgres
    credential: my_postgres_cred
  command_b64: "..."
```

### 2. Multi-Authentication (DuckDB)

**Before (Deprecated):**
```yaml
- step: process_data
  tool: duckdb
  credentials:             # ❌ Deprecated
    db:
      key: postgres_main
    storage:
      key: gcs_hmac
  command_b64: "..."
```

**After (Unified):**
```yaml
- step: process_data
  tool: duckdb
  auth:                    # ✅ New unified syntax
    db:
      type: postgres
      credential: postgres_main
    storage:
      type: gcs
      credential: gcs_hmac
  command_b64: "..."
```

## Authentication Sources

### 1. Credential Store (Recommended)
Reference credentials stored in NoETL's credential store:

```yaml
auth:
  type: postgres
  credential: my_database_cred
```

### 2. Environment Variables
Reference environment variables for tokens and simple auth:

```yaml
auth:
  type: bearer
  env: API_TOKEN
```

### 3. Secret Manager
Reference external secret managers (Google Secret Manager, etc.):

```yaml
auth:
  type: api_key
  secret: projects/my-project/secrets/api-key/versions/latest
```

### 4. Inline Configuration
Define credentials directly (not recommended for production):

```yaml
auth:
  type: postgres
  inline:
    host: localhost
    port: 5432
    user: testuser
    password: testpass  # ⚠️ Consider using credential store instead
    database: testdb
```

## Plugin-Specific Patterns

### Postgres Plugin (Single Auth)

```yaml
- step: run_sql
  tool: postgres
  auth:
    type: postgres
    credential: production_db
  command_b64: "U0VMRUNUICogRlJPTSB1c2Vyczs="
```

### HTTP Plugin (Single Auth)

#### Bearer Token
```yaml
- step: api_call
  tool: http
  method: GET
  endpoint: https://api.example.com/data
  auth:
    type: bearer
    env: API_TOKEN
```

#### Basic Authentication
```yaml
- step: api_call
  tool: http
  method: POST
  endpoint: https://api.example.com/secure
  auth:
    type: basic
    inline:
      username: admin
      password: "{{ secrets.admin_password }}"
```

#### API Key
```yaml
- step: api_call
  tool: http
  method: GET
  endpoint: https://api.example.com/data
  auth:
    type: api_key
    inline:
      key: X-API-Key
      value: "{{ secrets.api_key }}"
```

#### Custom Headers
```yaml
- step: api_call
  tool: http
  method: GET
  endpoint: https://api.example.com/data
  auth:
    type: header
    inline:
      Authorization: "Custom {{ secrets.custom_token }}"
      X-Client-ID: "{{ workload.client_id }}"
```

### DuckDB Plugin (Multi Auth)

#### Multiple Services
```yaml
- step: etl_pipeline
  tool: duckdb
  auth:
    # Postgres connection for reading
    source_db:
      type: postgres
      credential: warehouse_readonly
    
    # GCS for data storage
    data_storage:
      type: gcs
      credential: gcs_hmac_key
      
    # S3 for backup storage  
    backup_storage:
      type: s3
      env: AWS_CREDENTIALS
  
  command_b64: |
    -- DuckDB automatically creates secrets: source_db, data_storage, backup_storage
    CREATE TABLE results AS 
    SELECT * FROM postgres_scan('source_db', 'public', 'source_table');
    
    COPY results TO 'gs://my-bucket/results.parquet';
```

#### Single Auth Auto-Wrapped
DuckDB can also accept single auth configurations that get auto-wrapped:

```yaml
- step: simple_duckdb
  tool: duckdb
  auth:  # Single auth gets wrapped as 'default' alias
    type: postgres
    credential: simple_db
  command_b64: |
    CREATE TABLE data AS 
    SELECT * FROM postgres_scan('default', 'public', 'table');
```

## Template Integration

The unified auth system supports Jinja2 templating:

```yaml
auth:
  type: postgres
  inline:
    host: "{{ workload.environment }}.db.example.com"
    port: "{{ 5432 if workload.environment == 'dev' else 5433 }}"
    user: "user_{{ execution_id[:8] }}"
    database: "{{ workload.database_name }}"
    password: "{{ secrets.db_password }}"
```

## Validation Rules

### Plugin Arity Requirements
- **Postgres**: Single auth only (`auth_arity=single`)
- **HTTP**: Single auth only (`auth_arity=single`) 
- **DuckDB**: Multi auth preferred (`auth_arity=multi`), single auth auto-wrapped

### Reserved Keywords
In multi-auth configurations, these aliases are reserved:
- `type`, `credential`, `secret`, `env`, `inline`

### Required Fields
Every auth configuration must have:
- `type`: Authentication type (postgres, gcs, bearer, etc.)
- One source: `credential`, `secret`, `env`, or `inline`

## Backwards Compatibility

### Automatic Migration
The system automatically transforms deprecated fields with warnings:

```yaml
# This deprecated syntax...
credentials: my_old_cred

# ...is automatically converted to:
auth:
  type: <inferred>  
  credential: my_old_cred
```

### Deprecation Warnings
You'll see warnings like:
```
COMPATIBILITY: Step 'my_task' uses deprecated 'credentials' field. 
Please migrate to 'auth' field. See https://docs.noetl.io/migration/auth-unified
```

### Support Timeline
- **Current**: Backwards compatibility with warnings
- **v2.0**: Deprecated fields will be removed

## Security Best Practices

### 1. Use Credential Store
```yaml
# ✅ Recommended
auth:
  type: postgres
  credential: production_db

# ❌ Avoid in production  
auth:
  type: postgres
  inline:
    password: hardcoded_password
```

### 2. Environment Variables for Tokens
```yaml
# ✅ Good for CI/CD
auth:
  type: bearer
  env: API_TOKEN
```

### 3. Template Sensitive Values
```yaml
# ✅ Use templates for dynamic secrets
auth:
  type: postgres
  inline:
    password: "{{ secrets.dynamic_password }}"
```

## Troubleshooting

### Common Issues

#### 1. "Plugin expects single auth but received multi auth"
```yaml
# ❌ Wrong: Postgres expects single auth
- step: postgres_task
  tool: postgres
  auth:
    db1: {...}  # Multi auth not supported

# ✅ Correct: Use single auth
- step: postgres_task
  tool: postgres  
  auth:
    type: postgres
    credential: my_db
```

#### 2. "Auth alias 'type' is reserved"
```yaml
# ❌ Wrong: 'type' is reserved in multi-auth
auth:
  type: {...}  # Reserved keyword

# ✅ Correct: Use descriptive aliases
auth:
  primary_db: {...}
```

#### 3. "Auth configuration must specify exactly one source"
```yaml
# ❌ Wrong: Multiple sources
auth:
  type: postgres
  credential: db_cred
  inline: {...}    # Can't have both

# ✅ Correct: One source only
auth:
  type: postgres
  credential: db_cred
```

### Validation Steps

1. **Check Plugin Compatibility**: Ensure auth type matches plugin expectations
2. **Verify Sources**: Each auth config needs exactly one source
3. **Test Templates**: Validate Jinja expressions render correctly  
4. **Review Logs**: Look for deprecation warnings and security redactions

## Migration Checklist

- [ ] Replace `credential: key` with `auth: {type: ..., credential: key}`
- [ ] Replace `credentials: {...}` with `auth: {...}` 
- [ ] Add `type` field to all auth configurations
- [ ] Choose appropriate source (`credential`, `env`, `secret`, `inline`)
- [ ] Update DuckDB multi-auth to use alias structure
- [ ] Test authentication works with new syntax
- [ ] Review logs for deprecation warnings
- [ ] Update documentation and examples

## Examples Repository

## Examples Repository

See the `tests/fixtures/playbooks/oauth/` directory for complete working examples:
- `tests/fixtures/playbooks/oauth/google_secret_manager/google_secret_manager.yaml`
- `tests/fixtures/playbooks/oauth/google_gcs/google_gcs_oauth.yaml`
- `tests/fixtures/playbooks/oauth/interactive_brokers/ib_gateway_test.yaml`