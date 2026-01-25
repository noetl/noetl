# Snowflake Tool

Execute SQL queries against Snowflake Data Warehouse using the Snowflake SQL REST API.

## Overview

The Snowflake tool provides native SQL execution against Snowflake, supporting:
- Password-based authentication
- Multiple SQL statements in a single execution
- Base64-encoded commands for complex queries
- Automatic warehouse, database, schema, and role configuration

## Configuration

### Basic Configuration

```yaml
tool:
  kind: snowflake
  account: "myaccount.us-east-1"
  user: "{{ secrets.SNOWFLAKE_USER }}"
  password: "{{ secrets.SNOWFLAKE_PASSWORD }}"
  warehouse: "COMPUTE_WH"
  database: "MY_DATABASE"
  schema: "PUBLIC"
  command: "SELECT * FROM users LIMIT 10"
```

### Configuration Options

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `account` | string | Yes | - | Snowflake account identifier (e.g., `myaccount` or `myaccount.us-east-1`) |
| `user` | string | Yes | - | Snowflake username |
| `password` | string | Yes | - | Snowflake password |
| `warehouse` | string | No | `COMPUTE_WH` | Warehouse name |
| `database` | string | No | - | Database name |
| `schema` | string | No | `PUBLIC` | Schema name |
| `role` | string | No | - | User role to assume |
| `command` | string | No* | - | Single SQL command |
| `commands` | array | No* | - | Multiple SQL commands |
| `command_b64` | string | No* | - | Base64-encoded SQL command(s) |

*One of `command`, `commands`, or `command_b64` is required.

## Examples

### Single Query

```yaml
workflow:
  - step: query_users
    tool:
      kind: snowflake
      account: "{{ vars.SNOWFLAKE_ACCOUNT }}"
      user: "{{ secrets.SNOWFLAKE_USER }}"
      password: "{{ secrets.SNOWFLAKE_PASSWORD }}"
      warehouse: "ANALYTICS_WH"
      database: "PRODUCTION"
      schema: "PUBLIC"
      command: |
        SELECT
          user_id,
          email,
          created_at
        FROM users
        WHERE created_at > DATEADD(day, -7, CURRENT_DATE())
        ORDER BY created_at DESC
        LIMIT 100
```

### Multiple Commands

```yaml
workflow:
  - step: setup_and_query
    tool:
      kind: snowflake
      account: "{{ vars.SNOWFLAKE_ACCOUNT }}"
      user: "{{ secrets.SNOWFLAKE_USER }}"
      password: "{{ secrets.SNOWFLAKE_PASSWORD }}"
      warehouse: "ETL_WH"
      database: "STAGING"
      commands:
        - "CREATE TEMPORARY TABLE temp_results AS SELECT * FROM source_table WHERE date = CURRENT_DATE()"
        - "SELECT COUNT(*) as total FROM temp_results"
        - "SELECT category, SUM(amount) as total_amount FROM temp_results GROUP BY category"
```

### Base64-Encoded Commands

Useful for complex queries with special characters:

```yaml
workflow:
  - step: complex_query
    tool:
      kind: snowflake
      account: "{{ vars.SNOWFLAKE_ACCOUNT }}"
      user: "{{ secrets.SNOWFLAKE_USER }}"
      password: "{{ secrets.SNOWFLAKE_PASSWORD }}"
      warehouse: "COMPUTE_WH"
      # Base64 encoded: "SELECT * FROM table; SELECT COUNT(*) FROM table"
      command_b64: "U0VMRUNUICogRlJPTSB0YWJsZTsgU0VMRUNUIENPVU5UKCopIEZST00gdGFibGU="
```

### With Role

```yaml
workflow:
  - step: admin_query
    tool:
      kind: snowflake
      account: "myaccount"
      user: "admin_user"
      password: "{{ secrets.ADMIN_PASSWORD }}"
      warehouse: "ADMIN_WH"
      database: "ADMIN_DB"
      schema: "METADATA"
      role: "ACCOUNTADMIN"
      command: "SHOW WAREHOUSES"
```

## Response Format

### Successful Execution

```json
{
  "status": "success",
  "data": {
    "statement_0": {
      "status": "success",
      "row_count": 5,
      "columns": ["user_id", "email", "created_at"],
      "result": [
        {"user_id": "1", "email": "user1@example.com", "created_at": "2024-01-15"},
        {"user_id": "2", "email": "user2@example.com", "created_at": "2024-01-14"}
      ]
    }
  },
  "duration_ms": 1523
}
```

### Multiple Statements

```json
{
  "status": "success",
  "data": {
    "statement_0": {
      "status": "success",
      "row_count": 0,
      "result": null
    },
    "statement_1": {
      "status": "success",
      "row_count": 1,
      "columns": ["total"],
      "result": [{"total": "1000"}]
    }
  },
  "duration_ms": 2341
}
```

### Error Response

```json
{
  "status": "error",
  "error": "Some statements failed",
  "data": {
    "statement_0": {
      "status": "error",
      "row_count": 0,
      "error": "SQL compilation error: Table 'UNKNOWN_TABLE' does not exist"
    }
  },
  "duration_ms": 234
}
```

## Best Practices

1. **Use Secrets for Credentials**: Never hardcode passwords in playbooks
2. **Specify Warehouse Size**: Choose appropriate warehouse for query complexity
3. **Use Roles**: Apply least-privilege principle with specific roles
4. **Batch Operations**: Use multiple commands for related operations
5. **Handle Errors**: Check `status` field for each statement in response

## Limitations

- Currently supports password authentication only (key-pair auth planned)
- Session timeout is 60 seconds per statement
- Results are limited by Snowflake's API response size limits

## See Also

- [Transfer Tool](./transfer.md) - Transfer data from Snowflake to other databases
- [PostgreSQL Tool](./postgres) - Similar SQL execution for PostgreSQL
