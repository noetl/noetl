# Snowflake Transfer Test Playbook

## Overview

This playbook demonstrates **bidirectional data transfer** between **Snowflake** and **PostgreSQL** using the new `snowflake_transfer` action type with chunked streaming support.

## Features Tested

- **New `snowflake_transfer` Action Type**: Dedicated action type for efficient data transfers
- **Unified Auth System**: Uses NoETL's unified authentication with multi-credential support
- **Snowflake to PostgreSQL Transfer**: Stream data from Snowflake tables to PostgreSQL with configurable chunk sizes
- **PostgreSQL to Snowflake Transfer**: Reverse direction transfer with same capabilities
- **Multiple Transfer Modes**: 
  - `append`: Add data to existing table
  - `replace`: Truncate before insert
  - `upsert`: Insert or update based on primary key
- **Custom Target Queries** (NEW): Use `target.query` for custom INSERT/UPSERT statements when not all columns are needed or column names differ
- **Automatic Column Case Conversion**: Snowflake uppercase columns automatically lowercased for PostgreSQL
- **Data Type Mapping**: Automatic conversion (VARIANT ↔ JSONB, TIMESTAMP_TZ ↔ TIMESTAMPTZ)
- **Memory Efficient**: Process large datasets without loading all data into memory
- **Progress Tracking**: Monitor transfer progress through event callbacks
- **Error Handling**: Graceful handling of connection and data transfer errors

## Pipeline Flow

```
START
  ↓
1. Create Snowflake Database (if not exists)
  ↓
2. Setup PostgreSQL Target Table
  ↓
3. Setup Snowflake Source Table (with test data)
  ↓
4. Transfer Snowflake → PostgreSQL (using snowflake_transfer action type)
  ↓
5. Verify PostgreSQL Data
  ↓
6. Setup Snowflake Target Table
  ↓
7. Transfer PostgreSQL → Snowflake (using snowflake_transfer action type)
  ↓
8. Verify Snowflake Data
  ↓
END
```

## Action Types Used

This playbook demonstrates three NoETL action types:

### 1. `snowflake` Action Type
Execute SQL commands against Snowflake (DDL/DML operations):
```yaml
- step: create_sf_database
  type: snowflake
  auth: "{{ workload.sf_auth }}"
  command: |
    CREATE DATABASE IF NOT EXISTS TEST_DB;
    USE DATABASE TEST_DB;
    USE SCHEMA PUBLIC;
```

### 2. `postgres` Action Type
Execute SQL commands against PostgreSQL (DDL/DML operations):
```yaml
- step: setup_pg_table
  type: postgres
  auth: "{{ workload.pg_auth }}"
  command: |
    CREATE TABLE IF NOT EXISTS public.test_snowflake_transfer (
      id INTEGER PRIMARY KEY,
      name TEXT,
      value NUMERIC(10,2),
      created_at TIMESTAMPTZ,
      metadata JSONB
    );
```

### 3. `snowflake_transfer` Action Type (NEW)
Bidirectional data transfer with chunked streaming:
```yaml
- step: transfer_sf_to_pg
  type: snowflake_transfer
  direction: sf_to_pg  # or pg_to_sf
  source:
    query: "SELECT * FROM TEST_DATA ORDER BY id"
  target:
    table: "public.test_snowflake_transfer"
  chunk_size: 1000
  mode: append
  auth:
    sf:
      source: credential
      type: snowflake
      key: "{{ workload.sf_auth }}"
    pg:
      source: credential
      type: postgres
      key: "{{ workload.pg_auth }}"
```

## Prerequisites

### 1. Snowflake Account
- Active Snowflake account with appropriate permissions
- Warehouse created (default: COMPUTE_WH)
- Database created (e.g., TEST_DB)
- User with CREATE TABLE and INSERT permissions

### 2. PostgreSQL Database
- Running PostgreSQL instance (local or remote)
- Database with CREATE TABLE permissions
- User with INSERT/SELECT/DROP permissions

### 3. NoETL Server and Workers
- NoETL server running (port 8082/8083)
- At least one NoETL worker active
- PostgreSQL system database configured

## Configuration

### 1. Update Snowflake Credentials

Edit `tests/fixtures/credentials/sf_test.json`:

```json
{
  "name": "sf_test",
  "type": "snowflake",
  "description": "Test Snowflake connection for NoETL data transfer",
  "tags": ["test", "snowflake", "transfer"],
  "data": {
    "sf_account": "xy12345.us-east-1",
    "sf_user": "your_username",
    "sf_password": "your_password",
    "sf_warehouse": "COMPUTE_WH",
    "sf_database": "TEST_DB",
    "sf_schema": "PUBLIC",
    "sf_role": "SYSADMIN"
  }
}
```

### 2. Register Credentials

The playbook uses NoETL's unified auth system. Register credentials using the NoETL CLI or API:

```bash
# Using NoETL CLI (preferred)
.venv/bin/noetl credential register tests/fixtures/credentials/sf_test.json
.venv/bin/noetl credential register tests/fixtures/credentials/pg_local.json

# Or using cURL
curl -X POST http://localhost:8083/api/credentials \
  -H "Content-Type: application/json" \
  --data-binary @tests/fixtures/credentials/sf_test.json

curl -X POST http://localhost:8083/api/credentials \
  -H "Content-Type: application/json" \
  --data-binary @tests/fixtures/credentials/pg_local.json

# Or using task command
task noetl:local:reset  # This will register all test credentials including sf_test
```

### 3. Environment Setup (Optional)

The playbook uses credential-based authentication through NoETL's unified auth system. 
Environment variables are not required as credentials are retrieved from the NoETL credential store.

However, if you prefer environment-based configuration:

```bash
# Snowflake credentials
export SF_ACCOUNT="NDCFGPC-MI21697"
export SF_USER="your_username"
export SF_PASSWORD="your_password"
export SF_WAREHOUSE="SNOWFLAKE_LEARNING_WH"
export SF_DATABASE="TEST_DB"
export SF_SCHEMA="PUBLIC"

# PostgreSQL credentials
export PG_HOST="localhost"
export PG_PORT="54321"
export PG_USER="demo"
export PG_PASSWORD="demo"
export PG_DATABASE="demo_noetl"
```

## Running the Test

### Quick Start (Recommended)

```bash
# Complete reset and setup (includes credential registration)
task noetl:local:reset

# Execute the playbook
task playbook:local:execute PORT=8083 PLAYBOOK=tests/fixtures/playbooks/snowflake_transfer
```

### Using Task Commands

```bash
# Register playbook manually (optional, already done by reset)
task playbook:local:register PLAYBOOK=tests/fixtures/playbooks/snowflake_transfer/snowflake_transfer.yaml

# Execute playbook
task playbook:local:execute PORT=8083 PLAYBOOK=tests/fixtures/playbooks/snowflake_transfer
```

### Using NoETL CLI

```bash
# Register playbook
.venv/bin/noetl catalog register \
  tests/fixtures/playbooks/snowflake_transfer/snowflake_transfer.yaml \
  --host localhost --port 8083

# Execute playbook
.venv/bin/noetl execute playbook \
  tests/fixtures/playbooks/snowflake_transfer \
  --host localhost --port 8083 \
  --payload '{"pg_auth": "pg_local"}' --merge --json
```

### Using cURL

```bash
# Execute playbook (assuming already registered)
curl -X POST http://localhost:8083/api/executions/run \
  -H "Content-Type: application/json" \
  -d '{
    "path": "tests/fixtures/playbooks/snowflake_transfer",
    "payload": {"pg_auth": "pg_local"},
    "merge": true
  }'
```

## Expected Output

### Successful Execution

The playbook will:

1. **Create Snowflake Database**: Create TEST_DB if it doesn't exist
   - Output: `{status: "TEST_DB already exists, statement succeeded."}`

2. **Create PostgreSQL Table**: Set up target table with lowercase columns
   ```sql
   CREATE TABLE public.test_snowflake_transfer (
     id INTEGER PRIMARY KEY,
     name TEXT,
     value NUMERIC(10,2),
     created_at TIMESTAMPTZ,
     metadata JSONB
   );
   ```

