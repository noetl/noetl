---
sidebar_position: 2
title: PostgreSQL Tool
description: Execute SQL queries against PostgreSQL databases
---

# PostgreSQL Tool

The PostgreSQL tool executes SQL statements against PostgreSQL databases with support for connection pooling, authentication, and result processing.

## Basic Usage

```yaml
- step: query_users
  tool: postgres
  auth:
    type: postgres
    credential: my_pg_creds
  query: "SELECT * FROM users WHERE status = 'active'"
  next:
    - step: process_results
```

## Configuration

### Authentication

The PostgreSQL tool uses the unified authentication system:

```yaml
- step: query_db
  tool: postgres
  auth:
    type: postgres
    credential: production_db
  query: "SELECT count(*) FROM orders"
```

### Connection Parameters

When credentials are resolved, these connection parameters are available:

| Parameter | Description |
|-----------|-------------|
| `db_host` | Database hostname |
| `db_port` | Database port (default: 5432) |
| `db_user` | Database username |
| `db_password` | Database password |
| `db_name` | Database name |
| `db_conn_string` | Full connection string (overrides individual params) |

### SQL Commands

SQL commands can be provided in multiple ways:

#### Inline Query

```yaml
- step: simple_query
  tool: postgres
  auth: { type: postgres, credential: my_db }
  query: "SELECT * FROM users LIMIT 10"
```

#### Base64 Encoded Commands

```yaml
- step: encoded_query
  tool: postgres
  auth: { type: postgres, credential: my_db }
  command_b64: "U0VMRUNUICogRlJPTSB1c2VycyBMSU1JVCAxMDs="
```

#### Multiple Commands

```yaml
- step: multi_command
  tool: postgres
  auth: { type: postgres, credential: my_db }
  commands_b64: |
    U0VMRUNUICogRlJPTSB1c2VyczsKU0VMRUNUICogRlJPTSBvcmRlcnM7
```

#### External Script

Load SQL from external sources (GCS, S3, HTTP, file):

```yaml
- step: migration
  tool: postgres
  auth: { type: postgres, credential: my_db }
  script:
    uri: gs://sql-scripts/migrations/v2.sql
    source:
      type: gcs
      auth: gcp_service_account
```

## Connection Pooling

Configure connection pooling for high-throughput scenarios:

```yaml
- step: bulk_query
  tool: postgres
  auth: { type: postgres, credential: my_db }
  pool:
    min_size: 5
    max_size: 20
    timeout: 30
  query: "SELECT * FROM large_table"
```

### Pool Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `min_size` | int | 1 | Minimum pool connections |
| `max_size` | int | 10 | Maximum pool connections |
| `timeout` | int | 30 | Connection timeout (seconds) |

## Template Variables

Use Jinja2 templates in your SQL:

```yaml
- step: filtered_query
  tool: postgres
  auth: { type: postgres, credential: my_db }
  query: |
    SELECT * FROM orders 
    WHERE customer_id = '{{ workload.customer_id }}'
    AND created_at >= '{{ vars.start_date }}'
```

### Keychain Access

Access keychain secrets in queries:

```yaml
- step: secure_query
  tool: postgres
  auth: { type: postgres, credential: my_db }
  query: |
    SELECT * FROM api_logs 
    WHERE api_key = '{{ keychain.api_key }}'
```

## Response Format

The PostgreSQL tool returns a standardized response:

```json
{
  "id": "task-uuid",
  "status": "success",
  "data": {
    "command_1": [
      {"id": 1, "name": "Alice"},
      {"id": 2, "name": "Bob"}
    ]
  }
}
```

### Accessing Results

```yaml
- step: get_users
  tool: postgres
  auth: { type: postgres, credential: my_db }
  query: "SELECT id, name FROM users"
  vars:
    first_user: "{{ result.data.command_1[0] }}"
    total_users: "{{ result.data.command_1 | length }}"
  next:
    - step: process_users
      args:
        users: "{{ get_users.data.command_1 }}"
```

## Examples

### Simple SELECT Query

```yaml
- step: get_active_users
  tool: postgres
  auth:
    type: postgres
    credential: app_database
  query: |
    SELECT id, email, created_at 
    FROM users 
    WHERE status = 'active' 
    ORDER BY created_at DESC 
    LIMIT 100
```

### INSERT with Returning

```yaml
- step: create_record
  tool: postgres
  auth:
    type: postgres
    credential: app_database
  query: |
    INSERT INTO audit_logs (action, user_id, details)
    VALUES ('{{ workload.action }}', {{ workload.user_id }}, '{{ workload.details | tojson }}')
    RETURNING id, created_at
  vars:
    log_id: "{{ result.data.command_1[0].id }}"
```

### Transaction with Multiple Statements

```yaml
- step: batch_update
  tool: postgres
  auth:
    type: postgres
    credential: app_database
  command_b64: |
    # Base64 encoded:
    # BEGIN;
    # UPDATE orders SET status = 'processed' WHERE id = ANY($1);
    # INSERT INTO order_history SELECT * FROM orders WHERE id = ANY($1);
    # COMMIT;
```

### ETL Pipeline Step

```yaml
- step: extract_data
  tool: postgres
  auth:
    type: postgres
    credential: source_db
  query: |
    SELECT 
      id,
      customer_name,
      order_date,
      total_amount
    FROM orders
    WHERE order_date >= '{{ workload.start_date }}'
    AND order_date < '{{ workload.end_date }}'
  vars:
    extracted_rows: "{{ result.data.command_1 }}"
  next:
    - step: transform_data
```

### Dynamic Schema Query

```yaml
- step: get_table_info
  tool: postgres
  auth:
    type: postgres
    credential: app_database
  query: |
    SELECT column_name, data_type, is_nullable
    FROM information_schema.columns
    WHERE table_name = '{{ workload.table_name }}'
    ORDER BY ordinal_position
```

## Error Handling

The tool captures SQL errors and returns them in the response:

```json
{
  "id": "task-uuid",
  "status": "error",
  "error": "relation \"nonexistent_table\" does not exist",
  "data": {}
}
```

Use conditional routing to handle errors:

```yaml
- step: risky_query
  tool: postgres
  auth: { type: postgres, credential: my_db }
  query: "SELECT * FROM {{ workload.table_name }}"
  next:
    - when: "{{ risky_query.status == 'error' }}"
      then:
        - step: handle_error
    - step: process_success
```

## Best Practices

1. **Use parameterized queries**: Avoid SQL injection by using template variables carefully
2. **Connection pooling**: Enable for high-frequency queries
3. **Transaction management**: Group related statements in transactions
4. **Error handling**: Always check status in conditional routing
5. **Credential security**: Store credentials in keychain, never in playbooks

## See Also

- [DuckDB Tool](/docs/reference/tools/duckdb) - For analytics workloads
- [Snowflake Tool](/docs/reference/tools/snowflake) - For data warehouse queries
- [Authentication Reference](/docs/reference/auth_and_keychain_reference)
