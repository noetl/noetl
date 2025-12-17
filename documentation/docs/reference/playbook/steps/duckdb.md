# DuckDB step

Run DuckDB SQL; optionally attach external systems using unified auth.

What it does
- Executes one or more SQL statements in DuckDB.
- Can load extensions (httpfs, postgres, etc.) and attach external databases.
- Produces tables/views accessible within the step; result exposure is engine-dependent.

Required keys
- tool: duckdb
- commands or sql: SQL text to execute

Common optional keys
- auth: mapping of credential aliases (e.g., postgres, hmac) to use inside DuckDB
- assert: Validate inputs/outputs (expects/returns)
- sink: Persist selected results for later steps
- retry: Bounded re-attempt policy for transient failures (see `retry.md`)

Auth and attachments
- Postgres: install/load postgres; then ATTACH with SECRET bound to an alias
- GCS/S3: install/load httpfs; credentials bound via auth mapping and scope

Unified auth mapping example (from HTTP → DuckDB → Postgres → GCS pipeline)
```yaml
- step: aggregate_with_duckdb
  tool: duckdb
  auth:
    pg_db:
      source: credential
      type: postgres
      key: "{{ workload.pg_auth }}"
    gcs_secret:
      source: credential
      type: hmac
      key: gcs_hmac_local
      scope: gs://{{ workload.gcs_bucket }}
  assert:
    expects: [ auth.pg_db, auth.gcs_secret, data.require_cloud_output ]
    returns: [ weather_flat, weather_agg ]
  commands: |
    INSTALL postgres; LOAD postgres;
    INSTALL httpfs;  LOAD httpfs;

    ATTACH '' AS pg_db (TYPE postgres, SECRET pg_db);
    CREATE OR REPLACE TABLE weather_flat AS
    SELECT id, city, url AS source_url, elapsed AS elapsed_sec, payload
    FROM pg_db.public.weather_http_raw
    WHERE execution_id = '{{ execution_id }}';

    CREATE OR REPLACE TABLE weather_agg AS
    SELECT city, COUNT(*) AS rows_per_city
    FROM weather_flat
    GROUP BY city;

    COPY weather_flat TO 'gs://{{ workload.gcs_bucket }}/weather/flat_{{ execution_id }}.parquet' (FORMAT PARQUET);
    COPY weather_agg  TO 'gs://{{ workload.gcs_bucket }}/weather/agg_{{ execution_id }}.parquet'  (FORMAT PARQUET);
```

Usage patterns (fragments)
- Attach Postgres and aggregate into DuckDB tables
  # ...existing code...
  commands: |
    INSTALL postgres; LOAD postgres;
    ATTACH '' AS pg_db (TYPE postgres, SECRET pg_db);
    CREATE OR REPLACE TABLE weather_flat AS
    SELECT id, city, url AS source_url, elapsed AS elapsed_sec, payload
    FROM pg_db.public.weather_http_raw
    WHERE execution_id = '{{ execution_id }}';

- Write Parquet to cloud storage using httpfs
  # ...existing code...
  commands: |
    INSTALL httpfs; LOAD httpfs;
    COPY weather_flat TO 'gs://{{ workload.gcs_bucket }}/weather/flat_{{ execution_id }}.parquet' (FORMAT PARQUET);

Tips
- Use CREATE OR REPLACE to make reruns idempotent.
- Keep large result materializations constrained; consider CTAS into temporary tables.
- Ensure the proper auth entries exist in the playbook header for each alias.
- Add a `retry` block if external attachments (network to Postgres or cloud storage) are occasionally flaky.
