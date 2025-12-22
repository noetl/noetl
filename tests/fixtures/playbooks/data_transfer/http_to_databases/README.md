# HTTP to Multiple Databases Transfer Test

## Overview

This playbook demonstrates fetching data from an HTTP API and distributing it to multiple database systems (PostgreSQL, Snowflake, and DuckDB) using NoETL's data transfer capabilities.

## Test Purpose

Validates:
- HTTP API data fetching
- Python data transformation with single quotes escaping
- Iterator-based batch insertion across multiple databases
- Cross-database data verification
- Multi-database consistency checks

## Architecture

```
HTTP API (JSONPlaceholder)
    ↓
Transform (Python)
    ↓
├─→ PostgreSQL (INSERT with UPSERT)
├─→ Snowflake (MERGE statement)
└─→ DuckDB (INSERT with UPSERT)
    ↓
Cross-Verify Results
```

## Prerequisites

- **Credentials Required:**
  - `pg_local`: PostgreSQL local database credentials
  - `sf_test`: Snowflake test account credentials

- **Database Access:**
  - PostgreSQL: localhost:54321
  - Snowflake: TEST_DB.PUBLIC schema
  - DuckDB: Execution-specific database file

## Usage

### Register the Playbook

```bash
.venv/bin/noetl catalog register playbook \
  tests/fixtures/playbooks/data_transfer/http_to_databases/http_to_databases.yaml \
  --host localhost --port 8083
```

### Execute the Playbook

```bash
.venv/bin/noetl catalog execute playbook \
  tests/fixtures/playbooks/data_transfer/http_to_databases \
  --host localhost --port 8083
```

### Execute with Custom Parameters

```bash
# Override credentials
.venv/bin/noetl catalog execute playbook \
  tests/fixtures/playbooks/data_transfer/http_to_databases \
  --payload '{"pg_auth": "pg_k8s", "sf_auth": "sf_prod"}' \
  --merge \
  --host localhost --port 8083
```

## Workflow Steps

### 1. **fetch_http_data**
- Fetches user data from JSONPlaceholder API
- URL: `https://jsonplaceholder.typicode.com/users`
- Returns: Array of 10 user objects

### 2. **create_sf_database**
- Creates Snowflake database and selects schema
- Database: `TEST_DB`
- Schema: `PUBLIC`

### 3. **setup_pg_table**
- Creates PostgreSQL table `http_users_pg`
- Truncates existing data
- Columns: id, name, username, email, phone, website, company_name, city

### 4. **setup_sf_table**
- Creates Snowflake table `HTTP_USERS_SF`
- Uses CREATE OR REPLACE for idempotency
- Columns: Same as PostgreSQL table

### 5. **setup_duckdb_table**
- Creates DuckDB table `http_users_duckdb`
- Deletes existing data
- Columns: Same as other tables

### 6. **transform_http_to_pg**
- Python transformation step
- Extracts user data from HTTP response structure
- Escapes single quotes in string fields for SQL safety
- Flattens nested company and address objects
- Returns: `{status: 'success', rows: [...], count: N}`
- The `rows` array contains transformed dictionaries ready for database insertion

### 7. **insert_to_postgres**
- Iterator-based insertion (10 users, sequential mode)
- Iterates over `transform_http_to_pg.rows` collection
- Each iteration: INSERT with ON CONFLICT DO UPDATE (upsert pattern)
- Nested postgres tool task with base64-encoded commands
- Result: 10 successful insertions (1 row affected per iteration)

### 8. **verify_pg_data**
- Validates PostgreSQL data
- Counts: total users, unique cities, unique companies

### 9. **insert_to_snowflake**
- Iterator-based insertion using MERGE statement
- Handles both INSERT and UPDATE operations
- Sequential mode

### 10. **verify_sf_data**
- Validates Snowflake data
- Same metrics as PostgreSQL verification

### 11. **insert_to_duckdb**
- Iterator-based insertion with UPSERT
- Uses INSERT ... ON CONFLICT DO UPDATE
- Sequential mode

### 12. **verify_duckdb_data**
- Validates DuckDB data
- Same metrics as other databases

### 13. **cross_verify**
- Python step comparing all three databases
- Checks if record counts match across systems
- Returns: Comparison object with all metrics

### 14. **cleanup**
- Optional cleanup step (currently commented out)
- Preserves tables for inspection

## Data Flow Patterns

### Args-Based Data Passing

The playbook uses `args:` blocks to pass data between steps:

```yaml
- step: transform_http_to_pg
  tool: python
  code: |
    def main(fetch_http_data):
        # Function parameter matches args key
        users = fetch_http_data.get('data', [])
        # Transform logic...
  args:
    fetch_http_data: "{{ fetch_http_data.data }}"
  next:
    - step: insert_to_postgres
```

### Iterator Pattern with Task Block

```yaml
- step: insert_to_postgres
  tool: iterator
  collection: "{{ transform_http_to_pg.rows }}"
  element: user
  mode: sequential
  task:  # Note: uses 'task' not 'workbook'
    tool: postgres
    auth: "{{ workload.pg_auth }}"
    command: |
      INSERT INTO table (...)
      VALUES ({{ user.id }}, '{{ user.name }}', ...)
```

### Cross-Database Verification

```yaml
- step: cross_verify
  tool: python
  code: |
    def main(verify_pg_data, verify_sf_data, verify_duckdb_data):
        # Access result structures specific to each database
        pg_result = verify_pg_data['data']['command_0']['rows'][0]
        sf_result = verify_sf_data['data']['statement_0']['result'][0]
        duckdb_result = verify_duckdb_data['data']['result'][0]
        # Compare metrics...
  args:
    verify_pg_data: "{{ verify_pg_data }}"
    verify_sf_data: "{{ verify_sf_data }}"
    verify_duckdb_data: "{{ verify_duckdb_data }}"
```

## Expected Results

- 10 users fetched from HTTP API
- 10 records inserted into PostgreSQL via iterator
- 10 records inserted into Snowflake via iterator with MERGE
- 10 records inserted into DuckDB via iterator with UPSERT
- All databases have matching counts (10 users each)
- Cross-verify returns: "All databases have 10 users"

## Technical Notes

### Iterator Base64 Encoding

The iterator controller automatically encodes nested task configurations when executing tasks directly within the worker process. This ensures that PostgreSQL `command`, DuckDB `command`, and Python `code` fields are properly base64-encoded before execution, matching the behavior of tasks published through the queue system.

This encoding happens in `noetl/tools/controller/iterator/execution.py` via the `_encode_nested_task()` function, which:
1. Base64-encodes `code`, `command`, and `commands` fields
2. Removes the original plain-text fields
3. Ensures consistent handling regardless of execution path (queue vs direct)

## Verification Queries

### PostgreSQL
```sql
SELECT COUNT(*) as total, 
       COUNT(DISTINCT city) as cities,
       COUNT(DISTINCT company_name) as companies
FROM public.http_users_pg;
```

### Snowflake
```sql
SELECT COUNT(*) as total,
       COUNT(DISTINCT city) as cities,
       COUNT(DISTINCT company_name) as companies
FROM HTTP_USERS_SF;
```

### DuckDB
Query via NoETL:
```yaml
tool: duckdb
command: |
  SELECT COUNT(*) as total,
         COUNT(DISTINCT city) as cities,
         COUNT(DISTINCT company_name) as companies
  FROM http_users_duckdb;
```

## Key Learnings

1. **Iterator Syntax:** Use `task:` block (not `workbook:`) for iterator actions
2. **Function Signatures:** Python function parameters must match `args:` keys exactly
3. **Data References:** Step results accessed as `{{ step_name }}` are automatically unwrapped
4. **Database-Specific Results:** Each database tool has different result structures
   - PostgreSQL: `command_0.rows`
   - Snowflake: `statement_0.result`
   - DuckDB: `result`

5. **Args vs Data:** Use `args:` for explicit parameter passing (preferred pattern)

## Troubleshooting

### No Data Inserted
- Check transform step output: Should show `count: 10` and non-empty `rows` array
- Verify HTTP API response structure in fetch_http_data result
- Check worker logs (`logs/worker-debug.log`) for Python function execution details
- Validate Jinja2 template resolution in step context

### Iterator Errors with "No command_b64 found"
- **Fixed in v1.0+**: Iterator now automatically base64-encodes nested task commands
- If you see this error on older versions, upgrade to latest NoETL release
- The fix is in `noetl/tools/controller/iterator/execution.py`

### Database Connection Errors
- Verify credentials are registered: `.venv/bin/noetl credential list`
- Check database connectivity from worker host
- Ensure PostgreSQL is running on localhost:54321
- Verify Snowflake account access and credentials

### Iterator Failures
- Confirm `task:` block syntax (not `workbook:`)
- Validate collection reference resolves to array: check transform step result
- Verify element variable usage in SQL templates (e.g., `{{ user.id }}`)
- Check for SQL injection risks: ensure proper escaping in transform step

## Files

- `http_to_databases.yaml` - Main playbook
- `README.md` - This documentation
