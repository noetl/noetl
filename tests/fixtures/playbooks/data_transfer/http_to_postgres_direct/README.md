# HTTP to PostgreSQL Direct Save Test

## Purpose

This playbook validates NoETL's declarative `save` block functionality for direct data persistence from HTTP responses to PostgreSQL using **custom SQL statements**. It demonstrates storing array data from an API into a JSONB column by iterating over the response data with Jinja2 templates in the SQL statement.

## What This Validates

- HTTP API data fetching with automatic save block execution
- Declarative `save` block with custom SQL `statement` for bulk JSONB inserts
- Jinja2 templating in SQL statements for array iteration
- JSONB storage in PostgreSQL for flexible schema
- Single-step data ingestion (fetch + store in one HTTP action)
- Automatic connection management via `auth` property

## Architecture

```
┌─────────────────────┐
│  HTTP GET Request   │  Fetch 100 posts from JSONPlaceholder
│  + Automatic Save   │  GET https://jsonplaceholder.typicode.com/posts
└──────────┬──────────┘
           │
           │ save block triggers with Jinja2 loop
           ▼
┌─────────────────────┐
│  Save to Postgres   │  • Iterates over result.data array
│  (JSONB per row)    │  • Generates INSERT for each element
│                     │  • Converts each post to JSONB
│                     │  • Escapes quotes in JSON strings
│                     │  • Executes 100 INSERT statements
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Verification       │  Count records in http_to_postgres_direct
│  (show_count)       │  Expected: 100 records
└─────────────────────┘
```

## Workflow Steps

### 1. create_table
- **Type**: `postgres` tool
- **Purpose**: Create table with JSONB column and truncate existing data
- **Schema**:
  ```sql
  CREATE TABLE IF NOT EXISTS public.http_to_postgres_direct (
    id SERIAL PRIMARY KEY,
    data JSONB NOT NULL,
    fetched_at TIMESTAMPTZ DEFAULT NOW()
  );
  ```
- **Why JSONB**: Flexible storage for API responses without predefined schema

### 2. fetch_and_store
- **Type**: `http` tool with `save` block
- **Purpose**: Fetch data from API and automatically save to PostgreSQL using custom SQL
- **HTTP Configuration**:
  ```yaml
  tool: http
  method: GET
  url: "{{ workload.api_url }}"
  ```
- **Save Configuration**:
  ```yaml
  save:
    storage: postgres
    auth: "{{ workload.pg_credential }}"
    table: http_posts  # Used for context, actual table in statement
    statement: |
      {% for item in result.data %}
      INSERT INTO http_to_postgres_direct (data) VALUES ('{{ item | tojson | replace("'", "''") }}'::jsonb);
      {% endfor %}
  ```
- **Process**:
  1. Executes HTTP GET request
  2. Receives JSON array of 100 posts in `result.data`
  3. Save block renders Jinja2 template with loop
  4. For each post in array:
     - Converts post dict to JSON string with `tojson` filter
     - Escapes single quotes with `replace("'", "''")`
     - Casts to JSONB with `::jsonb`
     - Generates INSERT statement
  5. Executes all 100 INSERT statements as multi-statement SQL
  6. Each post stored as separate JSONB row

### 3. show_count
- **Type**: `postgres` tool
- **Purpose**: Verify 100 records inserted (one per API post)
- **Query**: `SELECT COUNT(*) as records FROM public.http_to_postgres_direct;`

## Key Features

### Save Block with Custom Statement Pattern
The `save` block enables declarative data persistence with custom SQL for complex scenarios:

```yaml
tool: http
method: GET
url: "{{ workload.api_url }}"
save:
  storage: postgres      # Target storage backend
  auth: "{{ ... }}"      # Credential for storage
  table: http_posts      # Context (actual table in statement)
  statement: |           # Custom SQL with Jinja2
    {% for item in result.data %}
    INSERT INTO http_to_postgres_direct (data) 
    VALUES ('{{ item | tojson | replace("'", "''") }}'::jsonb);
    {% endfor %}
```

**Key Points:**
- `statement` field allows custom SQL with full Jinja2 templating
- Access HTTP response via `result.data` context variable
- Use Jinja2 filters: `tojson` (dict→JSON string), `replace` (escape quotes)
- PostgreSQL JSONB casting with `::jsonb`
- Loop constructs generate multiple statements from arrays

### Why Custom Statement Instead of Args?

The postgres save handler has two modes:

