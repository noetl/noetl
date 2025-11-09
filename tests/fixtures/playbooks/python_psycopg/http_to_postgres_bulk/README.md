# HTTP to PostgreSQL Bulk Insert Test Playbook

## Overview

This playbook validates NoETL's ability to execute custom Python code with direct database driver usage for bulk operations. It fetches data from a REST API and performs a bulk insert into PostgreSQL using psycopg directly, demonstrating an imperative approach to data loading.

## Validation Purpose

**What This Test Demonstrates:**
- Custom Python code execution within NoETL workflows
- Direct database driver usage (psycopg) for bulk operations
- Secure credential passing through Jinja2 secret references
- Single-transaction bulk insertion pattern
- Integration between HTTP and Python plugins

**Key Patterns Validated:**
1. **Function Parameter Mapping**: Python function parameters match `args` keys exactly
2. **Secret Reference Pattern**: Using `{{ secret.credential_name.field }}` for secure credential access
3. **Direct Driver Usage**: Manual connection management vs declarative plugins
4. **Bulk Insert Efficiency**: Single transaction for multiple inserts
5. **HTTP Data Extraction**: Accessing nested response structures

## Architecture

```
┌─────────────────────┐
│   HTTP API Call     │  Fetch 100 posts from JSONPlaceholder
│  (fetch_http_data)  │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Python Bulk Insert │  Direct psycopg connection
│   (bulk_insert)     │  • Extract data from HTTP response
│                     │  • Connect to PostgreSQL
│                     │  • Loop through posts
│                     │  • Execute INSERT for each
│                     │  • Commit transaction
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  PostgreSQL Query   │  Verify record count
│   (show_count)      │
└─────────────────────┘
```

## Workflow Steps

### 1. create_table
- **Type**: `postgres` plugin
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

### 2. fetch_http_data
- **Type**: `http` plugin
- **API**: https://jsonplaceholder.typicode.com/posts
- **Returns**: Array of 100 post objects with structure:
  ```json
  {
    "id": 1,
    "userId": 1,
    "title": "Post title",
    "body": "Post body content"
  }
  ```

### 3. bulk_insert
- **Type**: `python` plugin
- **Purpose**: Bulk insert using direct psycopg connection
- **Function Signature**:
  ```python
  def main(http_data, pg_host, pg_port, pg_user, pg_password, pg_database):
  ```
- **Data Mapping**:
  ```yaml
  data:
    http_data: "{{ fetch_http_data }}"  # Full step result
    pg_host: "{{ workload.pg_host }}"
    pg_port: "{{ workload.pg_port }}"
    pg_user: "{{ workload.pg_user }}"
    pg_password: "{{ workload.pg_password }}"
    pg_database: "{{ workload.pg_database }}"
  ```
  **Note**: Python plugin doesn't support `auth` property like postgres/duckdb plugins. Connection details are passed via workload variables or could be fetched using a separate secrets step.
- **Process**:
  1. Extract posts array from `http_data['data']`
  2. Create psycopg connection
  3. Execute INSERT for each post in a loop
  4. Commit transaction
  5. Close cursor and connection
  6. Return statistics

### 4. show_count
- **Type**: `postgres` plugin
- **Purpose**: Verify 100 records were inserted
- **Query**: `SELECT COUNT(*) as records FROM public.http_posts;`

## Key Learnings

### Iterator vs Bulk Insert Patterns

| Pattern | Use Case | Pros | Cons |
|---------|----------|------|------|
| **Iterator** (http_to_databases) | Per-item transformations, cross-database inserts | Declarative, maintainable, built-in error handling per item | More overhead for large datasets, multiple transactions |
| **Bulk Insert** (this playbook) | Large datasets, custom logic, performance-critical | Single transaction, full control, efficient for bulk data | Imperative code, manual error handling, less maintainable |

### When to Use Bulk Insert Pattern
- **Performance Critical**: Inserting thousands of records where overhead matters
- **Custom Logic**: Complex transformations not supported by declarative plugins
- **Transaction Control**: Need fine-grained control over commit/rollback
- **Driver-Specific Features**: Using psycopg-specific features (COPY, bulk operations)

### When to Use Iterator Pattern
- **Standard CRUD**: Simple inserts, updates, deletes
- **Per-Item Logic**: Each item needs independent processing
- **Maintainability**: Prefer declarative over imperative
- **Error Isolation**: Want to continue on individual failures

## When to Use Custom Python vs Transfer Tool

### Choose Custom Python (This Playbook) When:
1. **Complex Transformations**: Data requires logic beyond simple field mapping
   - Date parsing, string manipulation, conditional logic
   - Computed fields based on multiple input values
   - Data validation with custom business rules

2. **Driver-Specific Features**: Need PostgreSQL-specific functionality
   - `COPY` command for maximum bulk insert performance
   - Custom cursor types (server-side cursors, named cursors)
   - Transaction isolation level control
   - PostgreSQL extensions (hstore, jsonb operators, etc.)

3. **Custom Error Handling**: Specific retry or recovery logic
   - Partial batch processing (continue on individual errors)
   - Custom logging for audit trails
   - Conditional rollback based on data validation

