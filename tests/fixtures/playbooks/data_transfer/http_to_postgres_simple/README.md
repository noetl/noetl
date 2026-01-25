# HTTP to PostgreSQL Simple - Python Batch INSERT Pattern

## Overview

This playbook demonstrates how to fetch data from an HTTP API, transform it using Python, and bulk-insert it into PostgreSQL using batch INSERT statements. Unlike the iterator pattern which processes records one-by-one, this pattern:

1. Fetches all data at once
2. Transforms it in Python into SQL INSERT statements
3. Executes all INSERTs in a single PostgreSQL command using Jinja2's `join` filter

This is ideal for moderate-sized datasets (hundreds to thousands of records) where you want simple, readable code without the overhead of looping.

## Usage

```bash
# Register the playbook
noetl playbook register tests/fixtures/playbooks/data_transfer/http_to_postgres_simple

# Execute the playbook
noetl execution create tests/fixtures/playbooks/data_transfer/http_to_postgres_simple

# Or execute with local PostgreSQL credentials explicitly
noetl execute playbook \
  "tests/fixtures/playbooks/data_transfer/http_to_postgres_simple" \
  --host localhost --port 8083 \
  --payload '{"pg_auth": "pg_local"}' --merge
```

## Workflow Steps

### 1. Fetch Data (`fetch_posts`)
- **Tool**: `http`
- **Action**: GET request to `https://jsonplaceholder.typicode.com/posts`
- **Returns**: Array of 100 post objects with `id`, `userId`, `title`, `body`

### 2. Create Table (`create_pg_table`)
- **Tool**: `postgres`
- **Action**: 
  - Creates table `public.http_to_postgres_simple` if not exists
  - Truncates existing data
- **Schema**:
  ```sql
  CREATE TABLE public.http_to_postgres_simple (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    title TEXT,
    body TEXT
  );
  ```

### 3. Transform and Prepare INSERT Statements (`transform_and_insert`)
- **Tool**: `python`
- **Input**: `input_data: "{{ fetch_posts }}"` (references step result directly)
- **Process**:
  1. Receives posts array directly as `input_data` parameter
  2. Escapes single quotes in title and body (replace `'` with `''`)
  3. Generates list of SQL INSERT statements with `ON CONFLICT DO NOTHING`
  4. Returns dictionary with `sql_statements` list and metadata
- **Python Code Pattern**:
  ```python
  def main(input_data):
      posts = input_data if isinstance(input_data, list) else []
      insert_statements = []
      for post in posts:
          title = (post.get('title') or '').replace("'", "''")
          body = (post.get('body') or '').replace("'", "''")
          sql = f"INSERT INTO ... VALUES (...) ON CONFLICT (id) DO NOTHING;"
          insert_statements.append(sql)
          return {'sql_statements': insert_statements, 'count': len(insert_statements)}
  ```
- **Important**: Reference step results directly as `{{ step_name }}`, not `{{ step_name.data }}`. The TaskResultProxy wrapper automatically provides access to the data.
- **Returns**:
  ```json
  {
    "status": "success",
    "sql_statements": ["INSERT INTO ...", "INSERT INTO ...", ...],
    "count": 100
  }
  ```

### 4. Execute Batch INSERT (`execute_inserts`)
- **Tool**: `postgres`
- **Command**: `"{{ transform_and_insert.sql_statements | join('\n') }}"`
- **Process**: 
  - Takes the list of SQL statements from `transform_and_insert.sql_statements`
  - Uses Jinja2 `join` filter to concatenate with newlines
  - Executes all INSERT statements in a single PostgreSQL command
- **Example command**:
  ```sql
  INSERT INTO public.http_to_postgres_simple (id, user_id, title, body) VALUES (1, 1, 'Title 1', 'Body 1') ON CONFLICT (id) DO NOTHING;
  INSERT INTO public.http_to_postgres_simple (id, user_id, title, body) VALUES (2, 1, 'Title 2', 'Body 2') ON CONFLICT (id) DO NOTHING;
  ...
  ```

### 5. Verification Steps
- **verify_data**: Count total records, unique users, max post ID
- **show_sample**: Display first 5 posts for visual verification

## Data Flow Patterns

### Python Tool `data` Parameter
The Python tool receives data through the `data` configuration field:

```yaml
- step: transform_and_insert
  tool: python
  code: |
    def main(input_data):
        # input_data contains the value from args.input_data below
        posts = input_data if isinstance(input_data, list) else []
        ...
  args:
    input_data: "{{ fetch_posts }}"  # Pass step result directly (not .data)
```

**Important**: Reference step results as `{{ step_name }}`, not `{{ step_name.data }}`. NoETL's TaskResultProxy automatically unwraps the data when passing to Python functions.

### Jinja2 Join Filter for SQL Batching
The `join` filter concatenates list elements into a single string:

```yaml
command: "{{ transform_and_insert.sql_statements | join('\n') }}"
```

This transforms:
```python
['INSERT INTO ...;', 'INSERT INTO ...;', ...]
```

Into:
```sql
INSERT INTO ...;
INSERT INTO ...;
...
```

## Expected Results

After successful execution:
- **Table**: `public.http_to_postgres_simple`
- **Records**: 100 posts
- **Unique users**: 10 (user IDs 1-10)
- **Max post ID**: 100

### Verification Queries

