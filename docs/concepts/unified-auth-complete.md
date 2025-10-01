# NoETL Unified Authentication System - Complete Implementation

## Overview

The unified authentication system consolidates the previous three-part credential system (`auth`, `credentials`, `secret`) into a single, powerful `auth` dictionary approach. This provides consistency, type safety, and flexibility across all NoETL plugins.

## Architecture

### Core Components

1. **`noetl/worker/plugin/_auth.py`** - Core auth resolution helper
2. **Plugin Integrations** - Updated DuckDB, Postgres, HTTP, and Save plugins
3. **Backward Compatibility** - Legacy system support during transition
4. **Security** - Automatic redaction of sensitive values in logs

### Key Features

- **Unified Interface**: Single `auth:` dictionary for all credential scenarios
- **Type Safety**: Explicit credential types (postgres, hmac, bearer, etc.)
- **Template Access**: All fields accessible via `{{ auth.<alias>.<field> }}`
- **Auto-Creation**: DuckDB secrets and HTTP headers generated automatically
- **Provider Support**: Credential store, secret manager, and inline options
- **Scoped Credentials**: Support for scoped access (e.g., GCS bucket-level)

## Authentication Types

### postgres
```yaml
auth:
  pg:
    type: postgres
    key: pg_local
    # Auto-resolved fields: db_host, db_port, db_name, db_user, db_password, sslmode
```

### hmac (GCS/S3 Compatible)
```yaml
auth:
  gcs:
    type: hmac
    service: gcs  # or s3
    key: gcs_hmac_local
    scope: "gs://{{ workload.bucket }}"
    # Auto-resolved fields: key_id, secret_key, region (for S3)
```

### bearer (API Tokens)
```yaml
auth:
  api:
    type: bearer
    key: api_service_token
    provider: secret_manager  # optional: credential_store (default), inline
    # Auto-resolved fields: token, access_token
```

### basic (Username/Password)
```yaml
auth:
  basic:
    type: basic
    key: basic_auth_cred
    # Auto-resolved fields: username, password
```

### api_key (Custom API Keys)
```yaml
auth:
  api:
    type: api_key
    key: api_key_cred
    header: "X-API-Key"  # default: X-API-Key
    # Auto-resolved fields: value
```

### header (Custom Headers)
```yaml
auth:
  custom:
    type: header
    name: "X-Custom-Header"
    value: "{{ some_template }}"
```

## Plugin Behavior

### DuckDB Plugin
- **Auto-Extension Loading**: Installs/loads postgres, httpfs extensions as needed
- **Secret Generation**: Creates DuckDB secrets automatically from auth config
- **Native Usage**: `ATTACH '' AS alias (TYPE postgres, SECRET alias)`
- **Scoped Cloud Access**: GCS/S3 secrets with proper scope configuration
- **Cloud Output Detection**: Infers scopes from `output_uri_base` when possible

### Postgres Plugin
- **Unified Auth Priority**: Prefers unified auth over legacy credential resolution
- **Multi-Auth Support**: `use_auth: alias` to select specific auth when multiple exist
- **Field Merging**: Auth fields merged with task_with parameters (task_with wins)
- **Backward Compatibility**: Still supports legacy `auth: string` format

### HTTP Plugin
- **Header Generation**: Auto-generates authentication headers from auth config
- **Multi-Auth Support**: Combines multiple auth types (bearer + api_key + custom)
- **Redaction**: Automatically redacts sensitive headers in logs
- **Template Access**: Fields available in templates: `{{ auth.alias.field }}`

### Save Plugin
- **Auth Pass-through**: Passes unified auth to target storage plugins
- **Format Support**: Supports both dictionary and string auth formats
- **Legacy Compatibility**: Maintains backward compatibility with old credential field

## Example Usage

