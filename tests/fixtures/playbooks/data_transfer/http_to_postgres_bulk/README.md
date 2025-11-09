# HTTP to PostgreSQL Bulk Transfer Test

## Purpose

This playbook validates NoETL's `transfer` tool for bulk data movement from HTTP APIs to PostgreSQL. It demonstrates the declarative approach to data loading, where NoETL handles the connection management, chunking, and transaction control automatically.

## What This Validates

- HTTP API data fetching as a transfer source
- Bulk data transfer using the `transfer` tool
- Column mapping from JSON to database columns
- Automatic chunking and transaction management
- PostgreSQL as a transfer target

## Architecture

```
┌─────────────────────┐
│   HTTP Source       │  Fetch 100 posts from JSONPlaceholder API
│                     │  GET https://jsonplaceholder.typicode.com/posts
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Transfer Tool      │  • Fetches HTTP data automatically
│                     │  • Maps JSON fields → SQL columns
│                     │  • Chunks data (10 rows/batch)
│                     │  • Manages PostgreSQL connection
│                     │  • Executes bulk INSERT
│                     │  • Commits transactions per chunk
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  PostgreSQL Target  │  Verify record count
│  (show_count)       │
└─────────────────────┘
```

## Workflow Steps

### 1. create_table
- **Type**: `postgres` tool
- **Purpose**: Drop and recreate `http_posts` table
- **Schema**:
  ```sql
  CREATE TABLE public.http_posts (
    id SERIAL PRIMARY KEY,
    post_id INTEGER,
    user_id INTEGER,
    title TEXT,
    body TEXT,
    fetched_at TIMESTAMPTZ DEFAULT NOW()
  );
  ```

### 2. transfer_http_to_pg
- **Type**: `transfer` tool
- **Source**: HTTP API - https://jsonplaceholder.typicode.com/posts
- **Target**: PostgreSQL - `public.http_posts` table
- **Column Mapping**:
  ```yaml
  mapping:
    post_id: id        # JSON field 'id' → SQL column 'post_id'
    user_id: userId    # JSON field 'userId' → SQL column 'user_id'
    title: title       # Direct mapping
    body: body         # Direct mapping
  ```
- **Process**:
  1. Fetches HTTP data automatically
  2. Maps JSON fields to database columns
  3. Chunks data (10 rows per batch)
  4. Executes bulk INSERT with proper transactions
  5. Returns transfer statistics

### 3. show_count
- **Type**: `postgres` tool
- **Purpose**: Verify 100 records were inserted
- **Query**: `SELECT COUNT(*) as records FROM public.http_posts;`

## Key Features

- **Declarative Configuration**: Simple YAML, no custom code
- **Automatic Column Mapping**: Maps JSON fields to SQL columns
- **Chunked Transfers**: Processes data in batches (configurable chunk_size)
- **Transaction Management**: Automatic commit/rollback per chunk
- **Connection Pooling**: Reuses connections efficiently
- **Error Handling**: Built-in retry and error reporting

## When to Use

### Use Transfer Tool When:
- Standard bulk data movement
- Simple column mappings
- No custom transformation logic needed
- Want automatic chunking and transaction handling

### Use Custom Python When:
- Complex data transformations required
- Need driver-specific features (COPY, MERGE with complex logic)
- Custom error handling or retry logic
- Performance optimization with direct SQL
- See: `tests/fixtures/playbooks/python_psycopg/http_to_postgres_bulk/`

## Prerequisites

- **NoETL Server**: Running on localhost:8083
- **PostgreSQL**: Running on localhost:54321, database `demo_noetl`
- **Credential**: `pg_local` registered with connection details
- **HTTP Access**: Internet connection to reach JSONPlaceholder API

## Usage

### 1. Register Playbook
```bash
.venv/bin/noetl register \
  tests/fixtures/playbooks/data_transfer/http_to_postgres_bulk/http_to_postgres_bulk.yaml \
  --host localhost --port 8083
```

### 2. Execute Playbook
```bash
.venv/bin/noetl execute playbook \
  "tests/fixtures/playbooks/data_transfer/http_to_postgres_bulk" \
  --host localhost --port 8083 --json
```

### 3. Verify Results
```bash
# Check record count
PGPASSWORD=demo psql -h localhost -p 54321 -U demo -d demo_noetl \
  -c "SELECT COUNT(*) FROM public.http_posts;"

# View sample records
PGPASSWORD=demo psql -h localhost -p 54321 -U demo -d demo_noetl \
  -c "SELECT * FROM public.http_posts LIMIT 5;"
```

## Expected Results