4. **Performance Optimization**: Fine-tune for specific workloads
   - Batch size optimization based on data characteristics
   - Connection pooling with custom parameters
   - Memory management for large datasets

### Choose Transfer Tool When:
1. **Simple Mapping**: Direct field-to-column transfers
2. **Standard Operations**: No custom logic needed
3. **Maintainability Priority**: Prefer declarative over code
4. **Quick Implementation**: Faster to configure than code

## Prerequisites

- **NoETL Server**: Running on localhost:8083
- **PostgreSQL**: Running on localhost:54321, database `demo_noetl`
- **Credential**: `pg_local` registered with connection details
- **Python Package**: `psycopg` must be installed in worker environment

### Installing psycopg

The worker environment needs psycopg installed:

```bash
# In NoETL virtual environment
pip install psycopg[binary]

# Or add to requirements.txt
echo "psycopg[binary]" >> requirements.txt
```

## Usage

### 1. Register Playbook
```bash
.venv/bin/noetl register \
  tests/fixtures/playbooks/python_psycopg/http_to_postgres_bulk/http_to_postgres_bulk_python.yaml \
  --host localhost --port 8083
```

### 2. Execute Playbook
```bash
.venv/bin/noetl execute playbook \
  "tests/fixtures/playbooks/python_psycopg/http_to_postgres_bulk/http_to_postgres_bulk_python" \
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
- **HTTP Response**: 100 posts from JSONPlaceholder API
- **Python Result**:
  ```json
  {
    "inserted": 100,
    "total": 100,
    "message": "Successfully inserted 100 posts"
  }
  ```
- **PostgreSQL Count**: 100 records in `http_posts` table

## Known Issues

### 1. psycopg Not Found
**Symptom**: `No module named 'psycopg'` error during bulk_insert step

**Cause**: psycopg not installed in worker Python environment

**Solution**:
```bash
# Activate NoETL virtual environment
source .venv/bin/activate

# Install psycopg
pip install psycopg[binary]

# Restart worker
task noetl:local:stop
task noetl:local:start
```

### 2. Connection Refused
**Symptom**: PostgreSQL connection refused during bulk_insert

**Cause**: PostgreSQL not running or incorrect credentials

**Solution**:
```bash
# Start PostgreSQL
docker compose up -d

# Verify pg_local credential exists
curl http://localhost:8083/api/credentials | jq '.[] | select(.name=="pg_local")'
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
# Extract posts from HTTP response
posts = []
if isinstance(http_data, dict) and 'data' in http_data:
    posts = http_data['data']  # Access the data array
```

### Bulk Insert Logic
```python
for post in posts:
    cursor.execute(
        """
        INSERT INTO public.http_posts (post_id, user_id, title, body)
        VALUES (%s, %s, %s, %s)
        """,
        (post['id'], post['userId'], post['title'], post['body'])
    )
conn.commit()  # Single commit for all inserts
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

### Check Python Result
```bash
# Get bulk_insert result
PGPASSWORD=demo psql -h localhost -p 54321 -U demo -d demo_noetl -c \
  "SELECT result FROM noetl.event 
   WHERE execution_id = '$execution_id' 
   AND node_name = 'bulk_insert' 
   AND event_type = 'step_result';"
```

## Comparison: Custom Python vs Transfer Tool

| Feature | Custom Python (this playbook) | Transfer Tool (data_transfer version) |
|---------|-------------------------------|---------------------------------------|
| **Configuration** | Imperative Python code | Declarative YAML |
| **Code Required** | ~50 lines Python | None |
| **Connection Mgmt** | Manual (with psycopg) | Automatic |
| **Chunking** | Must implement manually | Built-in (configurable) |
| **Transactions** | Must manage manually | Automatic per chunk |
| **Error Handling** | Must implement manually | Built-in retry logic |
| **Maintainability** | Medium (requires code updates) | High (no code) |
| **Flexibility** | Full control over logic | Limited to mapping |
| **Performance** | Depends on implementation | Optimized by framework |
| **Use Case** | Complex transformations, custom logic | Standard bulk transfers |
| **Learning Curve** | Medium (Python + driver) | Low (YAML only) |
| **Driver Features** | Access to psycopg COPY, cursors | Limited to INSERT |

## Related Playbooks

- **http_to_postgres_bulk**: Same use case using transfer tool (declarative approach)
- **http_to_databases**: Multi-database transfer using iterator pattern
- **snowflake_postgres**: Database-to-database transfer using transfer tool
- **control_flow_workbook**: Workbook pattern for reusable tasks

## File Structure

```
tests/fixtures/playbooks/python_psycopg/http_to_postgres_bulk/
├── http_to_postgres_bulk_python.yaml    # Main playbook definition
└── README.md                      # This file
```

## Metadata

- **API Version**: noetl.io/v1
- **Kind**: Playbook
- **Name**: http_to_postgres_bulk_python
- **Path**: tests/fixtures/playbooks/python_psycopg/http_to_postgres_bulk_python
- **Approach**: Imperative (custom Python with psycopg)
- **Last Updated**: 2025-11-09
- **Status**: Tested and working (100 records successfully inserted with psycopg3)
