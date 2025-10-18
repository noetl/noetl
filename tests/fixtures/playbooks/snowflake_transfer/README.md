# Snowflake Transfer Test Playbook

## Overview

This playbook demonstrates **chunked data transfer** capabilities between **Snowflake** and **PostgreSQL** using the NoETL Snowflake plugin with streaming support.

## Features Tested

- **Snowflake to PostgreSQL Transfer**: Stream data from Snowflake tables to PostgreSQL with configurable chunk sizes
- **PostgreSQL to Snowflake Transfer**: Stream data from PostgreSQL tables to Snowflake with configurable chunk sizes
- **Multiple Transfer Modes**: 
  - `append`: Add data to existing table
  - `replace`: Truncate before insert
  - `upsert`: Insert or update based on primary key
- **Memory Efficient**: Process large datasets without loading all data into memory
- **Progress Tracking**: Monitor transfer progress through callback mechanism
- **Error Handling**: Graceful handling of connection and data transfer errors

## Pipeline Flow

```
START
  ↓
1. Setup PostgreSQL Target Table
  ↓
2. Setup Snowflake Source Table (with test data)
  ↓
3. Transfer Snowflake → PostgreSQL (chunked)
  ↓
4. Verify PostgreSQL Data
  ↓
5. Setup PostgreSQL Source Table (with test data)
  ↓
6. Setup Snowflake Target Table
  ↓
7. Transfer PostgreSQL → Snowflake (chunked)
  ↓
8. Verify Snowflake Data
  ↓
9. Cleanup Test Tables
  ↓
END
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

```bash
# Register Snowflake credential
curl -X POST http://localhost:8082/api/credentials \
  -H "Content-Type: application/json" \
  --data-binary @tests/fixtures/credentials/sf_test.json

# Register PostgreSQL credential (if not already registered)
curl -X POST http://localhost:8082/api/credentials \
  -H "Content-Type: application/json" \
  --data-binary @tests/fixtures/credentials/pg_local.json
```

### 3. Set Environment Variables

Create a `.env` file or set environment variables:

```bash
# Snowflake credentials
export SF_ACCOUNT="xy12345.us-east-1"
export SF_USER="your_username"
export SF_PASSWORD="your_password"
export SF_WAREHOUSE="COMPUTE_WH"
export SF_DATABASE="TEST_DB"
export SF_SCHEMA="PUBLIC"

# PostgreSQL credentials
export PG_HOST="localhost"
export PG_PORT="5432"
export PG_USER="postgres"
export PG_PASSWORD="your_password"
export PG_DATABASE="demo_noetl"
```

## Running the Test

### Using Task Command

```bash
# Register playbook
task noetltest:playbook-register -- tests/fixtures/playbooks/snowflake_transfer/snowflake_transfer.yaml

# Execute playbook
task noetltest:playbook-execute -- tests/fixtures/playbooks/snowflake_transfer
```

### Using cURL

```bash
# Register playbook
curl -X POST http://localhost:8082/api/catalog \
  -H "Content-Type: application/yaml" \
  --data-binary @tests/fixtures/playbooks/snowflake_transfer/snowflake_transfer.yaml

# Execute playbook
curl -X POST http://localhost:8083/api/executions/run \
  -H "Content-Type: application/json" \
  -d '{"path": "tests/fixtures/playbooks/snowflake_transfer"}'
```

### Using NoETL CLI

```bash
# Register playbook
.venv/bin/noetl catalog register \
  tests/fixtures/playbooks/snowflake_transfer/snowflake_transfer.yaml \
  --host localhost --port 8082

# Execute playbook
.venv/bin/noetl execution run \
  tests/fixtures/playbooks/snowflake_transfer \
  --host localhost --port 8083
