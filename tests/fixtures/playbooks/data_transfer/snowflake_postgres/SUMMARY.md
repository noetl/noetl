# Snowflake ↔ PostgreSQL Transfer - Test Summary

## Overview

This test validates the bidirectional data transfer capability between Snowflake and PostgreSQL using NoETL's generic `transfer` tool. It demonstrates enterprise-grade ETL patterns for moving data between cloud data warehouse and operational database.

**Status**: ✅ **WORKING** - All transfers completed successfully as of 2025-11-08

## Test Purpose

Validates the following patterns:
1. **Snowflake → PostgreSQL**: Data warehouse to operational database
2. **PostgreSQL → Snowflake**: Operational database to data warehouse
3. **Generic Transfer Tool**: Unified source/target configuration
4. **Custom Queries**: UPSERT and MERGE for conflict resolution
5. **Chunked Processing**: Large dataset handling with batch operations

## Configuration Requirements

### Critical: Use `type:` not `tool:` in Transfer Config

**CORRECT Configuration**:
```yaml
tool: transfer
source:
  type: snowflake      # Use 'type:', not 'tool:'
  auth:
    source: credential
    tool: snowflake    # 'tool:' is OK here (for auth lookup)
    key: "sf_test"
  query: "SELECT * FROM table"
target:
  type: postgres       # Use 'type:', not 'tool:'
  auth:
    source: credential
    tool: postgres     # 'tool:' is OK here (for auth lookup)
    key: "pg_local"
  query: "INSERT INTO table ..."
```

**INCORRECT Configuration** (will fail with "source.type is required"):
```yaml
tool: transfer
source:
  tool: snowflake      # ❌ Wrong! Use 'type:' instead
  auth: {...}
target:
  tool: postgres       # ❌ Wrong! Use 'type:' instead
  auth: {...}
```

### Why This Matters

The `transfer` executor validates configuration by checking `source.get('type')` and `target.get('type')`. Using `tool:` instead causes validation error: "source.type is required".

**Code Reference** (`noetl/tools/tools/transfer/executor.py`, line 281):
```python
source_type = source_config.get('type', '').lower()
if not source_type:
    raise ValueError("source.type is required")
```

## Test Structure

### Workflow Steps

1. **create_sf_database**: Initialize Snowflake TEST_DB
2. **setup_pg_table**: Create Postgres target table with JSONB/TIMESTAMPTZ
3. **setup_sf_table**: Create Snowflake source table and insert 5 records
4. **transfer_sf_to_pg**: Transfer with custom UPSERT query
5. **verify_pg_data**: Validate row count and aggregates
6. **setup_pg_source**: Create Postgres source table with 5 different records
7. **setup_sf_target**: Create Snowflake target table
8. **transfer_pg_to_sf**: Transfer with custom MERGE query
9. **verify_sf_data**: Validate row count and aggregates
10. **cleanup**: Drop temporary Postgres tables

### Data Schemas

**Snowflake → Postgres** (TEST_DATA → test_data_transfer):
```sql
-- Source: Snowflake TEST_DATA
id INTEGER, name STRING, value NUMERIC(10,2), 
created_at TIMESTAMP_TZ, metadata VARIANT

-- Target: Postgres public.test_data_transfer
id INTEGER PRIMARY KEY, name TEXT, value NUMERIC(10,2),
created_at TIMESTAMPTZ, metadata JSONB
```

**Postgres → Snowflake** (test_pg_source → PG_IMPORTED_DATA):
```sql
-- Source: Postgres public.test_pg_source
id INTEGER PRIMARY KEY, description TEXT, 
amount NUMERIC(10,2), status TEXT

-- Target: Snowflake PG_IMPORTED_DATA
id INTEGER PRIMARY KEY, description STRING,
amount NUMERIC(10,2), status STRING
```

## Running the Test

### Complete Test Execution

```bash
# Register the playbook
.venv/bin/noetl catalog register \
  tests/fixtures/playbooks/data_transfer/snowflake_postgres/snowflake_postgres.yaml \
  --host localhost --port 8083

# Execute with default credentials
task playbook:local:execute \
  PLAYBOOK=tests/fixtures/playbooks/data_transfer/snowflake_postgres \
  PORT=8083
```

### Custom Credentials

```bash
.venv/bin/noetl execute playbook \
  tests/fixtures/playbooks/data_transfer/snowflake_postgres \
  --host localhost \
  --port 8083 \
  --payload '{"pg_auth": "pg_local", "sf_auth": "sf_test"}' \
  --merge \
  --json
```

## Execution Results