3. **Create Snowflake Table**: Set up source table with test data
   ```sql
   CREATE OR REPLACE TABLE TEST_DATA (
     id INTEGER PRIMARY KEY,
     name STRING,
     value NUMERIC(10,2),
     created_at TIMESTAMP_TZ,
     metadata VARIANT
   );
   ```

4. **Transfer SF → PG**: Move 5 test records with automatic column lowercasing
   - Snowflake columns: `ID`, `NAME`, `VALUE`, `CREATED_AT`, `METADATA`
   - PostgreSQL columns: `id`, `name`, `value`, `created_at`, `metadata`
   - Output: `{rows_transferred: 5, chunks_processed: 1, status: 'success'}`

5. **Verify PG Data**: Query PostgreSQL to confirm data arrival
   ```bash
   PGPASSWORD=demo psql -h localhost -p 54321 -U demo -d demo_noetl \
     -c "SELECT * FROM public.test_snowflake_transfer ORDER BY id;"
   ```
   Expected: 5 rows with proper data types (JSONB, TIMESTAMPTZ)

6. **Transfer PG → SF**: Move 5 test records from PostgreSQL to Snowflake
   - Output: `{rows_transferred: 5, chunks_processed: 1, status: 'success'}`

7. **Verify SF Data**: Query Snowflake to confirm data arrival
   - Output: Verification query result showing 5 rows

### Monitoring Progress

Check execution logs:

```bash
# Server logs
tail -f logs/server.log

# Worker logs
tail -f logs/worker.log

# Query execution events
PGPASSWORD=noetl psql -h localhost -p 54321 -U noetl -d demo_noetl -c \
  "SELECT event_type, node_name, status, created_at 
   FROM noetl.event 
   WHERE execution_id = '<execution_id>' 
   ORDER BY created_at;"
```

## Customization

### Adjust Chunk Size

Modify the `chunk_size` in the playbook workload:

```yaml
workload:
  chunk_size: 5000  # Process 5000 rows per chunk
```

### Change Transfer Mode

Update the transfer steps to use different modes:

```yaml
- step: transfer_with_replace
  type: snowflake_transfer
  direction: sf_to_pg
  source:
    query: "SELECT * FROM TEST_DATA"
  target:
    table: "public.target_table"
  chunk_size: 1000
  mode: replace  # Options: append, replace, upsert
  auth:
    sf:
      source: credential
      type: snowflake
      key: "sf_test"
    pg:
      source: credential
      type: postgres
      key: "pg_local"
```

### Use Upsert Mode

For upsert mode, the first column is treated as the primary key:

```yaml
- step: transfer_with_upsert
  type: snowflake_transfer
  direction: sf_to_pg
  source:
    query: "SELECT id, name, value FROM TEST_DATA"  # id is PK
  target:
    table: "public.target_table"
  mode: upsert  # Will UPDATE existing rows, INSERT new ones
  auth:
    sf:
      source: credential
      type: snowflake
      key: "sf_test"
    pg:
      source: credential
      type: postgres
      key: "pg_local"
```

### Custom Queries

Modify source queries for more complex scenarios:

```yaml
- step: filtered_transfer
  type: snowflake_transfer
  direction: sf_to_pg
  source:
    query: |
      SELECT 
        id,
        UPPER(name) as name,
        value * 1.1 as adjusted_value,
        created_at,
        metadata
      FROM TEST_DATA
      WHERE created_at > CURRENT_DATE - 7
        AND value > 100
      ORDER BY id
  target:
    table: "public.filtered_data"
  chunk_size: 5000
  mode: append
  auth:
    sf:
      source: credential
      type: snowflake
      key: "sf_test"
    pg:
      source: credential
      type: postgres
      key: "pg_local"
```

### Custom Target Queries (NEW)

Use `target.query` instead of `target.table` for custom INSERT/UPSERT logic when:
- Not all columns need to be transferred
- Column names differ between source and target
- Custom transformation or conflict resolution is needed

**Example 1: Partial Column Transfer**
```yaml
- step: partial_column_transfer
  type: snowflake_transfer
  direction: sf_to_pg
  source:
    query: "SELECT id, name, value FROM TEST_DATA"  # Only 3 columns
  target:
    query: |
      INSERT INTO public.target_table (record_id, record_name, amount)
      VALUES (%s, %s, %s)
  chunk_size: 1000
  auth:
    sf:
      source: credential
      type: snowflake
      key: "sf_test"
    pg:
      source: credential
      type: postgres
      key: "pg_local"
```

