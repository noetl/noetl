# Snowflake ↔ PostgreSQL Bidirectional Transfer Test

## Overview

This test playbook validates bidirectional data transfer between Snowflake and PostgreSQL using the generic `transfer` tool. It demonstrates both directions:
- **Snowflake → PostgreSQL**: Extract data from Snowflake and load into Postgres
- **PostgreSQL → Snowflake**: Extract data from Postgres and load into Snowflake

## Problem Being Tested

**Use Case**: Generic data transfer patterns between cloud data warehouse (Snowflake) and operational database (PostgreSQL).

**Key Features**:
- Unified transfer tool with source/target pattern
- Credential-based authentication for both systems
- Custom UPSERT/MERGE queries for conflict resolution
- Chunked data transfer for large datasets
- Bidirectional transfer validation

## Test Playbook

**Location**: `tests/fixtures/playbooks/data_transfer/snowflake_postgres/snowflake_postgres.yaml`

**Path**: `tests/fixtures/playbooks/data_transfer/snowflake_postgres`

## Test Workflow

### Part 1: Snowflake → PostgreSQL

1. **Create SF Database**: Initialize Snowflake TEST_DB database
2. **Setup PG Table**: Create target table `public.test_data_transfer` with schema
3. **Setup SF Table**: Create source table `TEST_DATA` and insert 5 test records
4. **Transfer SF → PG**: Use `transfer` tool to move data from Snowflake to Postgres
5. **Verify PG Data**: Query row count and aggregate statistics

### Part 2: PostgreSQL → Snowflake

6. **Setup PG Source**: Create source table `public.test_pg_source` with 5 records
7. **Setup SF Target**: Create target table `PG_IMPORTED_DATA` in Snowflake
8. **Transfer PG → SF**: Use `transfer` tool to move data from Postgres to Snowflake
9. **Verify SF Data**: Query row count and aggregate statistics
10. **Cleanup**: Drop temporary Postgres tables

## Key Features Tested

- **Transfer Tool**: Generic `tool: transfer` with source/target configuration
- **Type-Based Routing**: Uses `type:` (not `tool:`) for source/target specification
- **Credential Authentication**: Unified auth structure with `source: credential`
- **Custom Queries**: UPSERT for Postgres, MERGE for Snowflake
- **Chunk Processing**: Configurable `chunk_size` for batch operations
- **Data Type Handling**: Timestamps, JSONB/VARIANT, numeric precision
- **Bidirectional Validation**: Both transfer directions in single playbook

## Running the Test

### Prerequisites

1. NoETL server running on port 8083
2. PostgreSQL accessible with `pg_local` credential
3. Snowflake account accessible with `sf_test` credential
4. Snowflake credentials configured in `tests/fixtures/credentials/sf_test.json`

### Quick Run

```bash
# Register and execute
noetl playbook register tests/fixtures/playbooks/data_transfer/snowflake_postgres

noetl execution create tests/fixtures/playbooks/data_transfer/snowflake_postgres
```

### Step-by-Step

```bash
# 1. Start services (if not running)
noetl run automation/setup/bootstrap.yaml

# 2. Register the playbook
noetl playbook register tests/fixtures/playbooks/data_transfer/snowflake_postgres

# 3. Execute
noetl execute playbook \
  tests/fixtures/playbooks/data_transfer/snowflake_postgres \
  --host localhost \
  --port 8083 \
  --payload '{"pg_auth": "pg_local", "sf_auth": "sf_test"}' \
  --merge \
  --json
```

## Expected Results

### Success Criteria

#### Snowflake → PostgreSQL Transfer

1. **Source Data**: 5 records in Snowflake TEST_DATA table
2. **Target Table**: `public.test_data_transfer` created with schema:
   - `id` INTEGER PRIMARY KEY
   - `name` TEXT
   - `value` NUMERIC(10,2)
   - `created_at` TIMESTAMPTZ
   - `metadata` JSONB

3. **Verification Query Result**:
```json
{
  "row_count": 5,
  "min_id": 1,
  "max_id": 5,
  "total_value": 1502.49
}
```

#### PostgreSQL → Snowflake Transfer

1. **Source Data**: 5 records in Postgres public.test_pg_source table
2. **Target Table**: `PG_IMPORTED_DATA` created with schema:
   - `id` INTEGER PRIMARY KEY
   - `description` STRING
   - `amount` NUMERIC(10,2)
   - `status` STRING

3. **Verification Query Result**:
```json
{
  "ROW_COUNT": 5,
  "MIN_ID": 101,
  "MAX_ID": 105,
  "TOTAL_AMOUNT": 15002.49
}
```

### Validation Queries

#### Check Snowflake → Postgres Transfer

```sql
SELECT 
  COUNT(*) as row_count,
  MIN(id) as min_id,
  MAX(id) as max_id,
  SUM(value) as total_value
FROM public.test_data_transfer;
```

#### Check Postgres → Snowflake Transfer

```sql
-- Run in Snowflake
SELECT 
  COUNT(*) as row_count,
  MIN(id) as min_id,
  MAX(id) as max_id,
  SUM(amount) as total_amount
FROM PG_IMPORTED_DATA;
```

#### Check Execution Events