1. **Dict Mapping Mode** (with `data`/`args` field):
   ```yaml
   save:
     storage: postgres
     table: users
     data:
       name: "{{ user.name }}"
       email: "{{ user.email }}"
   ```
   - Requires: `data` must be a **dict** with column→value mappings
   - Generates: Single INSERT with mapped columns
   - Best for: Single record inserts with explicit field mapping

2. **Custom Statement Mode** (with `statement` field):
   ```yaml
   save:
     storage: postgres
     statement: |
       {% for item in result.data %}
       INSERT INTO table (col) VALUES ('{{ item | tojson }}'::jsonb);
       {% endfor %}
   ```
   - Allows: Full SQL control with Jinja2 templates
   - Handles: Arrays, complex transformations, bulk operations
   - Best for: Bulk inserts, JSONB storage, custom SQL logic

**This playbook uses statement mode because:**
- HTTP response `result.data` is an **array** (100 posts), not a dict
- Need to iterate over array elements
- Each element inserted as separate JSONB row
- Dict mapping mode would fail: "postgres save requires 'table' and mapping 'data' when no 'statement' provided"

### HTTP Response Structure
```json
{
  "url": "https://jsonplaceholder.typicode.com/posts",
  "data": [  ← Array with 100 elements, each stored as separate JSONB row
    {"id": 1, "userId": 1, "title": "...", "body": "..."},
    {"id": 2, "userId": 1, "title": "...", "body": "..."},
    ... (98 more posts)
  ],
  "status_code": 200,
  "headers": {...},
  "elapsed": 0.06
}
```

### Jinja2 Template Execution
The `statement` field is rendered as Jinja2 template with access to execution context:

**Context Variables:**
- `result.data` - HTTP response data array
- `workload.*` - Playbook workload variables
- `execution_id` - Current execution ID
- Previous step results

**Template Processing:**
```jinja2
{% for item in result.data %}  ← Iterates 100 times
INSERT INTO http_to_postgres_direct (data) 
VALUES ('{{ item | tojson | replace("'", "''") }}'::jsonb);
{% endfor %}
```

**Generated SQL (excerpt):**
```sql
INSERT INTO http_to_postgres_direct (data) VALUES ('{"id":1,"userId":1,"title":"sunt aut facere...","body":"quia et suscipit..."}'::jsonb);
INSERT INTO http_to_postgres_direct (data) VALUES ('{"id":2,"userId":1,"title":"qui est esse","body":"est rerum tempore..."}'::jsonb);
-- ... 98 more INSERT statements
```

### JSONB Benefits
- **Schema Flexibility**: No need to define columns for every field in API response
- **Query Power**: PostgreSQL JSONB supports indexing and complex queries
- **Rapid Development**: Store first, define schema later
- **API Evolution**: Handle changing API responses without migrations
- **Per-Record Storage**: Each API item stored as independent row for easier querying

## Prerequisites

- **NoETL Server**: Running on localhost:8083
- **PostgreSQL**: Running on localhost:54321, database `demo_noetl`
- **Credential**: `pg_local` registered with connection details
- **HTTP Access**: Internet connection to reach JSONPlaceholder API

## Usage

### 1. Register Playbook
```bash
.venv/bin/noetl register \
  tests/fixtures/playbooks/data_transfer/http_to_postgres_direct/http_to_postgres_direct.yaml \
  --host localhost --port 8083
```

### 2. Execute Playbook
```bash
.venv/bin/noetl execute playbook \
  "tests/fixtures/playbooks/data_transfer/http_to_postgres_direct" \
  --host localhost --port 8083 --json
```

### 3. Verify Results
```bash
# Check record count (should be 100 - one row per API post)
PGPASSWORD=demo psql -h localhost -p 54321 -U demo -d demo_noetl \
  -c "SELECT COUNT(*) FROM public.http_to_postgres_direct;"

# View sample JSONB data
PGPASSWORD=demo psql -h localhost -p 54321 -U demo -d demo_noetl \
  -c "SELECT id, data->>'title' as title, fetched_at FROM public.http_to_postgres_direct LIMIT 5;"

# Query within JSONB using operators
PGPASSWORD=demo psql -h localhost -p 54321 -U demo -d demo_noetl \
  -c "SELECT data->>'title' as title, data->>'userId' as user_id FROM public.http_to_postgres_direct WHERE (data->>'userId')::int = 1 LIMIT 5;"
```

## Expected Results

