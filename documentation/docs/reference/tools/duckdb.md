---
sidebar_position: 4
title: DuckDB Tool
description: Execute analytics queries with DuckDB
---

# DuckDB Tool

The DuckDB tool executes SQL queries using DuckDB's high-performance analytics engine, with support for cloud storage, database attachments, and data export.

## Basic Usage

```yaml
- step: analyze_data
  tool: duckdb
  query: "SELECT count(*) as total FROM read_parquet('data/*.parquet')"
  next:
    - step: process_results
```

## Configuration

### Query Definition

SQL queries can be provided in multiple ways:

#### Inline Query

```yaml
- step: simple_query
  tool: duckdb
  query: "SELECT * FROM read_csv_auto('data.csv') LIMIT 10"
```

#### Base64 Encoded

```yaml
- step: encoded_query
  tool: duckdb
  command_b64: "U0VMRUNUICogRlJPTSByZWFkX2Nzdiggxxxxxxx"
```

#### External Script

```yaml
- step: analytics
  tool: duckdb
  script:
    uri: gs://analytics/queries/monthly_report.sql
    source:
      type: gcs
      auth: gcp_service_account
```

### Authentication

DuckDB supports unified authentication for cloud storage and database attachments:

#### GCS Access

```yaml
- step: read_gcs
  tool: duckdb
  auth:
    type: gcs
    credential: gcp_hmac_keys
  query: "SELECT * FROM read_parquet('gs://my-bucket/data/*.parquet')"
```

#### S3 Access

```yaml
- step: read_s3
  tool: duckdb
  auth:
    type: s3
    credential: aws_credentials
  query: "SELECT * FROM read_parquet('s3://my-bucket/data/*.parquet')"
```

#### PostgreSQL Attachment

```yaml
- step: query_postgres
  tool: duckdb
  auth:
    type: postgres
    credential: source_db
  query: |
    ATTACH '' AS pg (TYPE POSTGRES);
    SELECT * FROM pg.public.users LIMIT 100;
```

## Cloud Storage Integration

### Reading from GCS

```yaml
- step: analyze_gcs_data
  tool: duckdb
  auth:
    type: gcs
    credential: gcp_service_account
  query: |
    SELECT 
      date_trunc('month', created_at) as month,
      count(*) as count,
      sum(amount) as total
    FROM read_parquet('gs://analytics-bucket/orders/*.parquet')
    GROUP BY 1
    ORDER BY 1
```

### Writing to GCS

```yaml
- step: export_to_gcs
  tool: duckdb
  auth:
    type: gcs
    credential: gcp_service_account
  require_cloud_output: true
  query: |
    COPY (
      SELECT * FROM read_csv_auto('local_data.csv')
      WHERE status = 'active'
    ) TO 'gs://output-bucket/processed/data.parquet' (FORMAT PARQUET);
```

### Reading from S3

```yaml
- step: analyze_s3_data
  tool: duckdb
  auth:
    type: s3
    credential: aws_credentials
  query: |
    SELECT * FROM read_parquet('s3://data-lake/events/*.parquet')
    WHERE event_date >= '2024-01-01'
```

## Database Attachments

### PostgreSQL

```yaml
- step: join_with_postgres
  tool: duckdb
  auth:
    type: postgres
    credential: production_db
  query: |
    ATTACH '' AS pg (TYPE POSTGRES);
    SELECT 
      l.event_type,
      u.email,
      count(*) as event_count
    FROM read_parquet('events.parquet') l
    JOIN pg.public.users u ON l.user_id = u.id
    GROUP BY 1, 2;
```

### MySQL

```yaml
- step: query_mysql
  tool: duckdb
  db_type: mysql
  auth:
    type: mysql
    credential: mysql_db
  query: |
    ATTACH '' AS mysql_db (TYPE MYSQL);
    SELECT * FROM mysql_db.orders;
```

### SQLite

```yaml
- step: query_sqlite
  tool: duckdb
  query: |
    ATTACH 'local_db.sqlite' AS sqlite_db;
    SELECT * FROM sqlite_db.main.data;
```

## File Format Support

DuckDB supports various file formats:

### Parquet

```yaml
- step: read_parquet
  tool: duckdb
  query: |
    SELECT * FROM read_parquet('data/*.parquet')
    WHERE partition_date = '2024-01-01'
```

### CSV