### Successful Test Run (2025-11-08)

**Execution ID**: `490878813291675767`

**Snowflake → Postgres Transfer**:
```json
{
  "row_count": 5,
  "min_id": 1,
  "max_id": 5,
  "total_value": 1502.49
}
```

**Postgres → Snowflake Transfer**:
```json
{
  "ROW_COUNT": 5,
  "MIN_ID": 101,
  "MAX_ID": 105,
  "TOTAL_AMOUNT": 15002.49
}
```

**Event Status**:
```
event_type           | node_id          | status
---------------------+------------------+-----------
execution_completed  | playbook         | COMPLETED
workflow_completed   | workflow         | COMPLETED
action_completed     | cleanup          | COMPLETED
action_completed     | verify_sf_data   | COMPLETED
action_completed     | transfer_pg_to_sf| COMPLETED
action_completed     | setup_sf_target  | COMPLETED
action_completed     | setup_pg_source  | COMPLETED
action_completed     | verify_pg_data   | COMPLETED
action_completed     | transfer_sf_to_pg| COMPLETED
action_completed     | setup_sf_table   | COMPLETED
action_completed     | setup_pg_table   | COMPLETED
action_completed     | create_sf_database| COMPLETED
```

**Performance**:
- Total execution time: ~20 seconds
- Transfer operations: ~2 seconds each
- Network: Snowflake (cloud) ↔ PostgreSQL (localhost)

## Transfer Tool Patterns

### Pattern 1: Auto-Generated INSERT

```yaml
tool: transfer
source:
  type: postgres
  auth: {...}
  query: "SELECT col1, col2 FROM source_table"
target:
  type: postgres
  auth: {...}
  table: schema.target_table    # Auto-generates INSERT statement
chunk_size: 1000
```

### Pattern 2: Custom UPSERT (Postgres)

```yaml
tool: transfer
source:
  type: snowflake
  auth: {...}
  query: "SELECT id, name, value FROM source"
target:
  type: postgres
  auth: {...}
  query: |
    INSERT INTO target (id, name, value) VALUES (%s, %s, %s)
    ON CONFLICT (id) DO UPDATE SET
      name = EXCLUDED.name,
      value = EXCLUDED.value
```

### Pattern 3: Custom MERGE (Snowflake)

```yaml
tool: transfer
source:
  type: postgres
  auth: {...}
  query: "SELECT id, description, amount FROM source"
target:
  type: snowflake
  auth: {...}
  query: |
    MERGE INTO target
    USING (SELECT %s AS id, %s AS description, %s AS amount) AS source
    ON target.id = source.id
    WHEN MATCHED THEN UPDATE SET
      description = source.description,
      amount = source.amount
    WHEN NOT MATCHED THEN INSERT
      (id, description, amount)
      VALUES (source.id, source.description, source.amount)
```

## Data Type Mappings

The transfer tool automatically handles type conversions:

| Snowflake Type | PostgreSQL Type | Notes |
|----------------|-----------------|-------|
| STRING | TEXT | Direct conversion |
| INTEGER | INTEGER | Direct conversion |
| NUMERIC(p,s) | NUMERIC(p,s) | Precision preserved |
| TIMESTAMP_TZ | TIMESTAMPTZ | Timezone aware |
| VARIANT | JSONB | JSON structure preserved |
| BOOLEAN | BOOLEAN | Direct conversion |
| FLOAT | DOUBLE PRECISION | Floating point |

## Authentication Configuration

### Credential-Based (Recommended)

```yaml
auth:
  source: credential
  tool: postgres         # Plugin type for credential lookup
  key: pg_local          # Credential name registered with NoETL
```

**Credential Structure** (`tests/fixtures/credentials/sf_test.json`):
```json
{
  "name": "sf_test",
  "type": "snowflake",
  "data": {
    "sf_account": "ACCOUNT-ID",
    "sf_user": "USERNAME",
    "sf_password": "PASSWORD",
    "sf_warehouse": "WAREHOUSE_NAME",
    "sf_database": "DATABASE",
    "sf_schema": "SCHEMA",
    "sf_role": "ROLE"
  }
}
```

## Troubleshooting

### Issue 1: "source.type is required"

**Error**:
```
ValueError: Transfer failed: source.type is required
```

**Cause**: Using `tool:` instead of `type:` in source/target configuration

**Fix**: Change source/target `tool:` to `type:`
```yaml
# Before (incorrect)
source:
  tool: snowflake

# After (correct)
source:
  type: snowflake
```

### Issue 2: Snowflake Connection Timeout

**Error**:
```
OperationalError: Could not connect to Snowflake
```

