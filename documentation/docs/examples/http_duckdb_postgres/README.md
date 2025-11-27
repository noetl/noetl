---
sidebar_position: 1
---

# Http duckdb postgres

A comprehensive integration test demonstrating:
- **HTTP API integration** with external weather service (Open-Meteo)
- **Async iterator processing** over multiple cities
- **PostgreSQL storage** with upsert capabilities
- **DuckDB analytics** with cross-database queries
- **GCS cloud storage** output using unified authentication
- **Excel export** via Polars-powered DuckDB COPY commands
- **Multi-stage pipeline** with data transformation and aggregation

## Pipeline Flow

1. **Setup**: Creates PostgreSQL table for raw HTTP results
2. **Data Collection**: Fetches weather data for multiple cities (London, Paris, Berlin) asynchronously
3. **Storage**: Saves raw HTTP responses to PostgreSQL with upsert mode
4. **Analytics**: Uses DuckDB to:
   - Connect to PostgreSQL data
   - Flatten and aggregate results by city
   - Export processed data to GCS as Parquet files and an Excel workbook (`gs://…/weather/weather_<execution_id>.xlsx`)
5. **Metrics**: Records pipeline metrics back to PostgreSQL

## Key Features Tested

- **Iterator step type** with async mode for parallel processing
- **Cross-database connectivity** (DuckDB → PostgreSQL)
- **Cloud storage integration** with credential management
- **Data format handling** (JSON → SQL → Parquet)
- **Error handling** with safe defaults in Jinja expressions
- **Unified authentication** across multiple services

### Runtime Tests with Kubernetes Cluster

#### Prerequisites
- Kubernetes cluster deployed with NoETL (use `task bring-all` to deploy full stack)
- NoETL API accessible on `localhost:8082`
- PostgreSQL accessible on `localhost:54321`
- Internet connectivity for weather API

#### Test Commands
```bash
# Register required credentials
task register-test-credentials

# Register HTTP DuckDB Postgres playbook
task test-register-http-duckdb-postgres

# Execute HTTP DuckDB Postgres test
task test-execute-http-duckdb-postgres

# Full integration test (credentials + register + execute)
task test-http-duckdb-postgres-full
```

#### Alias Commands (shorter)
```bash
# Register credentials
task rtc

# Register playbook
task trhdp

# Execute playbook
task tehdp

# Full test workflow
task thdpf
```

## Configuration

The playbook expects these authentication credentials:
- `pg_k8s`: PostgreSQL database connection (for cluster-based testing)
- `gcs_hmac_local`: GCS HMAC credentials for bucket access

Workload parameters:
- `cities`: List of cities with lat/lon coordinates
- `base_url`: Weather API endpoint
- `gcs_bucket`: Target GCS bucket for output files

## Playbook Example