```sql
-- Total records
SELECT COUNT(*) FROM public.http_to_postgres_simple;
-- Expected: 100

-- Check unique users
SELECT COUNT(DISTINCT user_id) FROM public.http_to_postgres_simple;
-- Expected: 10

-- View sample data
SELECT * FROM public.http_to_postgres_simple ORDER BY id LIMIT 5;

-- Max post ID
SELECT MAX(id) FROM public.http_to_postgres_simple;
-- Expected: 100
```

## Pattern Comparison: Batch vs Iterator

### This Pattern (Batch INSERT with Python)
**Advantages**:
- Simple, readable code
- Single database connection
- Efficient for moderate data volumes (hundreds to thousands of records)
- Full control over SQL generation in Python
- Easy to add complex transformations or validations

**Best for**:
- Datasets that fit comfortably in memory
- When you need custom SQL logic (upserts, conditional inserts)
- When transformation logic is more complex than simple mapping

**Example**: 
```yaml
- tool: python
  code: "def main(input_data): return {'sql_statements': [...]}"
  data:
    input_data: "{{ source_data }}"

- tool: postgres
  command: "{{ transform_step.sql_statements | join('\n') }}"
```

### http_to_postgres_iterator Pattern
**Advantages**:
- Processes records individually
- Lower memory footprint for large datasets
- Built-in support for nested task execution
- Better for streaming or continuous processing

**Best for**:
- Very large datasets that don't fit in memory
- When you need to process each record independently
- When downstream steps depend on individual record processing

**Example**:
```yaml
- tool: iterator
  items: "{{ fetch_data.data }}"
  nested_tasks:
    - tool: postgres
      command: "INSERT INTO ... VALUES ({{ item.id }}, ...);"
```

### Choosing Between Patterns

| Criteria | Batch (This Playbook) | Iterator |
|----------|----------------------|----------|
| Dataset size | < 10,000 records | Any size |
| Memory usage | Higher | Lower |
| Complexity | Simpler | More complex |
| Performance | Faster for small-medium datasets | Better for large datasets |
| SQL control | Full (Python) | Template-based |
| Error handling | Batch failure | Per-record failure |

## Technical Notes

### Python Function Signature
The Python tool supports multiple function signatures:
```python
# Recommended: single parameter
def main(input_data):
    # input_data receives data.input_data from YAML
    pass

# No parameters (access context directly)
def main():
    # Access context through globals
    pass

# Keyword arguments
def main(**kwargs):
    # Receives all data fields as kwargs
    pass
```

### SQL String Escaping
Single quotes in text fields must be escaped for SQL:
```python
title = post.get('title', '').replace("'", "''")
```

Postgres uses `''` (two single quotes) to represent a literal single quote in strings.

### ON CONFLICT Handling
Using `ON CONFLICT (id) DO NOTHING` ensures:
- Idempotent execution (can re-run safely)
- No errors on duplicate primary keys
- First insert wins (doesn't update existing records)

Alternative: `ON CONFLICT (id) DO UPDATE SET ...` for upsert behavior.

## Troubleshooting

### Issue: Python Step Fails with `'NoneType' object has no attribute 'get'`
**Cause**: Incorrect template reference - using `{{ step.data }}` instead of `{{ step }}`.

**Solution**: Reference step results directly without `.data`:
```yaml
args:
  input_data: "{{ fetch_posts }}"     # ✓ Correct
  input_data: "{{ fetch_posts.data }}" # ✗ Wrong - renders as string "[{...}]"
```

### Issue: SQL Syntax Error with Single Quotes
**Cause**: Text fields contain unescaped single quotes.

**Solution**: Escape single quotes in Python:
```python
title = post.get('title', '').replace("'", "''")
```

### Issue: Duplicate Key Violations
**Cause**: Re-running the playbook without truncating table.

**Solution**: Either:
1. Include `TRUNCATE TABLE` in create_pg_table step (current approach)
2. Use `ON CONFLICT (id) DO NOTHING` in INSERT statements (current approach)

Both are implemented in this playbook for safety.

### Issue: Empty sql_statements Array
**Cause**: Input data is empty or in unexpected format.

**Debug**:
1. Check fetch_posts step result:
   ```sql
   SELECT data FROM noetl.event 
   WHERE event_type = 'step_result' 
   AND meta->>'step_name' = 'fetch_posts' 
   LIMIT 1;
   ```
2. Verify Python receives data correctly - check worker logs

### Issue: HTTP DNS Error
**Cause**: Network connectivity or DNS resolution issues.

**Solution**: 
- Verify internet connectivity
- Check if `jsonplaceholder.typicode.com` is accessible
- Use alternative test API if needed
- For local testing, mock HTTP response

## Related Playbooks

- **http_to_postgres_iterator**: Uses iterator pattern for record-by-record processing
- **http_to_postgres_bulk**: Uses native PostgreSQL COPY command for maximum performance
- **http_to_databases**: Demonstrates parallel inserts to multiple database types
- **snowflake_postgres**: Similar batch pattern for Snowflake → PostgreSQL transfer

## File Structure

```
http_to_postgres_simple/
├── http_to_postgres_simple.yaml  # Main playbook
└── README.md                      # This file
```

## Metadata

- **Category**: Data Transfer
- **Pattern**: Batch INSERT with Python transformation
- **Tools Used**: http, python, postgres
- **Complexity**: Medium
- **Performance**: Good for < 10K records
- **Memory Usage**: Moderate (all data in memory)