```yaml
- step: read_csv
  tool: duckdb
  query: |
    SELECT * FROM read_csv_auto('data.csv', 
      header=true, 
      delim=',',
      quote='"'
    )
```

### JSON

```yaml
- step: read_json
  tool: duckdb
  query: |
    SELECT * FROM read_json_auto('data/*.json')
```

### Excel (with extension)

```yaml
- step: read_excel
  tool: duckdb
  auto_secrets: true
  query: |
    INSTALL spatial;
    LOAD spatial;
    SELECT * FROM st_read('data.xlsx')
```

## Response Format

```json
{
  "id": "task-uuid",
  "status": "success",
  "data": {
    "command_1": [
      {"column1": "value1", "column2": 123},
      {"column1": "value2", "column2": 456}
    ],
    "task_id": "task-uuid",
    "execution_id": "exec-123",
    "secrets_created": 1,
    "database_path": ":memory:"
  }
}
```

## Examples

### ETL Pipeline

```yaml
- step: extract_transform_load
  tool: duckdb
  auth:
    type: gcs
    credential: gcp_service_account
  query: |
    -- Extract from source
    CREATE TABLE source_data AS 
    SELECT * FROM read_parquet('gs://source-bucket/raw/*.parquet');
    
    -- Transform
    CREATE TABLE transformed AS
    SELECT 
      id,
      upper(name) as name,
      amount * 1.1 as adjusted_amount,
      current_timestamp as processed_at
    FROM source_data
    WHERE status = 'active';
    
    -- Load to destination
    COPY transformed TO 'gs://dest-bucket/processed/data.parquet' (FORMAT PARQUET);
    
    SELECT count(*) as rows_processed FROM transformed;
```

### Data Aggregation

```yaml
- step: aggregate_metrics
  tool: duckdb
  auth:
    type: gcs
    credential: gcp_credentials
  query: |
    SELECT 
      date_trunc('day', event_time) as day,
      event_type,
      count(*) as event_count,
      count(distinct user_id) as unique_users,
      avg(duration_ms) as avg_duration
    FROM read_parquet('gs://events-bucket/2024/*/*.parquet')
    WHERE event_time >= '2024-01-01'
    GROUP BY 1, 2
    ORDER BY 1, 2
```

### Cross-Database Join

```yaml
- step: cross_db_analysis
  tool: duckdb
  auth:
    type: postgres
    credential: analytics_db
  query: |
    ATTACH '' AS pg (TYPE POSTGRES);
    
    WITH cloud_events AS (
      SELECT user_id, count(*) as event_count
      FROM read_parquet('events.parquet')
      GROUP BY user_id
    )
    SELECT 
      u.email,
      u.plan_type,
      ce.event_count
    FROM pg.public.users u
    LEFT JOIN cloud_events ce ON u.id = ce.user_id
    ORDER BY ce.event_count DESC NULLS LAST
```

### Data Quality Check

```yaml
- step: data_quality
  tool: duckdb
  query: |
    SELECT 
      'total_rows' as metric, count(*)::varchar as value
    FROM read_parquet('data.parquet')
    UNION ALL
    SELECT 
      'null_emails', count(*)::varchar
    FROM read_parquet('data.parquet')
    WHERE email IS NULL
    UNION ALL
    SELECT
      'duplicate_ids', count(*)::varchar  
    FROM (
      SELECT id, count(*) as cnt
      FROM read_parquet('data.parquet')
      GROUP BY id
      HAVING count(*) > 1
    )
```

## Configuration Options

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | - | SQL query to execute |
| `command_b64` | string | - | Base64 encoded SQL |
| `auto_secrets` | bool | true | Auto-generate DuckDB secrets from auth |
| `require_cloud_output` | bool | false | Fail if no cloud output in query |
| `db_type` | string | postgres | Database type for attachments |

## Best Practices

1. **Use Parquet format**: More efficient than CSV for analytics
2. **Partition data**: Use partitioned Parquet for better query performance
3. **Limit result sets**: Use LIMIT when exploring large datasets
4. **Use cloud storage**: Prefer GCS/S3 over local files in production
5. **Close attachments**: Clean up database attachments when done

## See Also

- [PostgreSQL Tool](/docs/reference/tools/postgres) - For OLTP workloads
- [DuckLake Tool](/docs/reference/tools/ducklake) - For lakehouse queries
- [Authentication Reference](/docs/reference/auth_and_keychain_reference)