**Example 2: Custom Upsert with Different Column Names**
```yaml
- step: custom_upsert
  type: snowflake_transfer
  direction: sf_to_pg
  source:
    query: "SELECT id, name, value, updated_at FROM TEST_DATA"
  target:
    query: |
      INSERT INTO public.target_table (record_id, record_name, amount, last_modified)
      VALUES (%s, %s, %s, %s)
      ON CONFLICT (record_id) DO UPDATE SET
        record_name = EXCLUDED.record_name,
        amount = EXCLUDED.amount,
        last_modified = EXCLUDED.last_modified
  chunk_size: 1000
  auth:
    sf:
      source: credential
      type: snowflake
      key: "sf_test"
    pg:
      source: credential
      type: postgres
      key: "pg_local"
```

**Example 3: PostgreSQL to Snowflake with Custom Query**
```yaml
- step: pg_to_sf_custom
  type: snowflake_transfer
  direction: pg_to_sf
  source:
    query: "SELECT id, name, amount, status FROM pg_table"
  target:
    query: |
      MERGE INTO sf_table t
      USING (SELECT %s as id, %s as name, %s as amount, %s as status) s
      ON t.id = s.id
      WHEN MATCHED THEN UPDATE SET
        name = s.name,
        amount = s.amount,
        status = s.status
      WHEN NOT MATCHED THEN INSERT (id, name, amount, status)
        VALUES (s.id, s.name, s.amount, s.status)
  chunk_size: 1000
  auth:
    sf:
      source: credential
      type: snowflake
      key: "sf_test"
    pg:
      source: credential
      type: postgres
      key: "pg_local"
```

**Important Notes:**
- The number of `%s` placeholders in `target.query` must match the number of columns in `source.query`
- When `target.query` is provided, `target.table` is optional
- When `target.query` is provided, `mode` parameter is ignored (custom query controls behavior)
- Use `%s` as placeholder (not `$1`, `$2` etc.) - the plugin handles parameter binding

## Troubleshooting

### Connection Issues

**Snowflake Connection Failed**:
- Verify account identifier (e.g., `NDCFGPC-MI21697`)
- Check username and password in `sf_test.json` credential
- Confirm warehouse is running (`SNOWFLAKE_LEARNING_WH`)
- Validate network access to Snowflake
- Check credential registration: `curl http://localhost:8083/api/credentials/sf_test`

**PostgreSQL Connection Failed**:
- Check host and port accessibility (default: `localhost:54321`)
- Verify credentials in `pg_local.json`
- Confirm database exists (`demo_noetl`)
- Check firewall rules
- Test connection: `PGPASSWORD=demo psql -h localhost -p 54321 -U demo -d demo_noetl`

### Auth Resolution Issues

**"auth configuration is required" error**:
- Verify auth block is properly formatted in playbook step
- Check both `sf` and `pg` credentials are defined
- Ensure credential keys match registered credentials

**"Snowflake credential 'sf' not found" error**:
- Verify credential is registered: `curl http://localhost:8083/api/credentials/sf_test`
- Check credential key in playbook matches registered name
- Re-register if needed: `task noetl:local:reset`

### Data Transfer Issues

**Column Case Mismatch**:
- The plugin automatically lowercases Snowflake column names for PostgreSQL
- Ensure PostgreSQL table uses lowercase column names
- Snowflake: `ID, NAME` → PostgreSQL: `id, name`

**Data Type Mismatch**:
- Automatic conversions: VARIANT ↔ JSONB, TIMESTAMP_TZ ↔ TIMESTAMPTZ
- For custom types, use SQL CAST in source query
- Update target table schema to match source data types

**Chunk Transfer Timeout**:
- Reduce chunk_size (e.g., from 10000 to 1000)
- Increase worker timeout settings in environment
- Check network bandwidth between Snowflake and NoETL worker

**Primary Key Conflicts** (upsert mode):
- First column in SELECT is used as primary key
- Verify target table has primary key defined
- Check for duplicate keys in source data
- Use explicit ORDER BY in source query