- **Execution Status**: COMPLETED
- **Records Inserted**: 100 (one row per API post, each as JSONB)
- **HTTP Response**: 100 posts from JSONPlaceholder API
- **Each Row**: Contains one post as JSONB document
- **PostgreSQL Query**:
  ```
   records 
  ---------
       100
  ```

## Comparison: Statement Mode vs Other Patterns

| Feature | Statement Mode (this playbook) | Dict Mapping Mode | Iterator Pattern | Transfer Tool |
|---------|-------------------------------|-------------------|------------------|---------------|
| **Approach** | Custom SQL with Jinja2 loop | Declarative column mapping | Per-item iteration | Declarative transfer |
| **Code Complexity** | Medium (SQL + Jinja2) | Minimal (YAML only) | Medium (iterator config) | Low (YAML config) |
| **Data Type** | Array → multiple rows | Dict → single row | Array → multiple rows | Array → multiple rows |
| **Records Inserted** | N (loop count) | 1 | N (array length) | N (array length) |
| **Storage Format** | JSONB per row | Mapped columns or JSONB | Mapped columns | Mapped columns |
| **Schema Required** | No (flexible JSONB) | Depends on mapping | Yes (defined columns) | Yes (defined columns) |
| **SQL Control** | Full (custom SQL) | Limited (generated) | None (generated) | None (generated) |
| **Transformation** | Jinja2 in SQL | Field mapping only | Per-item mapping | Field mapping |
| **Best For** | Bulk JSONB inserts, custom SQL | Single record with mapping | Standard iteration | Standard bulk transfers |
| **Performance** | Good (batch SQL) | Excellent (single op) | Fair (N operations) | Excellent (optimized) |

## Troubleshooting

### 1. Connection Refused
**Symptom**: PostgreSQL connection refused during save

**Cause**: PostgreSQL not running or incorrect credentials

**Solution**:
```bash
# Start PostgreSQL
docker compose up -d

# Verify pg_local credential exists
curl http://localhost:8083/api/credentials | jq '.[] | select(.name=="pg_local")'
```

### 2. HTTP Source Unreachable
**Symptom**: Save fails with HTTP connection error

**Cause**: Cannot reach JSONPlaceholder API

**Solution**:
```bash
# Test API accessibility
curl https://jsonplaceholder.typicode.com/posts

# Check network connectivity
ping jsonplaceholder.typicode.com
```

### 3. Save Block Not Executing
**Symptom**: HTTP step completes but no data in database

**Causes & Solutions**:

1. **Configuration Error**
   - Verify flat structure: `storage: postgres` (not nested `storage: {type: postgres}`)
   - Check `auth` credential reference is valid
   - Ensure `statement` field has valid Jinja2 syntax

2. **Array Data with Dict Mapping Mode**
   - **Error**: "postgres save requires 'table' and mapping 'data' when no 'statement' provided"
   - **Cause**: Using `data` field with array value (dict expected)
   - **Solution**: Use `statement` mode with Jinja2 loop for array data:
     ```yaml
     save:
       storage: postgres
       statement: |
         {% for item in result.data %}
         INSERT INTO table (col) VALUES ('{{ item | tojson }}'::jsonb);
         {% endfor %}
     ```

3. **Worker Logs Check**
   ```bash
   # Check for save execution
   grep -A 20 "SAVE.EXECUTOR: execute_save_task CALLED" logs/worker.log | tail -50
   
   # Check for postgres save handler
   grep -A 10 "SAVE.POSTGRES: handle_postgres_storage CALLED" logs/worker.log | tail -30
   
   # Look for errors
   grep -i "error.*save\|save.*error" logs/worker.log | tail -20
   ```

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

### Check Save Operation
```bash
# Verify save block was called
grep "About to call save plugin" logs/worker.log | tail -5

# Check what kind was detected (should be 'postgres', not 'event')
grep "Extracted save config with kind=" logs/worker.log | tail -5

# View rendered data passed to save handler
grep "SAVE.POSTGRES: rendered_data=" logs/worker.log | tail -1
```

## Technical Notes

### Save Block Architecture

1. **Worker Detection**: When HTTP action completes, worker checks for `save` block in action config
2. **Context Preparation**: Worker creates context with `result` variable containing HTTP response
3. **Save Executor**: Calls `execute_save_task()` from `noetl.plugin.shared.storage`
4. **Config Extraction**: Parses `save` block structure (flat vs nested, storage type)
5. **Storage Delegation**: Routes to `handle_postgres_storage()` for postgres saves
6. **Statement Rendering**: Renders Jinja2 template in `statement` field with execution context
7. **SQL Execution**: Passes rendered SQL to postgres plugin for execution

