# DuckDB Plugin

## Overview

The DuckDB plugin can read/write local files and cloud storage, and attach external databases. It supports multiple credentials via `credentials:` where aliases become your native DuckDB handles.

## Aliases and credentials

- credentials: map of alias → `{ key: <credential_name> }`
- Aliases are used natively in DuckDB:
  - `ATTACH ... AS <alias>` for catalogs
  - `SECRET <alias>` for both cloud and Postgres/MySQL auth
- For Postgres, the plugin now auto-creates a DuckDB SECRET named after the alias when enough fields exist in the credential (HOST/PORT/DATABASE/USER/PASSWORD). Use the SECRET in ATTACH.
- `credentials.<alias>.secret` exposes the secret name; `credentials.<alias>.connstr` remains for backward compat.
 - For object stores (GCS/S3), provide `scope` in the credential record to let DuckDB select the right secret automatically. If `scope` is missing, the plugin attempts to infer it from `with.output_uri_base` when it is a cloud URI.

## Example

```yaml
type: duckdb
credentials:
  pg_db:      { key: pg_local }
  gcs_secret: { key: gcs_hmac_local }
commands: |
  INSTALL postgres; LOAD postgres;
  INSTALL httpfs;  LOAD httpfs;

  -- Preferred: ATTACH via named SECRET created from the credential alias
  ATTACH '' AS pg_db (TYPE postgres, SECRET pg_db);

  CREATE OR REPLACE SECRET gcs_secret (
    TYPE gcs,
    KEY_ID  '{{ credentials.gcs_secret.key_id }}',
    SECRET  '{{ credentials.gcs_secret.secret_key }}',
    SCOPE   'gs://{{ workload.gcs_bucket }}'
  );

  CREATE OR REPLACE TABLE weather_flat AS
  SELECT id, city, url, elapsed, payload
  FROM   pg_db.public.weather_http_raw
  WHERE  execution_id = '{{ execution_id }}';

  COPY weather_flat TO 'gs://{{ workload.gcs_bucket }}/weather/flat_{{ execution_id }}.parquet' (FORMAT PARQUET);
```

## Notes

- The plugin also auto-loads cloud access via secrets if URIs are present and matching credentials are provided.
- Aliases are under your control; choose names that match how you prefer to address catalogs and secrets in SQL.
