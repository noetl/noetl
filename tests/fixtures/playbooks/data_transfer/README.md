# Data Transfer Test Playbooks

This directory contains test playbooks for the generic `transfer` action type, which provides a unified interface for transferring data between different database systems.

## Overview

The `transfer` action type is a modernized, extensible approach to data movement that:
- **Infers direction** from source/target types (no explicit `direction` parameter needed)
- **Simplifies authentication** - each endpoint has its own auth config
- **Supports custom queries** - use `target.query` for custom INSERT/UPSERT/MERGE statements
- **Is extensible** - easily add new source/target combinations

## Key Improvements Over `snowflake_transfer`

| Feature | `snowflake_transfer` | `transfer` (NEW) |
|---------|---------------------|------------------|
| Direction | Explicit `direction: sf_to_pg` | Inferred from `source.type` → `target.type` |
| Auth Config | Complex auth map with aliases | Simple `source.auth` and `target.auth` |
| Extensibility | Snowflake-specific | Generic, easy to add new systems |
| Configuration | More verbose | Cleaner, more intuitive |

## Configuration Pattern

```yaml
- step: transfer_data
  type: transfer
  source:
    type: snowflake|postgres|...
    auth:
      source: credential
      type: snowflake
      key: "credential_name"
    query: "SELECT * FROM source_table"
  target:
    type: postgres|snowflake|...
    auth:
      source: credential
      type: postgres
      key: "credential_name"
    table: "target_table"  # OR
    query: "INSERT INTO target_table ..."  # Custom query
  chunk_size: 1000
```

## Test Playbooks

### snowflake_postgres.yaml

Complete bidirectional transfer test between Snowflake and PostgreSQL:

**Features Tested:**
- Snowflake → PostgreSQL transfer with custom UPSERT query
- PostgreSQL → Snowflake transfer with custom MERGE query
- Table setup and data validation
- Cleanup operations

**Usage:**
```bash
# Register playbook
curl -X POST http://localhost:8083/api/catalog/register \
  -H "Content-Type: application/json" \
  -d "{\"content\": $(cat tests/fixtures/playbooks/data_transfer/snowflake_postgres.yaml | jq -Rs .)}"

# Execute playbook
curl -X POST http://localhost:8083/api/execute \
  -H "Content-Type: application/json" \
  -d '{"path": "tests/fixtures/playbooks/data_transfer/snowflake_postgres"}'
```

## Supported Transfer Combinations

Currently supported:
- ✅ Snowflake → PostgreSQL
- ✅ PostgreSQL → Snowflake

Future additions (easy to add):
- BigQuery → PostgreSQL
- PostgreSQL → BigQuery
- Redshift → PostgreSQL
- MySQL → PostgreSQL
- etc.

## Adding New Data Sources

To add a new data source (e.g., MySQL):

1. **Add connection logic** in `noetl/plugin/transfer/executor.py`:
   ```python
   SUPPORTED_TYPES = {'snowflake', 'postgres', 'mysql'}
   
   def _create_connection(self, db_type: str, auth_data: Dict[str, Any]):
       elif db_type == 'mysql':
           import mysql.connector
           return mysql.connector.connect(...)
   ```

2. **Add transfer function** (if needed):
   ```python
   def transfer_mysql_to_postgres(...):
       # Implementation
   ```

3. **Register in TRANSFER_FUNCTIONS**:
   ```python
   TRANSFER_FUNCTIONS = {
       ('mysql', 'postgres'): transfer_mysql_to_postgres,
       # ... other combinations
   }
   ```

4. **Test** with a new playbook in this directory

## Architecture

The `transfer` action type uses a plugin architecture:

```
noetl/plugin/transfer/
├── __init__.py           # Package exports
└── executor.py           # TransferExecutor class
    ├── execute()         # Main execution logic
    ├── _resolve_auth()   # Auth resolution
    ├── _create_connection()  # DB connections
    └── _close_connection()   # Cleanup
```

**Key Components:**
- `SUPPORTED_TYPES`: Set of supported database types
- `TRANSFER_FUNCTIONS`: Registry mapping (source, target) → transfer function
- Reuses existing transfer functions from `noetl/plugin/snowflake/transfer.py`

## Comparison Example

### Old Way (`snowflake_transfer`)
```yaml
- step: transfer
  type: snowflake_transfer
  direction: sf_to_pg
  source:
    query: "SELECT * FROM source"
  target:
    table: "target"
  chunk_size: 1000
  auth:
    sf:
      source: credential
      type: snowflake
      key: "sf_cred"
    pg:
      source: credential
      type: postgres
      key: "pg_cred"
```

### New Way (`transfer`)
```yaml
- step: transfer
  type: transfer
  source:
    type: snowflake
    auth:
      source: credential
      type: snowflake
      key: "sf_cred"
    query: "SELECT * FROM source"
  target:
    type: postgres
    auth:
      source: credential
      type: postgres
      key: "pg_cred"
    table: "target"
  chunk_size: 1000
```

## Benefits

1. **More Intuitive**: Source and target are self-contained
2. **Less Configuration**: No auth mapping needed
3. **Extensible**: Easy to add new database types
4. **Maintainable**: Clear separation of concerns
5. **Future-Proof**: Can support any source/target combination

## Running Tests

```bash
# Start server and worker
task noetl:local:reset

# Execute test playbook
curl -X POST http://localhost:8083/api/execute \
  -H "Content-Type: application/json" \
  -d '{"path": "tests/fixtures/playbooks/data_transfer/snowflake_postgres"}'

# Check execution status
curl http://localhost:8083/api/executions/{execution_id} | jq '.status'
```

## References

- **Transfer Executor**: `noetl/plugin/transfer/executor.py`
- **Transfer Functions**: `noetl/plugin/snowflake/transfer.py`
- **Tool Dispatcher**: `noetl/plugin/tool/execution.py`
- **Legacy Implementation**: `noetl/plugin/snowflake_transfer/`
