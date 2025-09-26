# DuckDB step

Run DuckDB SQL; optionally attach external systems using unified auth.

What it does
- Executes one or more SQL statements in DuckDB.
- Can load extensions (httpfs, postgres, etc.) and attach external databases.
- Produces tables/views accessible within the step; result exposure is engine-dependent.

Required keys
- type: duckdb
- commands or sql: SQL text to execute

Common optional keys
- auth: a mapping of credential aliases (e.g., postgres, hmac) to use inside DuckDB
- assert: Validate inputs/outputs (expects/returns)
- save: Persist selected results for later steps

Auth and attachments
- Postgres: install/load postgres; then ATTACH with SECRET bound to an alias
- GCS/S3: install/load httpfs; credentials bound via auth mapping and scope

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