### Complete Multi-Service Pipeline
```yaml
apiVersion: noetl.io/v1
kind: Playbook

metadata:
  name: unified_auth_pipeline
  path: examples/unified_auth_pipeline

workload:
  gcs_bucket: "my-data-bucket"
  api_base: "https://api.example.com"

workflow:
  # Simple Postgres step
  - step: setup_tables
    type: postgres
    auth:
      pg:
        type: postgres
        key: pg_local
    command: |
      CREATE TABLE IF NOT EXISTS api_data (
        id SERIAL PRIMARY KEY,
        data JSONB,
        created_at TIMESTAMPTZ DEFAULT now()
      );
    next:
      - step: fetch_api_data

  # HTTP with multiple auth types
  - step: fetch_api_data
    type: http
    method: POST
    endpoint: "{{ workload.api_base }}/secure/data"
    auth:
      bearer_token:
        type: bearer
        key: api_bearer_token
        provider: secret_manager
      api_key:
        type: api_key
        key: api_key_secret
        header: "X-Service-Key"
      custom_auth:
        type: header
        name: "X-Pipeline-ID"
        value: "{{ execution_id }}"
    # Headers auto-generated:
    # Authorization: Bearer <token>
    # X-Service-Key: <api_key>
    # X-Pipeline-ID: <execution_id>
    data:
      query: "SELECT * FROM users WHERE active = true"
      limit: 1000
    next:
      - step: process_with_duckdb

  # DuckDB with multiple credentials and auto-secrets
  - step: process_with_duckdb
    type: duckdb
    auth:
      pg_db:
        type: postgres
        key: pg_local
        secret_name: pg_main
      gcs_storage:
        type: hmac
        service: gcs
        key: gcs_hmac_prod
        scope: "gs://{{ workload.gcs_bucket }}"
      s3_backup:
        type: hmac
        service: s3
        key: aws_s3_backup
        scope: "s3://backup-bucket"
    with:
      auto_secrets: true  # default: true
    commands: |
      -- Extensions auto-loaded: postgres, httpfs
      -- Secrets auto-created: pg_main, gcs_storage, s3_backup
      
      -- Native DuckDB usage
      ATTACH '' AS pg_db (TYPE postgres, SECRET pg_main);
      
      -- Process the HTTP response data
      CREATE OR REPLACE TABLE processed_data AS
      SELECT 
        id,
        data->'name' as name,
        data->'email' as email,
        now() as processed_at
      FROM pg_db.public.api_data
      WHERE created_at >= current_date;
      
      -- Write to cloud storage (auto-scoped)
      COPY processed_data TO 'gs://{{ workload.gcs_bucket }}/processed/data_{{ execution_id }}.parquet' 
      (FORMAT PARQUET);
      
      -- Backup to S3 (different scope)
      COPY processed_data TO 's3://backup-bucket/daily/data_{{ execution_id }}.parquet'
      (FORMAT PARQUET);
    next:
      - step: save_results

  # Save with unified auth
  - step: save_results
    type: save
    save:
      storage: postgres
      auth:
        pg_results:
          type: postgres
          key: pg_local
      table: pipeline_results
      mode: upsert
      key: execution_id
      data:
        execution_id: "{{ execution_id }}"
        status: "completed"
        records_processed: "{{ get_from_previous('processed_data.count') }}"
        gcs_path: "gs://{{ workload.gcs_bucket }}/processed/data_{{ execution_id }}.parquet"
        s3_backup_path: "s3://backup-bucket/daily/data_{{ execution_id }}.parquet"
        completed_at: "{{ now() }}"
```

## Security Features

- **Automatic Redaction**: Sensitive fields redacted in all logs
- **Step-Scoped Secrets**: Credentials only available during step execution
- **No Persistence**: Secret values never stored in results or logs
- **Template Safety**: Secure template resolution with field validation
- **Provider Isolation**: Clear separation between credential sources

## Migration Path

1. **Phase 1**: Deploy unified auth system with backward compatibility
2. **Phase 2**: Update playbooks to use unified auth syntax
3. **Phase 3**: Deprecate legacy `credentials` and `{{ secret.* }}` usage
4. **Phase 4**: Remove legacy support in future major version

## Testing

Comprehensive test suite covers:
- Auth resolution with various providers
- Legacy format conversion
- Plugin integrations
- Security (redaction, field isolation)
- Template rendering and scoping
- Multi-auth scenarios
- Error handling and fallbacks

## Benefits

1. **Consistency**: Single auth pattern across all plugins and scenarios
2. **Type Safety**: Explicit types prevent configuration errors
3. **Security**: Built-in redaction and scope isolation
4. **Flexibility**: Support for multiple auth types and providers
5. **Performance**: Auto-optimization (secret pre-creation, extension loading)
6. **Maintainability**: Centralized auth logic, easier to extend and debug
7. **User Experience**: Simpler syntax, better error messages, comprehensive documentation

The unified authentication system provides a robust, secure, and user-friendly foundation for credential management in NoETL pipelines.
