# HTTP to PostgreSQL Transfer - Transfer Tool Pattern

## Overview

This playbook demonstrates the **transfer tool** pattern for direct data movement between sources and targets. Unlike manual Python transformation or iterators, the transfer tool:

1. Fetches data from HTTP API
2. Automatically maps and transforms fields
3. Inserts directly into PostgreSQL with schema mapping
4. Handles the entire ETL pipeline in a single declarative step

This is the **simplest and most efficient** pattern for straightforward data transfers with field mapping and no complex transformations.

## Usage

```bash
# Register the playbook
.venv/bin/noetl catalog register playbook \
  tests/fixtures/playbooks/data_transfer/http_to_postgres_transfer/http_to_postgres_transfer.yaml \
  --host localhost --port 8083

# Execute with local PostgreSQL credentials
.venv/bin/noetl execute playbook \
  "tests/fixtures/playbooks/data_transfer/http_to_postgres_transfer" \
  --host localhost --port 8083 \
  --payload '{"pg_auth": "pg_local"}' --merge
```

## Workflow Steps

### 1. Create Target Table (`create_table`)
- **Tool**: `postgres`
- **Action**: 
  - Drops existing table `public.http_to_postgres_transfer` if exists
  - Creates new table with schema including auto-generated timestamp
- **Schema**:
  ```sql
  CREATE TABLE public.http_to_postgres_transfer (
    id SERIAL PRIMARY KEY,
    post_id INTEGER,
    user_id INTEGER,
    title TEXT,
    body TEXT,
    fetched_at TIMESTAMPTZ DEFAULT NOW()
  );
  ```

### 2. Transfer Data (`transfer_http_to_pg`)
- **Tool**: `transfer`
- **Source Configuration**:
  ```yaml
  source:
    type: http
    url: "{{ workload.api_url }}"
    method: GET
  ```
- **Target Configuration**:
  ```yaml
  target:
    type: postgres
    auth: "{{ workload.pg_auth }}"
    table: public.http_to_postgres_transfer
    mode: insert
    mapping:
      post_id: id         # Target column: Source field
      user_id: userId
      title: title
      body: body
  ```
- **Process**:
  1. HTTP GET request fetches JSON array
  2. Transfer tool maps source fields to target columns
  3. Batch inserts into PostgreSQL table
  4. Auto-populated fields (id, fetched_at) handled by database

### 3. Verify Results (`show_count`)
- **Tool**: `postgres`
- **Action**: Count records to verify transfer success
- **Query**: `SELECT COUNT(*) as records FROM public.http_to_postgres_transfer;`

## Transfer Tool Configuration

### Source Types
The transfer tool supports multiple source types:
- `http`: REST API endpoints
- `postgres`: PostgreSQL queries
- `snowflake`: Snowflake queries
- `duckdb`: DuckDB queries

### Target Types
Supported target types:
- `postgres`: PostgreSQL tables
- `snowflake`: Snowflake tables
- `duckdb`: DuckDB tables

### Field Mapping
The `mapping` configuration specifies how source fields map to target columns:

```yaml
mapping:
  target_column_name: source_field_name
```

**Important**: 
- Left side = database column name (must exist in table)
- Right side = JSON field name from source data
- Field names are case-sensitive
- Unmapped source fields are ignored
- Unmapped target columns use default values or NULL

### Insert Modes
The `mode` parameter controls insertion behavior:
- `insert`: Append new rows (default)
- `upsert`: Insert or update based on primary key (if supported)
- `replace`: Truncate table first, then insert

## Expected Results

After successful execution:
- **Table**: `public.http_to_postgres_transfer`
- **Records**: 100 posts
- **Unique users**: 10 (user IDs 1-10)
- **Post IDs**: 1-100
- **Auto-generated**: Sequential IDs and timestamps

### Verification Queries

```sql
-- Total records and unique users
SELECT 
  COUNT(*) as total,
  COUNT(DISTINCT user_id) as unique_users,
  MIN(post_id) as min_post,
  MAX(post_id) as max_post
FROM public.http_to_postgres_transfer;
-- Expected: 100 total, 10 unique users, posts 1-100

-- Check timestamps
SELECT 
  MIN(fetched_at) as first_fetch,
  MAX(fetched_at) as last_fetch,
  MAX(fetched_at) - MIN(fetched_at) as duration
FROM public.http_to_postgres_transfer;
-- Should show when data was fetched

-- Sample data
SELECT * FROM public.http_to_postgres_transfer ORDER BY id LIMIT 5;
```

## Pattern Comparison

### Transfer Tool (This Playbook)
**Advantages**:
- Declarative configuration (no code)
- Built-in field mapping
- Single step for entire ETL
- Automatic type handling
- Best performance for simple transfers
- Minimal configuration

**Best for**:
- Direct data movement with field mapping
- Standard ETL without complex transformations
- When source and target types are both supported
- Production data pipelines

**Example**:
```yaml
- tool: transfer
  source:
    type: http
    url: "{{ api_url }}"
  target:
    type: postgres
    table: target_table
    mapping:
      db_col: source_field
```

### Python Batch INSERT (http_to_postgres_simple)
**Advantages**:
- Full control over transformation logic
- Can perform complex calculations
- Custom validation and error handling
- Generate dynamic SQL

**Best for**:
- Complex transformations (calculations, concatenations)
- Custom business logic
- Data validation rules
- When you need programming flexibility