**Checks**:
1. Verify warehouse is running (not suspended)
2. Check network connectivity to Snowflake
3. Validate credentials in `sf_test.json`
4. Test with `snowsql`: `snowsql -a <account> -u <user>`

### Issue 3: Query Syntax Errors

**Postgres UPSERT**:
- Use `ON CONFLICT (column) DO UPDATE SET ...`
- Placeholders: `%s`
- Reference excluded values: `EXCLUDED.column`

**Snowflake MERGE**:
- Use `MERGE INTO target USING source ON condition`
- Placeholders: `%s`
- Require both MATCHED and NOT MATCHED clauses

### Issue 4: Data Type Conversion Errors

**Common Issues**:
- JSON fields: Ensure source data is valid JSON for VARIANT/JSONB
- Timestamps: Both systems handle timezones, but format may differ
- Decimals: Precision loss if target has lower precision

**Solution**: Cast values in source query:
```sql
-- Snowflake to Postgres
SELECT 
  id,
  name::STRING as name,
  TO_CHAR(created_at, 'YYYY-MM-DD HH24:MI:SS') as created_at,
  TO_JSON(metadata) as metadata
FROM source_table
```

## Key Learnings

### Configuration Syntax

1. **Transfer Tool Level**: Use `tool: transfer`
2. **Source/Target Level**: Use `type:` (not `tool:`) to specify system type
3. **Auth Level**: Use `tool:` for credential lookup (maps to plugin type)

### Query Patterns

1. **Source Query**: Standard SELECT with column selection
2. **Target Query**: INSERT/UPSERT/MERGE with `%s` placeholders
3. **Column Order**: Placeholders must match source SELECT column order
4. **Idempotency**: Use UPSERT/MERGE for replayability

### Performance

1. **Chunk Size**: Balance between memory usage and network overhead
2. **Network**: Cloud transfers have latency; use appropriate chunk sizes
3. **Transactions**: Each chunk is a transaction; tune for your use case
4. **Parallelism**: Current implementation is sequential per execution

## Success Criteria

All criteria met:

- ✅ Snowflake database and tables created
- ✅ PostgreSQL tables created with correct schema
- ✅ 5 records transferred from Snowflake to Postgres
- ✅ 5 records transferred from Postgres to Snowflake
- ✅ Data type conversions handled correctly (TIMESTAMP_TZ → TIMESTAMPTZ, VARIANT → JSONB)
- ✅ UPSERT query executed successfully (Postgres)
- ✅ MERGE query executed successfully (Snowflake)
- ✅ Verification queries return correct aggregates
- ✅ Cleanup completed (temporary tables dropped)
- ✅ No errors in event log
- ✅ Execution status: COMPLETED

## Files

### Test Playbook
- **`tests/fixtures/playbooks/data_transfer/snowflake_postgres/snowflake_postgres.yaml`**
  - Complete bidirectional transfer workflow
  - Uses `type:` in source/target configuration (fixed from initial `tool:`)
  - Custom UPSERT/MERGE queries for conflict resolution

### Documentation
- **`tests/fixtures/playbooks/data_transfer/snowflake_postgres/README.md`**
  - Detailed usage guide
  - Configuration examples
  - Troubleshooting section

- **`tests/fixtures/playbooks/data_transfer/snowflake_postgres/SUMMARY.md`** (this file)
  - Test summary and results
  - Key learnings and patterns

### Related Files
- **`noetl/tools/tools/transfer/executor.py`**
  - Transfer tool implementation
  - Direction detection logic
  - Type validation and routing

- **`noetl/tools/tools/snowflake/transfer.py`**
  - Snowflake-specific transfer functions
  - Type conversion and connection handling

- **`tests/fixtures/credentials/sf_test.json`**
  - Snowflake credential configuration
  - Not committed to repo (use local copy)

## Next Steps

### Potential Enhancements

1. **Parallel Transfers**: Process multiple chunks concurrently
2. **Incremental Loads**: Support for WHERE clause with max_timestamp pattern
3. **Error Recovery**: Resume from last successful chunk
4. **Schema Inference**: Auto-detect target schema from source
5. **Data Validation**: Pre/post transfer data quality checks
6. **More Directions**: Add support for other database pairs

### Related Tests to Create

1. **Large Dataset**: Test with 100k+ rows to validate chunking
2. **Schema Evolution**: Handle column additions/removals
3. **Null Handling**: Validate NULL value transfers
4. **Error Scenarios**: Network failures, connection drops
5. **Performance Benchmarks**: Measure throughput for different chunk sizes
