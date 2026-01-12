---
sidebar_position: 5
title: Snowflake Tool
description: Execute queries and transfer data with Snowflake
---

# Snowflake Tool

The Snowflake tool executes SQL queries against Snowflake data warehouses with support for authentication, data transfers, and result processing.

## Basic Usage

```yaml
- step: query_warehouse
  tool: snowflake
  auth:
    type: snowflake
    credential: snowflake_prod
  query: "SELECT * FROM sales.orders WHERE order_date >= '2024-01-01'"
  next:
    - step: process_results
```

## Configuration

### Authentication

Snowflake supports multiple authentication methods:

#### Password Authentication

```yaml
- step: basic_query
  tool: snowflake
  auth:
    type: snowflake
    credential: snowflake_creds
  query: "SELECT current_user(), current_warehouse()"
```

Credential payload:
```json
{
  "account": "xy12345.us-east-1",
  "user": "my_user",
  "password": "my_password",
  "warehouse": "COMPUTE_WH",
  "database": "MY_DB",
  "schema": "PUBLIC"
}
```

#### Key Pair Authentication

```yaml
- step: keypair_query
  tool: snowflake
  auth:
    type: snowflake
    credential: snowflake_keypair
  query: "SELECT 1"
```

Credential payload:
```json
{
  "account": "xy12345.us-east-1",
  "user": "my_user",
  "private_key": "-----BEGIN PRIVATE KEY-----\n...",
  "private_key_passphrase": "optional_passphrase",
  "warehouse": "COMPUTE_WH",
  "database": "MY_DB"
}
```

### Connection Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `account` | Yes | - | Snowflake account identifier |
| `user` | Yes | - | Username |
| `password` | Conditional | - | Password (or use private_key) |
| `private_key` | Conditional | - | RSA private key (or use password) |
| `warehouse` | No | COMPUTE_WH | Compute warehouse |
| `database` | No | - | Default database |
| `schema` | No | PUBLIC | Default schema |
| `role` | No | - | Snowflake role |
| `authenticator` | No | snowflake | Auth method |

## Query Execution

### Simple Query

```yaml
- step: get_data
  tool: snowflake
  auth:
    type: snowflake
    credential: snowflake_prod
  query: |
    SELECT 
      customer_id,
      order_date,
      total_amount
    FROM sales.orders
    WHERE order_date >= '{{ workload.start_date }}'
    LIMIT 1000
```

### Multiple Statements

```yaml
- step: multi_statement
  tool: snowflake
  auth:
    type: snowflake
    credential: snowflake_prod
  command_b64: |
    # Base64 encoded SQL containing:
    # USE WAREHOUSE compute_wh;
    # CREATE TEMP TABLE staging AS SELECT * FROM source;
    # INSERT INTO target SELECT * FROM staging;
```

### External Script

```yaml
- step: run_report
  tool: snowflake
  auth:
    type: snowflake
    credential: snowflake_prod
  script:
    uri: gs://sql-scripts/reports/monthly_summary.sql
    source:
      type: gcs
      auth: gcp_service_account
```

## Data Transfer

The Snowflake tool supports efficient data transfer between Snowflake and PostgreSQL.

### Snowflake to PostgreSQL

```yaml
- step: transfer_to_postgres
  tool: snowflake_transfer
  direction: snowflake_to_postgres
  source_auth:
    type: snowflake
    credential: snowflake_prod
  dest_auth:
    type: postgres
    credential: postgres_analytics
  source_query: "SELECT * FROM sales.orders WHERE order_date >= '2024-01-01'"
  dest_table: analytics.snowflake_orders
  chunk_size: 10000
  truncate_dest: true
```

### PostgreSQL to Snowflake

```yaml
- step: transfer_to_snowflake
  tool: snowflake_transfer
  direction: postgres_to_snowflake
  source_auth:
    type: postgres
    credential: postgres_prod
  dest_auth:
    type: snowflake
    credential: snowflake_staging
  source_query: "SELECT * FROM events WHERE created_at >= now() - interval '1 day'"
  dest_table: RAW.EVENTS
  chunk_size: 50000
```

### Transfer Configuration

| Parameter | Type | Description |
|-----------|------|-------------|
| `direction` | string | `snowflake_to_postgres` or `postgres_to_snowflake` |
| `source_query` | string | SQL query for source data |
| `dest_table` | string | Destination table name |
| `chunk_size` | int | Rows per chunk (default: 10000) |
| `truncate_dest` | bool | Truncate destination before load |

## Response Format