### Iterator (http_to_postgres_iterator)
**Advantages**:
- Processes records individually
- Lower memory footprint
- Can chain multiple operations per record
- Built-in parallelization support

**Best for**:
- Very large datasets
- When each record needs independent processing
- Streaming or continuous data

### Comparison Table

| Criteria | Transfer | Python Batch | Iterator |
|----------|----------|--------------|----------|
| Complexity | Lowest | Medium | Highest |
| Code Required | None | Python | YAML |
| Performance | Best | Good | Good (large data) |
| Memory Usage | Low | Medium | Lowest |
| Flexibility | Limited | Highest | Medium |
| Field Mapping | Declarative | Programmatic | Template-based |
| Best Use Case | Simple ETL | Complex transforms | Large datasets |

## Technical Notes

### Transfer Tool Architecture
The transfer tool:
1. Executes source query/request
2. Retrieves data as JSON array
3. Maps fields according to configuration
4. Batches inserts for performance
5. Reports success/failure with metrics

### Automatic Type Conversion
The transfer tool handles type conversion automatically:
- JSON strings → TEXT
- JSON numbers → INTEGER/NUMERIC
- JSON booleans → BOOLEAN
- JSON null → NULL
- Nested objects → JSONB (if target supports)

### Error Handling
Transfer failures report:
- Number of successful inserts
- Number of failed inserts
- Specific error messages
- Which records failed (if applicable)

### Performance Characteristics
- Batch size: Configurable (default: 1000 records)
- Memory: Streams data for large datasets
- Network: Single HTTP request, single DB connection
- Typical speed: 1000-10000 records/second

## Troubleshooting

### Issue: ValueError: Transfer failed: source.type is required
**Cause**: Using `tool:` instead of `type:` in source/target configuration.

**Solution**: Use `type:` for source and target:
```yaml
source:
  type: http         # ✓ Correct
  tool: http         # ✗ Wrong

target:
  type: postgres     # ✓ Correct
  tool: postgres     # ✗ Wrong
```

### Issue: Column Not Found Error
**Cause**: Mapping references a column that doesn't exist in target table.

**Solution**: 
1. Verify table schema: `\d table_name` in psql
2. Check mapping keys match actual column names
3. Ensure column names are case-sensitive correct

**Example**:
```yaml
mapping:
  user_id: userId    # ✓ Correct if column is 'user_id'
  userId: userId     # ✗ Wrong if column is 'user_id'
```

### Issue: Data Type Mismatch
**Cause**: Source data type incompatible with target column type.

**Solution**:
1. Check source data types in API response
2. Ensure target columns have compatible types
3. Use wider types (e.g., TEXT instead of VARCHAR(50))

**Example**:
```sql
-- If source has long text, use TEXT not VARCHAR
title TEXT,           -- ✓ Handles any length
title VARCHAR(50),    -- ✗ May truncate
```

### Issue: Missing Records After Transfer
**Cause**: 
- Field mapping incomplete
- Source data format unexpected
- Silent failures in batch

**Debug**:
```sql
-- Check what was inserted
SELECT COUNT(*), MIN(post_id), MAX(post_id) 
FROM target_table;

-- Compare with source
-- Should match source record count
```

### Issue: Authentication Failed
**Cause**: Invalid or missing credentials.

**Solution**:
```yaml
# Ensure credential exists and is registered
target:
  auth: "{{ workload.pg_auth }}"  # ✓ Correct - uses workload variable

# Override at execution time
--payload '{"pg_auth": "pg_local"}' --merge
```

### Issue: Duplicate Primary Key Violations
**Cause**: Re-running playbook without truncating table.

**Solution**:
1. Add `DROP TABLE IF EXISTS` in create_table step (current approach)
2. Use `mode: upsert` in transfer target
3. Use table without primary key for append-only

## Related Playbooks

- **http_to_postgres_simple**: Python batch INSERT with custom transformation
- **http_to_postgres_iterator**: Record-by-record processing with iterator
- **http_to_postgres_bulk**: Native PostgreSQL COPY for maximum speed
- **http_to_databases**: Parallel transfers to multiple database types
- **snowflake_postgres**: Similar transfer pattern for Snowflake → PostgreSQL

## File Structure

```
http_to_postgres_transfer/
├── http_to_postgres_transfer.yaml  # Main playbook
└── README.md                        # This file
```

## Configuration Reference

### Complete Transfer Step Template

```yaml
- step: transfer_step_name
  desc: Description of transfer
  tool: transfer
  source:
    type: http | postgres | snowflake | duckdb
    # HTTP-specific
    url: "{{ url }}"
    method: GET | POST
    headers:
      Header-Name: value
    # Database-specific
    auth: "{{ credential_name }}"
    query: "SELECT * FROM table"
  target:
    type: postgres | snowflake | duckdb
    auth: "{{ credential_name }}"
    table: schema.table_name
    mode: insert | upsert | replace
    mapping:
      target_col1: source_field1
      target_col2: source_field2
    batch_size: 1000  # Optional
  next:
    - step: next_step
```

## Metadata

- **Category**: Data Transfer
- **Pattern**: Transfer Tool (Declarative ETL)
- **Tools Used**: transfer (http → postgres)
- **Complexity**: Low
- **Performance**: Excellent (native batch operations)
- **Code Required**: None (pure configuration)
- **Memory Usage**: Low (streaming)
- **Best For**: Production ETL pipelines with simple field mapping