## Architecture Notes

### Action Type Implementation

The `snowflake_transfer` action type is implemented as a dedicated plugin:
- **Package**: `noetl/plugin/snowflake_transfer/`
- **Executor**: `executor.py` with `execute_snowflake_transfer_action()`
- **Dispatcher**: Registered in `noetl/plugin/tool/execution.py`
- **Auth System**: Uses NoETL's unified auth resolver (non-legacy)

### Chunked Streaming

The plugin uses **cursor-based chunked streaming**:

1. **Auth Resolution**: Resolves both Snowflake and PostgreSQL credentials via unified auth
2. **Connection Setup**: Establishes connections to both databases
3. **Source Query Execution**: Opens cursor on source database
4. **Column Mapping**: Automatically lowercases Snowflake columns for PostgreSQL
5. **Chunk Fetching**: Retrieves `chunk_size` rows at a time
6. **Batch Insert**: Inserts chunk into target database with proper quoting
7. **Commit**: Commits transaction after each chunk
8. **Progress Events**: Reports transfer progress via event callbacks
9. **Repeat**: Continues until all data transferred
10. **Cleanup**: Closes connections gracefully

**Benefits**:
- Memory efficient (only one chunk in memory at a time)
- Resilient (partial progress preserved on failure)
- Scalable (handles datasets larger than available RAM)
- Automatic column case conversion
- Type-safe data conversion (VARIANT→JSONB, etc.)

### Unified Auth System

The action type uses NoETL's modern unified auth pattern (same as `duckdb` plugin):

```python
from noetl.worker.auth_resolver import resolve_auth

# Resolve multi-credential auth
mode_type, resolved_auth_map = resolve_auth(auth_config, jinja_env, context)

# Access payload from ResolvedAuthItem
sf_auth_data = resolved_auth_map.get('sf').payload
pg_auth_data = resolved_auth_map.get('pg').payload

# Extract credentials with prefix mapping
sf_account = sf_auth_data.get('sf_account')
pg_host = pg_auth_data.get('db_host')
```

### Connection Management

- **Persistent Connections**: Single connection per transfer direction
- **Transaction Control**: Each chunk is a separate transaction
- **Graceful Cleanup**: Connections closed even on errors
- **Connection Pooling**: Handled by underlying connectors (snowflake-connector-python, psycopg)

### Error Handling

- **Per-Chunk Errors**: Logged with chunk number and row range
- **Rollback**: Failed chunks rolled back automatically
- **Progress Tracking**: Rows transferred count includes only committed data

## Integration with NoETL

### Using with Other Action Types

Combine `snowflake_transfer` with `snowflake` and `postgres` action types:

```yaml
workflow:
  # Use snowflake action type for DDL
  - step: prepare_snowflake
    type: snowflake
    auth: "{{ workload.sf_auth }}"
    command: |
      CREATE DATABASE IF NOT EXISTS TEST_DB;
      CREATE TABLE source_data (id INT, name STRING);
  
  # Use postgres action type for DDL
  - step: prepare_postgres
    type: postgres
    auth: "{{ workload.pg_auth }}"
    command: |
      CREATE TABLE target_data (id INT, name TEXT);
  
  # Use snowflake_transfer for data movement
  - step: move_data
    type: snowflake_transfer
    direction: sf_to_pg
    source:
      query: "SELECT * FROM source_data"
    target:
      table: "target_data"
    chunk_size: 1000
    auth:
      sf:
        source: credential
        type: snowflake
        key: "sf_test"
      pg:
        source: credential
        type: postgres
        key: "pg_local"
```

### With Iterator

Process multiple tables in parallel:

```yaml
workflow:
  - step: transfer_multiple_tables
    type: iterator
    collection: "{{ workload.tables }}"
    element: table
    mode: async
    task:
      type: snowflake_transfer
      direction: sf_to_pg
      source:
        query: "SELECT * FROM {{ table.source }}"
      target:
        table: "{{ table.target }}"
      chunk_size: 5000
      auth:
        sf:
          source: credential
          type: snowflake
          key: "{{ workload.sf_auth }}"
        pg:
          source: credential
          type: postgres
          key: "{{ workload.pg_auth }}"
```

### As Conditional Step