```json
{
  "id": "task-uuid",
  "status": "success",
  "data": {
    "command_1": [
      {"CUSTOMER_ID": 123, "ORDER_DATE": "2024-01-15", "TOTAL": 99.99}
    ]
  }
}
```

## Examples

### Analytics Query

```yaml
- step: monthly_metrics
  tool: snowflake
  auth:
    type: snowflake
    credential: snowflake_analytics
  query: |
    SELECT 
      DATE_TRUNC('month', order_date) as month,
      COUNT(DISTINCT customer_id) as unique_customers,
      COUNT(*) as total_orders,
      SUM(total_amount) as revenue
    FROM sales.orders
    WHERE order_date >= DATEADD('month', -12, CURRENT_DATE())
    GROUP BY 1
    ORDER BY 1
```

### Data Warehouse Refresh

```yaml
workflow:
  - step: start
    next:
      - step: truncate_staging

  - step: truncate_staging
    tool: snowflake
    auth:
      type: snowflake
      credential: snowflake_etl
    query: "TRUNCATE TABLE staging.daily_events"
    next:
      - step: load_data

  - step: load_data
    tool: snowflake
    auth:
      type: snowflake
      credential: snowflake_etl
    query: |
      COPY INTO staging.daily_events
      FROM @raw_stage/events/
      FILE_FORMAT = (TYPE = 'PARQUET')
      PATTERN = '.*{{ workload.date }}.*'
    next:
      - step: merge_to_prod

  - step: merge_to_prod
    tool: snowflake
    auth:
      type: snowflake
      credential: snowflake_etl
    query: |
      MERGE INTO prod.events t
      USING staging.daily_events s
      ON t.event_id = s.event_id
      WHEN MATCHED THEN UPDATE SET *
      WHEN NOT MATCHED THEN INSERT *
    next:
      - step: end

  - step: end
```

### Cross-Platform ETL

```yaml
workflow:
  - step: start
    next:
      - step: extract_snowflake

  - step: extract_snowflake
    tool: snowflake
    auth:
      type: snowflake
      credential: snowflake_source
    query: |
      SELECT 
        user_id,
        event_type,
        properties,
        timestamp
      FROM raw.events
      WHERE timestamp >= '{{ workload.start_date }}'
      AND timestamp < '{{ workload.end_date }}'
    vars:
      events: "{{ result.data.command_1 }}"
    next:
      - step: transform_data

  - step: transform_data
    tool: python
    code: |
      import json
      def main(events):
          transformed = []
          for event in events:
              props = json.loads(event.get('PROPERTIES', '{}'))
              transformed.append({
                  'user_id': event['USER_ID'],
                  'event_type': event['EVENT_TYPE'],
                  'page_url': props.get('page_url'),
                  'timestamp': event['TIMESTAMP']
              })
          return {'events': transformed}
    args:
      events: "{{ vars.events }}"
    vars:
      transformed_events: "{{ result.data.events }}"
    next:
      - step: load_postgres

  - step: load_postgres
    tool: postgres
    auth:
      type: postgres
      credential: postgres_analytics
    query: |
      INSERT INTO analytics.page_views (user_id, event_type, page_url, event_time)
      SELECT 
        (e->>'user_id')::int,
        e->>'event_type',
        e->>'page_url',
        (e->>'timestamp')::timestamp
      FROM jsonb_array_elements('{{ vars.transformed_events | tojson }}'::jsonb) e
    next:
      - step: end

  - step: end
```

## Error Handling

```yaml
- step: risky_query
  tool: snowflake
  auth:
    type: snowflake
    credential: snowflake_prod
  query: "{{ workload.dynamic_query }}"
  next:
    - when: "{{ risky_query.status == 'error' }}"
      then:
        - step: handle_error
    - step: continue_workflow
```

## Best Practices

1. **Use appropriate warehouse size**: Scale warehouse for query complexity
2. **Leverage clustering**: Cluster large tables on frequently filtered columns
3. **Use Time Travel**: Query historical data when needed
4. **Chunked transfers**: Use appropriate chunk sizes for data transfers
5. **Role-based access**: Use roles with minimal required permissions

## Known Limitations

- MFA/TOTP authentication not supported (use key pair or OAuth)
- Large result sets should use data transfer for efficiency

## See Also

- [PostgreSQL Tool](/docs/reference/tools/postgres) - For OLTP workloads
- [DuckDB Tool](/docs/reference/tools/duckdb) - For local analytics
- [Transfer Tool](/docs/reference/tools/transfer) - For generic data transfers
- [Authentication Reference](/docs/reference/auth_and_keychain_reference)
