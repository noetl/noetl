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
- Extracts user data from HTTP response
- Escapes single quotes in string fields
- Flattens nested company and address objects
- Returns: Array of transformed row dictionaries

### 7. **insert_to_postgres**
- Iterator-based insertion (10 users)
- Uses INSERT ... ON CONFLICT DO UPDATE
- Sequential mode for data consistency

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

## Known Issues

### Data Passing with Nested Structures

There is currently an issue with passing nested HTTP response data through Jinja2 templates to Python functions. The HTTP tool returns data in this structure:

```
result.data.data = [array of records]
```

When using `{{ fetch_http_data.data }}` in the args block, the data may not be correctly passed to the Python function parameter. This is under investigation.

**Workaround:** Use direct database queries or simplify the data structure in intermediate steps.

## Expected Results

When fully working:
- 10 users fetched from HTTP API
- 10 records inserted into each database
- All databases have matching counts
- Cross-verify returns: "All databases have 10 users"

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
- Check transform step output: Should show `count > 0`
- Verify HTTP API response structure
- Check worker logs for Python function execution
- Validate Jinja2 template resolution

### Database Connection Errors
- Verify credentials are registered
- Check database connectivity
- Ensure tables don't have conflicting constraints

### Iterator Failures
- Confirm `task:` block syntax (not `workbook:`)
- Validate collection reference resolves to array
- Check element variable usage in SQL

## Files

- `http_to_databases.yaml` - Main playbook
- `README.md` - This documentation