Use with conditional routing:

```yaml
workflow:
  - step: check_source
    type: snowflake
    auth: "{{ workload.sf_auth }}"
    command: "SELECT COUNT(*) as row_count FROM source_table;"
    next:
      - when: "{{ check_source.result.row_count > 0 }}"
        then:
          - step: transfer_data
            type: snowflake_transfer
            direction: sf_to_pg
            # ... transfer config
      - when: "{{ check_source.result.row_count == 0 }}"
        then:
          - step: skip_transfer
            desc: "No data to transfer"
```

## Testing Checklist

- [ ] Snowflake credentials registered (`sf_test`)
- [ ] PostgreSQL credentials registered (`pg_local`)
- [ ] NoETL server running (port 8083)
- [ ] NoETL workers active
- [ ] Test database access verified (demo_noetl)
- [ ] Snowflake warehouse running (SNOWFLAKE_LEARNING_WH)
- [ ] Playbook registered in catalog
- [ ] Execution initiated successfully
- [ ] SF→PG transfer completed (5 rows)
- [ ] PG→SF transfer completed (5 rows)
- [ ] Column case conversion verified (uppercase→lowercase)
- [ ] Data type conversions verified (VARIANT→JSONB)
- [ ] Data verification passed

## Example Verification Queries

### PostgreSQL
```bash
# Check transferred data
PGPASSWORD=demo psql -h localhost -p 54321 -U demo -d demo_noetl -c \
  "SELECT id, name, value, 
          created_at, 
          metadata->>'type' as type 
   FROM public.test_snowflake_transfer 
   ORDER BY id;"

# Verify row count
PGPASSWORD=demo psql -h localhost -p 54321 -U demo -d demo_noetl -c \
  "SELECT COUNT(*) FROM public.test_snowflake_transfer;"
```

### Snowflake
```sql
-- Check transferred data (from Snowflake console)
USE DATABASE TEST_DB;
USE SCHEMA PUBLIC;

SELECT * FROM PG_IMPORTED_DATA ORDER BY id;

-- Verify row count
SELECT COUNT(*) FROM PG_IMPORTED_DATA;
```

### NoETL Events
```bash
# Check execution events
PGPASSWORD=noetl psql -h localhost -p 54321 -U noetl -d demo_noetl -c \
  "SELECT event_type, node_name, status, created_at, data->>'rows_transferred'
   FROM noetl.event 
   WHERE node_name LIKE '%transfer%'
   ORDER BY created_at DESC 
   LIMIT 10;"
```

## References

- [NoETL Snowflake Plugin Documentation](../../../../docs/plugin/snowflake.md)
- [NoETL Credential Management](../../../../docs/credentials.md)
- [NoETL Unified Auth System](../../../../docs/auth_refactoring_summary.md)
- [Snowflake Python Connector Docs](https://docs.snowflake.com/en/user-guide/python-connector.html)
- [psycopg3 Documentation](https://www.psycopg.org/psycopg3/docs/)
- [NoETL Action Types](../../../../docs/action_type.md)

## Related Files

- **Action Type Plugin**: `noetl/plugin/snowflake_transfer/executor.py`
- **Snowflake Plugin**: `noetl/plugin/snowflake/`
- **Transfer Functions**: `noetl/plugin/snowflake/transfer.py`
- **Dispatcher**: `noetl/plugin/tool/execution.py`
- **Server Transitions**: `noetl/server/api/event/service/transitions.py`
- **Auth Resolver**: `noetl/worker/auth_resolver.py`

## Summary

This playbook demonstrates the complete implementation of the `snowflake_transfer` action type, featuring:
- ✅ Bidirectional data transfer (Snowflake ↔ PostgreSQL)
- ✅ Unified auth system integration (non-legacy)
- ✅ Automatic column case conversion
- ✅ Chunked streaming for memory efficiency
- ✅ Multiple transfer modes (append, replace, upsert)
- ✅ Data type conversions (VARIANT↔JSONB, TIMESTAMP_TZ↔TIMESTAMPTZ)
- ✅ Event-driven progress tracking
- ✅ Production-ready error handling

The implementation follows NoETL's modern plugin architecture and serves as a reference for building similar data transfer action types.