```yaml title="http_duckdb_postgres.yaml"
apiVersion: noetl.io/v1
kind: Playbook

metadata:
  name: http_duckdb_postgres
  path: examples/http_duckdb_postgres # catalog path; do not change in tests

workload:
  pg_auth: pg_local
  message: HTTP -> DuckDB -> Postgres pipeline
  cities:
    - name: London
      lat: 51.51
      lon: -0.13
    - name: Paris
      lat: 48.85
      lon: 2.35
    - name: Berlin
      lat: 52.52
      lon: 13.41
  base_url: https://api.open-meteo.com/v1
  gcs_bucket: noetl-demo-19700101
workflow:
  - step: start
    desc: Start pipeline
    next:
      - step: ensure_pg_table

  - step: ensure_pg_table
    desc: Ensure raw HTTP results table exists in Postgres
    tool: postgres
    auth: "{{ workload.pg_auth }}"
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
    next:
      - step: http_loop
        args:
          cities: "{{ workload.cities }}"

  - step: http_loop
    desc: Fetch hourly temperatures for each city and save raw rows
    tool: iterator
    collection: "{{ workload.cities }}"
    element: city
    mode: async
    task:
      tool: http
      args:
        latitude: "{{ city.lat }}"
        longitude: "{{ city.lon }}"
        hourly: temperature_2m
        forecast_days: 1
      endpoint: "{{ workload.base_url }}/forecast"
      headers:
        User-Agent: NoETL City HTTP -> PG Demo/1.0
      assert:
        expects:
          - latitude
          - longitude
          - hourly
          - forecast_days
        returns:
          - data.url
          - data.elapsed
          - data.payload
      save:
        storage: postgres
        args:
          id: "{{ execution_id }}:{{ city.name }}:{{ http_loop.result_index }}"
          execution_id: "{{ execution_id }}"
          iter_index: "{{ http_loop.result_index }}"
          city: "{{ city.name }}"
          url: "{{ this.data.url if this is defined and this.data is defined else '' }}"
          elapsed: "{{ (this.data.elapsed | default(0)) if this is defined and this.data is defined else 0 }}"
          payload: "{{ (this.data | tojson) if this is defined and this.data is defined else '' }}"
        auth: "{{ workload.pg_auth }}"
        table: public.weather_http_raw
        mode: upsert
        key: id
    next:
      - step: aggregate_with_duckdb

  - step: aggregate_with_duckdb
    args:
      require_cloud_output: true
    desc: Read Postgres rows in DuckDB, aggregate, write to GCS using unified auth dictionary
    tool: duckdb
    auth:
      pg_db:
        source: credential
        tool: postgres
        key: "{{ workload.pg_auth }}"
      gcs_secret:
        source: credential
        tool: hmac
        key: gcs_hmac_local
        scope: gs://{{ workload.gcs_bucket }}
    assert:
      expects:
        - auth.pg_db
        - auth.gcs_secret
        - data.require_cloud_output
      returns:
        - weather_flat
        - weather_agg
    commands: |
      -- Load needed extensions
      INSTALL postgres; LOAD postgres;
      INSTALL httpfs;  LOAD httpfs;

      -- Attach using the postgres credential via alias 'pg_db'
      ATTACH '' AS pg_db (TYPE postgres, SECRET pg_db);

      -- GCS secrets are auto-created from auth mapping; no SQL needed here.

      -- Flattened view from Postgres-attached table
      CREATE OR REPLACE TABLE weather_flat AS
      SELECT id, city, url AS source_url, elapsed AS elapsed_sec, payload
      FROM pg_db.public.weather_http_raw
      WHERE execution_id = '{{ execution_id }}';

      -- Aggregate by city (simple count)
      CREATE OR REPLACE TABLE weather_agg AS
      SELECT city, COUNT(*) AS rows_per_city
      FROM weather_flat
      GROUP BY city;

      -- Write results using the GCS credential
      COPY weather_flat TO 'gs://{{ workload.gcs_bucket }}/weather/flat_{{ execution_id }}.parquet' (FORMAT PARQUET);
      COPY weather_agg  TO 'gs://{{ workload.gcs_bucket }}/weather/agg_{{ execution_id }}.parquet'  (FORMAT PARQUET);

      -- Excel workbook now stored in GCS alongside parquet outputs
      COPY (
        SELECT city, source_url, elapsed_sec
        FROM weather_flat
        ORDER BY city
      ) TO 'gs://{{ workload.gcs_bucket }}/weather/weather_{{ execution_id }}.xlsx' (FORMAT 'xlsx', SHEET 'Flat');

      COPY (
        SELECT city, rows_per_city
        FROM weather_agg
        ORDER BY city
      ) TO 'gs://{{ workload.gcs_bucket }}/weather/weather_{{ execution_id }}.xlsx' (FORMAT 'xlsx', SHEET 'Aggregates', WRITE_MODE 'overwrite_sheet');
    next:
      - step: ensure_metrics_table
  - step: ensure_metrics_table
    desc: Ensure metrics table exists in Postgres
    tool: postgres
    auth: "{{ workload.pg_auth }}"
    command: |
      CREATE TABLE IF NOT EXISTS public.weather_pipeline_metrics (
        execution_id TEXT PRIMARY KEY,
        pg_rows_saved INTEGER,
        gcs_flat_uri TEXT,
        gcs_agg_uri  TEXT,
        created_at   TIMESTAMPTZ DEFAULT now()
      );
    next:
      - step: end

  - step: end
    desc: Finish
    tool: postgres
    auth: "{{ workload.pg_auth }}"
    command: |
      INSERT INTO public.weather_pipeline_metrics (execution_id, pg_rows_saved, gcs_flat_uri, gcs_agg_uri)
      VALUES (
        '{{ execution_id }}',
        (SELECT COUNT(*) FROM public.weather_http_raw WHERE execution_id = '{{ execution_id }}'),
        'gs://{{ workload.gcs_bucket }}/weather/flat_{{ execution_id }}.parquet',
        'gs://{{ workload.gcs_bucket }}/weather/agg_{{ execution_id }}.parquet'
      )
      ON CONFLICT (execution_id) DO UPDATE SET
        pg_rows_saved = EXCLUDED.pg_rows_saved,
        gcs_flat_uri = EXCLUDED.gcs_flat_uri,
        gcs_agg_uri = EXCLUDED.gcs_agg_uri
```