- **Execution Status**: COMPLETED
- **Records Inserted**: 100
- **HTTP Source**: 100 posts from JSONPlaceholder API
- **Transfer Statistics**:
  ```json
  {
    "rows_transferred": 100,
    "chunks_processed": 1,
    "source": "http",
    "target": "postgres"
  }
  ```
- **PostgreSQL Count**: 100 records in `http_posts` table

## Troubleshooting

### 1. Connection Refused
**Symptom**: PostgreSQL connection refused during transfer

**Cause**: PostgreSQL not running or incorrect credentials

**Solution**:
```bash
# Start PostgreSQL
docker compose up -d

# Verify pg_local credential exists
curl http://localhost:8083/api/credentials | jq '.[] | select(.name=="pg_local")'
```

### 2. HTTP Source Unreachable
**Symptom**: Transfer fails with HTTP connection error

**Cause**: Cannot reach JSONPlaceholder API

**Solution**:
```bash
# Test API accessibility
curl https://jsonplaceholder.typicode.com/posts

# Check network connectivity
ping jsonplaceholder.typicode.com
```

## Data Flow Details

### HTTP Response Structure
```python
{
  "url": "https://jsonplaceholder.typicode.com/posts",
  "data": [  # Array of 100 posts
    {"id": 1, "userId": 1, "title": "...", "body": "..."},
    ...
  ],
  "status_code": 200,
  "headers": {...},
  "elapsed": 0.06132
}
```

### Data Extraction in Python
```python
# Transfer tool automatically extracts data from HTTP response
# No manual extraction needed - the tool handles:
# - Response parsing
# - Data extraction
# - Field mapping
# - Chunking
```

### Transfer Process
```yaml
# Declarative configuration - no code needed
tool: transfer
source:
  type: http
  url: "https://jsonplaceholder.typicode.com/posts"
  method: GET
target:
  type: postgres
  table: public.http_posts
  mapping:
    post_id: id      # JSON field → SQL column
    user_id: userId
    title: title
    body: body
chunk_size: 10     # Automatic batching
```

## Troubleshooting

### Check Execution Events
```bash
# Get execution ID from execute command output
execution_id="<your_execution_id>"

# Query all events
PGPASSWORD=demo psql -h localhost -p 54321 -U demo -d demo_noetl -c \
  "SELECT event_type, node_name, status FROM noetl.event 
   WHERE execution_id = '$execution_id' ORDER BY event_id;"
```

### View Error Details
```bash
# Get error message
PGPASSWORD=demo psql -h localhost -p 54321 -U demo -d demo_noetl -c \
  "SELECT error FROM noetl.event 
   WHERE execution_id = '$execution_id' AND event_type = 'action_failed';"
```

### Check Transfer Result
```bash
# Get transfer_http_to_pg result
PGPASSWORD=demo psql -h localhost -p 54321 -U demo -d demo_noetl -c \
  "SELECT result FROM noetl.event 
   WHERE execution_id = '$execution_id' 
   AND node_name = 'transfer_http_to_pg' 
   AND event_type = 'step_result';"
```

## Comparison: Transfer Tool vs Custom Python

| Feature | Transfer Tool (this playbook) | Custom Python (python_psycopg version) |
|---------|-------------------------------|----------------------------------------|
| **Configuration** | Declarative YAML | Imperative Python code |
| **Code Required** | None | ~50 lines Python |
| **Connection Mgmt** | Automatic | Manual (with psycopg) |
| **Chunking** | Built-in (configurable) | Must implement manually |
| **Transactions** | Automatic per chunk | Must manage manually |
| **Error Handling** | Built-in retry logic | Must implement manually |
| **Maintainability** | High (no code) | Medium (requires code updates) |
| **Flexibility** | Limited to mapping | Full control over logic |
| **Performance** | Optimized by framework | Depends on implementation |
| **Use Case** | Standard bulk transfers | Complex transformations, custom logic |
| **Learning Curve** | Low (YAML only) | Medium (Python + driver) |

## Related Playbooks

- **http_to_postgres_bulk_python**: Same use case using custom Python with psycopg (imperative approach)
- **http_to_databases**: Multi-database transfer using iterator pattern
- **snowflake_postgres**: Database-to-database transfer using transfer tool
- **save_storage_test**: Declarative save blocks for persistence

## File Structure

```
tests/fixtures/playbooks/data_transfer/http_to_postgres_bulk/
├── http_to_postgres_bulk.yaml    # Main playbook definition
└── README.md                      # This file
```

## Metadata

- **API Version**: noetl.io/v1
- **Kind**: Playbook
- **Path**: tests/fixtures/playbooks/data_transfer/http_to_postgres_bulk
- **Approach**: Declarative (transfer tool)
- **Last Updated**: 2025-11-09
- **Status**: Tested and working (100 records successfully transferred)
