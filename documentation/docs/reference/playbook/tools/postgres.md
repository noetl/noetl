# Postgres Plugin

## Overview

The Postgres plugin executes SQL commands against PostgreSQL databases. It uses the new credential system with `auth:` for single credential lookup from the NoETL Server.

## New Behavior (v0.2+)

- **Preferred**: Use `auth: <credential_key>` for automatic credential resolution
- **Resolved fields**: `db_name`, `db_user`, `db_password`, `db_host`, `db_port`, optional `sslmode`
- **Override support**: Non-secret fields can be overridden via `with:`
- **Security**: Secrets are step-scoped and never persisted to results

## Example Usage

### Basic Table Creation
```yaml
- step: ensure_pg_table
  tool: postgres
  auth: pg_local
  command: |
    CREATE TABLE IF NOT EXISTS public.weather_http_raw (
      id TEXT PRIMARY KEY,
      execution_id TEXT,
      iter_index INTEGER,
      city TEXT,
      url TEXT,
      elapsed DOUBLE PRECISION,
      payload TEXT,
      created_at TIMESTAMPTZ DEFAULT now()
    );
```

### With Non-Secret Overrides
```yaml
- step: custom_database
  tool: postgres
  auth: pg_local
  with:
    db_name: "custom_database"  # Override default database
    sslmode: "require"          # Override SSL mode
  command: |
    SELECT version();
```

### Data Insertion with Templates
```yaml
- step: insert_weather_data
  tool: postgres
  auth: pg_local
  command: |
    INSERT INTO public.weather_http_raw (
      id, execution_id, iter_index, city, url, elapsed, payload, created_at
    ) VALUES (
      '{{ data.id }}',
      '{{ execution_id }}',
      {{ http_loop.result_index | default(0) }},
      '{{ city.name }}',
      '{{ data.url }}',
      {{ data.elapsed | default(0) }},
      '{{ data | tojson }}',
      now()
    );
```

## Migration from v0.1.x

### Before
```yaml
- step: get_pg_credential
  tool: secret
  path: credentials/postgres/local
  
- step: postgres_task
  tool: postgres
  credential: "{{ get_pg_credential.data.data }}"
  command: SELECT 1;
```

### After
```yaml
- step: postgres_task
  type: postgres
  auth: pg_local
  command: SELECT 1;
```

## Security Notes

- Connection details are resolved at runtime and never logged
- DSNs containing passwords are automatically redacted in logs
- Credential payloads are ephemeral and not persisted to execution results
- Use `auth:` instead of passing credentials via `with:` to maintain security