### Flat vs Nested Save Structure

**Flat Structure (Correct)**:
```yaml
save:
  storage: postgres      # String value
  auth: "{{ ... }}"
  statement: "..."
```
- Config parser extracts `kind='postgres'` from string value
- Compatible with statement mode and dict mapping mode

**Nested Structure (Incorrect for this use case)**:
```yaml
save:
  storage:              # Dict value
    type: postgres      # Would work but 'tool' doesn't
    statement: "..."
```
- Config parser looks for `type` field in dict
- Falls back to `kind='event'` if not found
- Previous error was using `tool` instead of `type`

### Jinja2 Filters for SQL Safety

| Filter | Purpose | Example |
|--------|---------|---------|
| `tojson` | Convert dict/list to JSON string | `{{ item \| tojson }}` |
| `replace("'", "''")` | Escape single quotes for SQL | `{{ text \| replace("'", "''") }}` |
| `string` | Convert to string | `{{ value \| string }}` |
| `safe` | Mark as safe HTML (use cautiously) | `{{ html \| safe }}` |

**Critical**: Always escape quotes when embedding Jinja2 values in SQL strings to prevent SQL injection and syntax errors.

## Related Playbooks

- **`http_to_postgres_bulk/`** - Transfer tool pattern for structured data with column mapping
- **`http_iterator_save_postgres/`** - Iterator pattern with per-item save blocks and explicit column mapping
- **`python_psycopg/http_to_postgres_bulk/`** - Custom Python implementation using psycopg3 for advanced control

Each pattern serves different use cases - choose based on your requirements for control, complexity, and performance.
````
```bash
# Get fetch_and_store result
PGPASSWORD=demo psql -h localhost -p 54321 -U demo -d demo_noetl -c \
  "SELECT result FROM noetl.event 
   WHERE execution_id = '$execution_id' 
   AND node_name = 'fetch_and_store' 
   AND event_type = 'step_result';"
```

## Advanced JSONB Queries

Once data is stored as JSONB, you can query it flexibly:

```sql
-- Extract all post titles
SELECT jsonb_array_elements(data)->>'title' as title 
FROM public.http_posts;

-- Filter posts by userId
SELECT jsonb_array_elements(data) as post
FROM public.http_posts
WHERE (jsonb_array_elements(data)->>'userId')::int = 1;

-- Count posts by user
SELECT 
  jsonb_array_elements(data)->>'userId' as user_id,
  COUNT(*) as post_count
FROM public.http_posts
GROUP BY jsonb_array_elements(data)->>'userId';

-- Create GIN index for faster queries
CREATE INDEX idx_http_posts_data ON public.http_posts USING GIN (data);
```

## Related Playbooks

- **http_to_postgres_bulk**: Uses transfer tool for structured row-by-row insertion
- **http_to_postgres_bulk_python**: Custom Python with psycopg for bulk operations  
- **http_to_postgres_iterator**: Iterator pattern for per-item processing
- **http_to_databases**: Multi-database transfer demonstration
- **save_storage_test**: Declarative save blocks across multiple storage types

## When to Use This Pattern

### Choose Direct Save with JSONB When:
1. **Rapid Prototyping**: Need to store data quickly without defining schema
2. **Flexible Schema**: API response structure changes frequently
3. **Document Storage**: Data is naturally hierarchical/nested
4. **Raw Archive**: Want to preserve original API response for later processing
5. **Exploratory Analysis**: Decide on structure after analyzing stored data

### Choose Other Patterns When:
1. **Relational Queries**: Need JOIN operations with other tables
2. **Performance**: Frequent queries on specific fields (use columns + indexes)
3. **Data Quality**: Want schema validation and type checking
4. **Legacy Systems**: Integrating with existing relational schema
5. **Analytics**: BI tools work better with columnar data

## File Structure

```
tests/fixtures/playbooks/data_transfer/http_to_postgres_direct/
├── http_to_postgres_direct.yaml    # Main playbook definition
└── README.md                        # This file
```

## Metadata

- **API Version**: noetl.io/v1
- **Kind**: Playbook
- **Path**: tests/fixtures/playbooks/data_transfer/http_to_postgres_direct
- **Pattern**: Declarative save block with JSONB storage (pattern demonstration)
- **Last Updated**: 2025-11-09
- **Status**: Pattern Reference - Save block structure defined per save_storage_test examples, awaiting HTTP plugin save integration. Table creation works; use transfer tool or Python patterns for active data loading.
