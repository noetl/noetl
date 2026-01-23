# Transfer Tool

Transfer data between different database systems with support for chunked streaming and various transfer modes.

## Overview

The Transfer tool enables data movement between:
- PostgreSQL ↔ PostgreSQL
- HTTP API → PostgreSQL
- DuckDB ↔ PostgreSQL
- Snowflake → PostgreSQL (planned)
- PostgreSQL → Snowflake (planned)

## Features

- **Chunked Streaming**: Process data in configurable batch sizes
- **Multiple Transfer Modes**: Append, Replace, or Upsert
- **Column Mapping**: Map source columns to target columns
- **JSON Path Extraction**: Extract data from nested HTTP responses

## Configuration

### Basic Structure

```yaml
tool:
  kind: transfer
  source:
    type: <source_type>
    # source-specific config
  target:
    type: <target_type>
    # target-specific config
  chunk_size: 1000
  mode: append
```

### Source Types

| Type | Description |
|------|-------------|
| `postgres` | PostgreSQL database |
| `duckdb` | DuckDB database |
| `http` | HTTP API endpoint |
| `snowflake` | Snowflake Data Warehouse |

### Target Types

| Type | Description |
|------|-------------|
| `postgres` | PostgreSQL database |
| `duckdb` | DuckDB database |
| `snowflake` | Snowflake Data Warehouse |

### Transfer Modes

| Mode | Description |
|------|-------------|
| `append` | Add rows to existing data (default) |
| `replace` | Truncate target table before insert |
| `upsert` | Insert or update based on primary key |

## Examples

### PostgreSQL to PostgreSQL

```yaml
workflow:
  - step: sync_users
    desc: Sync users from source to target database
    tool:
      kind: transfer
      source:
        type: postgres
        connection: "postgres://user:pass@source-db:5432/app"
        query: |
          SELECT id, email, name, created_at
          FROM users
          WHERE updated_at > NOW() - INTERVAL '1 day'
      target:
        type: postgres
        connection: "postgres://user:pass@target-db:5432/warehouse"
        table: users_replica
      chunk_size: 500
      mode: append
```

### HTTP to PostgreSQL

```yaml
workflow:
  - step: import_api_data
    desc: Import data from REST API to PostgreSQL
    tool:
      kind: transfer
      source:
        type: http
        url: "https://api.example.com/v1/products"
        method: GET
        headers:
          Authorization: "Bearer {{ secrets.API_TOKEN }}"
          Accept: "application/json"
        data_path: "data.items"  # Extract from nested response
        query: ""  # Not used for HTTP
      target:
        type: postgres
        connection: "{{ vars.POSTGRES_URL }}"
        table: products
        mapping:
          product_id: "id"
          product_name: "name"
          price_cents: "price"
      chunk_size: 100
      mode: replace
```

### DuckDB to PostgreSQL

```yaml
workflow:
  - step: export_analytics
    desc: Export DuckDB analytics to PostgreSQL
    tool:
      kind: transfer
      source:
        type: duckdb
        connection: "/data/analytics.duckdb"
        query: |
          SELECT
            date,
            category,
            SUM(revenue) as total_revenue,
            COUNT(*) as transaction_count
          FROM transactions
          GROUP BY date, category
      target:
        type: postgres
        connection: "{{ vars.WAREHOUSE_URL }}"
        table: daily_revenue
      mode: replace
```

### PostgreSQL to DuckDB

```yaml
workflow:
  - step: create_local_cache
    desc: Cache PostgreSQL data in local DuckDB
    tool:
      kind: transfer
      source:
        type: postgres
        connection: "{{ vars.POSTGRES_URL }}"
        query: "SELECT * FROM large_table WHERE date >= '2024-01-01'"
      target:
        type: duckdb
        connection: "/tmp/cache.duckdb"
        table: cached_data
      chunk_size: 5000
      mode: replace
```

### With Column Mapping

```yaml
workflow:
  - step: transform_import
    tool:
      kind: transfer
      source:
        type: http
        url: "https://api.vendor.com/customers"
        data_path: "customers"
        query: ""
      target:
        type: postgres
        connection: "{{ vars.POSTGRES_URL }}"
        table: customer_import
        mapping:
          # target_column: source_field
          customer_id: "id"
          full_name: "displayName"
          email_address: "email"
          phone_number: "phone"
          created_timestamp: "createdAt"
      mode: append
```

## Configuration Reference

### Source Configuration

#### PostgreSQL Source

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | `postgres` |
| `connection` | string | Yes | PostgreSQL connection string |
| `query` | string | Yes | SQL query to fetch data |

#### DuckDB Source

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | `duckdb` |
| `connection` | string | No | Path to DuckDB file (in-memory if not specified) |
| `query` | string | Yes | SQL query to fetch data |

#### HTTP Source

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | `http` |
| `url` | string | Yes | HTTP endpoint URL |
| `method` | string | No | HTTP method (default: `GET`) |
| `headers` | map | No | HTTP headers |
| `data_path` | string | No | JSON path to extract data (dot notation) |

### Target Configuration

#### PostgreSQL Target

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | `postgres` |
| `connection` | string | Yes | PostgreSQL connection string |
| `table` | string | Yes | Target table name |
| `mapping` | map | No | Column mapping (target: source) |

#### DuckDB Target

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | `duckdb` |
| `connection` | string | No | Path to DuckDB file |
| `table` | string | Yes | Target table name |

## Response Format

### Successful Transfer

```json
{
  "status": "success",
  "data": {
    "direction": "postgres_to_postgres",
    "source_type": "postgres",
    "target_type": "postgres",
    "mode": "append",
    "rows_transferred": 1523,
    "chunks_processed": 4,
    "target_table": "users_replica",
    "columns": ["id", "email", "name", "created_at"]
  },
  "duration_ms": 3421
}
```

### Empty Result

```json
{
  "status": "success",
  "data": {
    "direction": "http_to_postgres",
    "source_type": "http",
    "target_type": "postgres",
    "mode": "append",
    "rows_transferred": 0,
    "chunks_processed": 0,
    "target_table": "products"
  },
  "duration_ms": 234
}
```

## Data Path Extraction

For HTTP sources, use `data_path` to extract data from nested JSON:

```json
// API Response
{
  "status": "ok",
  "data": {
    "items": [
      {"id": 1, "name": "Product A"},
      {"id": 2, "name": "Product B"}
    ]
  }
}
```

```yaml
source:
  type: http
  url: "https://api.example.com/products"
  data_path: "data.items"  # Extracts the items array
```

## Best Practices

1. **Use Appropriate Chunk Sizes**:
   - Small chunks (100-500) for wide tables or slow networks
   - Large chunks (1000-5000) for narrow tables or fast networks

2. **Handle Failures**:
   - Use `append` mode for incremental loads
   - Use `replace` mode only when full refresh is needed

3. **Monitor Performance**:
   - Check `rows_transferred` and `chunks_processed`
   - Adjust `chunk_size` based on duration

4. **Secure Credentials**:
   - Use secrets for connection strings
   - Never log connection strings with passwords

## Limitations

- Target table must exist before transfer (auto-create planned)
- Upsert mode requires manual conflict resolution setup
- Large transfers may require increased timeouts

## See Also

- [PostgreSQL Tool](./postgres.md) - Direct PostgreSQL queries
- [DuckDB Tool](./duckdb.md) - Local analytics with DuckDB
- [Snowflake Tool](./snowflake.md) - Snowflake queries