```

## Expected Output

### Successful Execution

The playbook will:

1. **Create Tables**: Set up test tables in both Snowflake and PostgreSQL
2. **Transfer SF → PG**: Move 5 test records from Snowflake to PostgreSQL
   - Output: `{rows_transferred: 5, chunks_processed: 1, status: 'success'}`
3. **Verify PG Data**: Query PostgreSQL to confirm data arrival
   - Output: `{row_count: 5, min_id: 1, max_id: 5, total_value: 1501.49}`
4. **Transfer PG → SF**: Move 5 test records from PostgreSQL to Snowflake
   - Output: `{rows_transferred: 5, chunks_processed: 1, status: 'success'}`
5. **Verify SF Data**: Query Snowflake to confirm data arrival
   - Output: `{row_count: 5, min_id: 101, max_id: 105, total_amount: 15001.49}`
6. **Cleanup**: Remove test tables

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
task_config = {
    'transfer_direction': 'sf_to_pg',
    'source_query': 'SELECT * FROM TEST_DATA',
    'target_table': 'public.test_snowflake_transfer',
    'chunk_size': 1000,
    'mode': 'replace'  # Options: append, replace, upsert
}
```

### Custom Queries

Modify source queries for more complex scenarios:

```yaml
'source_query': '''
    SELECT 
        id,
        name,
        value,
        created_at,
        metadata
    FROM TEST_DATA
    WHERE created_at > CURRENT_DATE - 7
    ORDER BY id
'''
```

## Troubleshooting

### Connection Issues

**Snowflake Connection Failed**:
- Verify account identifier format: `<account>.<region>`
- Check username and password
- Confirm warehouse is running
- Validate network access to Snowflake

**PostgreSQL Connection Failed**:
- Check host and port accessibility
- Verify credentials
- Confirm database exists
- Check firewall rules

### Data Transfer Issues

**Chunk Transfer Timeout**:
- Reduce chunk_size (e.g., from 10000 to 1000)
- Increase worker timeout settings
- Check network bandwidth

**Data Type Mismatch**:
- Review column types in source and target tables
- Use SQL CAST functions in source queries
- Update target table schema to match source

**Primary Key Conflicts** (upsert mode):
- Verify first column is primary key
- Use explicit key specification in transfer config
- Check for duplicate keys in source data

## Architecture Notes

### Chunked Streaming

The plugin uses **cursor-based chunked streaming**:

1. **Source Query Execution**: Opens cursor on source database
2. **Chunk Fetching**: Retrieves `chunk_size` rows at a time
3. **Batch Insert**: Inserts chunk into target database
4. **Commit**: Commits transaction after each chunk
5. **Repeat**: Continues until all data transferred

**Benefits**:
- Memory efficient (only one chunk in memory at a time)
- Resilient (partial progress preserved on failure)
- Scalable (handles datasets larger than available RAM)

### Connection Management

- **Persistent Connections**: Single connection per transfer direction
- **Transaction Control**: Each chunk is a separate transaction
- **Graceful Cleanup**: Connections closed even on errors

### Error Handling

- **Per-Chunk Errors**: Logged with chunk number and row range
- **Rollback**: Failed chunks rolled back automatically
- **Progress Tracking**: Rows transferred count includes only committed data

## Integration with NoETL

### As Workbook Task

Define transfer as reusable workbook task:

```yaml
workbook:
  - name: sf_pg_transfer
    type: python
    code: |
      # Transfer implementation
      from noetl.plugin.snowflake import execute_snowflake_transfer_task
      # ... (see playbook for full code)

workflow:
  - step: run_transfer
    type: workbook
    name: sf_pg_transfer
    data:
      sf_account: "{{ workload.sf_account }}"
      # ... other params
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
      type: python
      code: |
        # Transfer code for each table
```

## Testing Checklist

- [ ] Snowflake credentials registered
- [ ] PostgreSQL credentials registered
- [ ] NoETL server running
- [ ] NoETL workers active
- [ ] Test database access verified
- [ ] Environment variables set
- [ ] Playbook registered in catalog
- [ ] Execution initiated successfully
- [ ] Transfer progress monitored
- [ ] Data verification passed
- [ ] Cleanup completed

## References

- [NoETL Snowflake Plugin Documentation](../../../docs/plugin/snowflake.md)
- [NoETL Credential Management](../../../docs/credentials.md)
- [Snowflake Python Connector Docs](https://docs.snowflake.com/en/user-guide/python-connector.html)
- [psycopg3 Documentation](https://www.psycopg.org/psycopg3/docs/)