```bash
PGPASSWORD=demo psql -h localhost -p 54321 -U demo -d demo_noetl -c \
  "SELECT event_type, node_id, status 
   FROM noetl.event 
   WHERE execution_id = '<execution_id>' 
   ORDER BY event_id DESC 
   LIMIT 30;"
```

## Troubleshooting

### Transfer Configuration Error: "source.type is required"

**Symptom**: Transfer step fails with error message about missing `source.type`

**Cause**: The transfer tool expects `type:` not `tool:` in source/target configuration

**Solution**: Use correct configuration:
```yaml
tool: transfer
source:
  type: snowflake    # Use 'type:', not 'tool:'
  auth: {...}
  query: "SELECT ..."
target:
  type: postgres     # Use 'type:', not 'tool:'
  auth: {...}
  query: "INSERT ..."
```

### Snowflake Connection Failures

**Check**:
1. Verify Snowflake credentials in `tests/fixtures/credentials/sf_test.json`
2. Test connectivity: `snowsql -a <account> -u <user>`
3. Check warehouse status: Must be running (not suspended)
4. Verify role permissions: ACCOUNTADMIN or custom role with appropriate grants

### Data Type Mismatches

**Common Issues**:
- **Timestamps**: Snowflake uses `TIMESTAMP_TZ`, Postgres uses `TIMESTAMPTZ`
- **JSON**: Snowflake uses `VARIANT`, Postgres uses `JSONB`
- **Text**: Snowflake uses `STRING`, Postgres uses `TEXT`

**Solution**: Transfer tool handles type conversions automatically

### Custom Query Syntax

**Postgres UPSERT**:
```sql
INSERT INTO table (col1, col2) VALUES (%s, %s)
ON CONFLICT (id) DO UPDATE SET col2 = EXCLUDED.col2
```

**Snowflake MERGE**:
```sql
MERGE INTO target
USING (SELECT %s AS col1, %s AS col2) AS source
ON target.id = source.col1
WHEN MATCHED THEN UPDATE SET col2 = source.col2
WHEN NOT MATCHED THEN INSERT (col1, col2) VALUES (source.col1, source.col2)
```

## Transfer Tool Configuration

### Source/Target Structure

```yaml
tool: transfer
source:
  type: snowflake|postgres|http    # Required: source system type
  auth:                            # Required for database sources
    source: credential
    tool: <type>                   # Tool name for credential lookup
    key: <credential_name>         # Credential key
  query: "SELECT ..."              # Required: SQL query to extract data
target:
  type: postgres|snowflake         # Required: target system type
  auth:                            # Required: authentication config
    source: credential
    tool: <type>
    key: <credential_name>
  query: "INSERT/MERGE ..."        # Optional: custom insert/upsert query
  table: schema.table_name         # Alternative: auto-generate INSERT
chunk_size: 1000                   # Optional: rows per batch (default: 1000)
```

### Authentication Patterns

**Credential-Based**:
```yaml
auth:
  source: credential
  tool: postgres
  key: pg_local    # References credential registered with NoETL
```

**Direct Credentials** (not recommended for production):
```yaml
auth:
  pg_host: localhost
  pg_port: 5432
  pg_user: user
  pg_password: pass
  pg_database: dbname
```

### Query Placeholders

- **Postgres**: Use `%s` for parameter placeholders
- **Snowflake**: Use `%s` for parameter placeholders (converted internally)
- **Order**: Placeholders must match SELECT column order from source query

## Implementation Notes

### Transfer Direction Detection

The transfer executor automatically detects the transfer direction based on source/target types:
- `snowflake` → `postgres`: Calls `transfer_snowflake_to_postgres()`
- `postgres` → `snowflake`: Calls `transfer_postgres_to_snowflake()`
- Other combinations: Extensible for future support

### Data Streaming

- Data is fetched from source in chunks (configurable `chunk_size`)
- Each chunk is inserted/merged into target using batch operations
- Progress is reported via event callbacks
- Memory-efficient for large datasets

### Transaction Handling

- **Source**: READ COMMITTED isolation, read-only transaction
- **Target**: Each chunk is a separate transaction
- **Failure**: Partial data may exist in target; implement idempotent inserts (UPSERT/MERGE)

## Related Tests

- **`http_to_postgres_transfer.yaml`**: HTTP API to PostgreSQL transfer
- **`http_to_databases.yaml`**: HTTP to multiple database types
- **`http_iterator_save_postgres`**: Iterator with per-item save pattern

## References

- **Transfer Tool Documentation**: `docs/tools/transfer.md`
- **Snowflake Plugin**: `noetl/tools/tools/snowflake/`
- **Postgres Plugin**: `noetl/tools/tools/postgres/`
- **Transfer Executor**: `noetl/tools/tools/transfer/executor.py`
- **Credential Management**: `docs/credentials.md`

## Test Results

### Successful Execution (2025-11-08)

**Execution ID**: `490878813291675767`

**Snowflake → Postgres**:
- Rows transferred: 5
- Total value: 1502.49
- Time: ~2 seconds

**Postgres → Snowflake**:
- Rows transferred: 5
- Total amount: 15002.49
- Time: ~2 seconds

**Total Duration**: ~20 seconds (including table setup and cleanup)

**Status**: ✅ COMPLETED - All steps successful
