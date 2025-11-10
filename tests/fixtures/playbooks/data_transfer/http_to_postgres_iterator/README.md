# HTTP to PostgreSQL Iterator Test

## Overview

This playbook demonstrates fetching data from an HTTP API and inserting it into PostgreSQL using NoETL's iterator pattern. It showcases the iterator tool for batch processing of API responses with individual database inserts.

## Test Purpose

Validates:
- HTTP API data fetching (GET request)
- Iterator-based sequential processing
- PostgreSQL INSERT operations with base64-encoded commands
- Dollar-quoted strings in SQL for handling special characters
- Complete workflow from API fetch to database verification

## Architecture

```
HTTP API (JSONPlaceholder)
    ↓
Fetch 100 Posts
    ↓
Iterator (Sequential)
    ↓
PostgreSQL INSERT (100 operations)
    ↓
Verify Count
```

## Prerequisites

- **Credentials Required:**
  - `pg_local`: PostgreSQL local database credentials

- **Database Access:**
  - PostgreSQL: localhost:54321
  - Schema: public

## Usage

### Register the Playbook

```bash
.venv/bin/noetl catalog register playbook \
  tests/fixtures/playbooks/data_transfer/http_to_postgres_iterator/http_to_postgres_iterator.yaml \
  --host localhost --port 8083
```

### Execute the Playbook

```bash
.venv/bin/noetl execute playbook \
  "examples/data_transfer/http_to_postgres_iterator" \
  --host localhost --port 8083 \
  --payload '{"pg_auth": "pg_local"}' \
  --merge
```

### Execute with Custom API URL

```bash
.venv/bin/noetl execute playbook \
  "examples/data_transfer/http_to_postgres_iterator" \
  --payload '{"api_url": "https://jsonplaceholder.typicode.com/users", "pg_auth": "pg_local"}' \
  --merge \
  --host localhost --port 8083
```

## Workflow Steps

### 1. **start**
- Entry point for workflow execution

### 2. **create_table**
- Drops existing `http_to_postgres_iterator` table if present
- Creates new table with columns:
  - `id` - SERIAL PRIMARY KEY
  - `post_id` - INTEGER (from API)
  - `user_id` - INTEGER (from API)
  - `title` - TEXT (post title)
  - `body` - TEXT (post content)
  - `fetched_at` - TIMESTAMPTZ (auto-populated timestamp)

### 3. **fetch_http_data**
- Tool: HTTP GET request
- URL: `https://jsonplaceholder.typicode.com/posts`
- Returns: Array of 100 post objects
- Each post contains: `id`, `userId`, `title`, `body`

### 4. **insert_posts**
- Tool: Iterator (sequential mode)
- Collection: `{{ fetch_http_data.data }}` (100 posts)
- Element variable: `item`
- Nested task: PostgreSQL INSERT
- Uses dollar-quoted strings (`$$`) to safely handle special characters in title/body
- Base64-encoded command execution (automatic via iterator)
- Result: 100 individual INSERT operations

### 5. **show_count**
- Verification query counting total records
- Expected result: 100 records

### 6. **end**
- Workflow completion marker

## Data Flow Patterns

### HTTP Result Reference

The HTTP tool returns data in this structure:
```
fetch_http_data.data = [array of posts]
```

Reference in iterator:
```yaml
collection: "{{ fetch_http_data.data }}"
```

### Iterator with Nested PostgreSQL Task

```yaml
- step: insert_posts
  tool: iterator
  collection: "{{ fetch_http_data.data }}"
  element: item
  task:  # Nested task definition
    tool: postgres
    auth: "{{ workload.pg_auth }}"
    command: |
      INSERT INTO table (...)
      VALUES ({{ item.id }}, $${{ item.title }}$$);
```

### Dollar-Quoted Strings

PostgreSQL dollar quoting (`$$`) is used to safely handle text containing single quotes:
```sql
$${{ item.title }}$$  -- Handles: It's a "special" title
```

This prevents SQL injection and escaping issues with user-generated content.

## Expected Results

- HTTP API fetches 100 posts successfully
- Iterator processes all 100 posts sequentially
- Each post results in 1 successful INSERT operation
- Final count: 100 records in database
- Execution completes with `playbook_completed` event

## Technical Notes

### Iterator Base64 Encoding

The iterator automatically encodes nested task `command` fields to base64 before execution. This ensures PostgreSQL commands are properly handled when executing tasks directly within the worker process (without going through the queue publisher).

The encoding happens in `noetl/plugin/controller/iterator/execution.py` via `_encode_nested_task()`.

### Sequential vs Async Mode

This playbook uses sequential mode (`mode: sequential` is the default) to ensure:
- Predictable INSERT order
- Simplified debugging
- Database connection pooling efficiency

For higher throughput with many items, consider `mode: async` with `concurrency: 10`.

### Error Handling

If any single INSERT fails:
- The iterator continues processing remaining items
- Failed items are tracked in the result
- Overall status remains "success" unless all items fail

For stricter error handling, set iterator `stop_on_error: true` (if supported).

## Verification Queries

### Check Record Count
```sql
SELECT COUNT(*) as total_records 
FROM public.http_to_postgres_iterator;
-- Expected: 100
```

### View Sample Data
```sql
SELECT post_id, user_id, 
       LEFT(title, 40) as title, 
       LEFT(body, 50) as body,
       fetched_at
FROM public.http_to_postgres_iterator 
LIMIT 5;
```

### Check Data Range
```sql
SELECT 
  MIN(post_id) as first_post,
  MAX(post_id) as last_post,
  COUNT(DISTINCT user_id) as unique_users,
  MIN(fetched_at) as earliest_fetch,
  MAX(fetched_at) as latest_fetch
FROM public.http_to_postgres_iterator;
-- Expected: first_post=1, last_post=100, unique_users=10
```

### Verify User Distribution
```sql
SELECT user_id, COUNT(*) as posts_per_user
FROM public.http_to_postgres_iterator
GROUP BY user_id
ORDER BY user_id;
-- Expected: 10 posts per user (users 1-10)
```

## Key Learnings

1. **HTTP Data Access**: Use `{{ step_name.data }}` to access HTTP response body array
2. **Iterator Syntax**: Use `task:` block for nested action definition
3. **PostgreSQL Dollar Quotes**: Use `$$text$$` for strings with special characters
4. **Base64 Encoding**: Iterator automatically handles command encoding for nested tasks
5. **Sequential Processing**: Default mode processes items one at a time in order
6. **Template Variables**: Iterator exposes `{{ element_name }}` in nested task context

## Troubleshooting

### No Data Inserted (Empty Collection)

**Symptom**: Iterator completes but COUNT returns 0

**Causes**:
1. Incorrect collection reference (e.g., `{{ steps.fetch_http_data.data }}` instead of `{{ fetch_http_data.data }}`)
2. HTTP API returned empty array
3. HTTP fetch failed but error was silent

**Solution**:
- Check fetch_http_data result in events: Should show array with 100 items
- Use correct reference: `{{ fetch_http_data.data }}`
- Verify API URL is accessible

### SQL Syntax Errors in Iterator

**Symptom**: Each iterator iteration fails with SQL syntax error

**Causes**:
1. Special characters in title/body breaking SQL
2. Missing dollar quotes around text fields
3. Template rendering issues with item properties

**Solution**:
- Use dollar quotes: `$${{ item.title }}$$`
- Check item structure matches expected fields (`id`, `userId`, `title`, `body`)
- Review SQL command syntax in iterator task

### Iterator Shows Success But INSERTs Failed

**Symptom**: Iterator completes, but data not in database

**Causes**:
1. Wrong table name
2. Missing table (create_table step failed)
3. Database connection issues
4. Transaction not committed

**Solution**:
- Check create_table step completed successfully
- Verify table exists: `\d public.http_to_postgres_iterator`
- Check PostgreSQL logs for connection errors
- Ensure auth credential is valid

### Performance Issues (Slow Execution)

**Symptom**: Iterator takes very long to process 100 items

**Optimization**:
- Use `mode: async` with `concurrency: 10` for parallel processing
- Batch multiple INSERTs into single command
- Use bulk transfer tool instead of iterator for large datasets

## Comparison with Other Patterns

### Iterator Pattern (This Playbook)
- **Best for**: Individual item processing, custom logic per item
- **Pros**: Flexible, handles errors per item, easy to debug
- **Cons**: Slower for large datasets (100+ items)

### Bulk Transfer Pattern
- **Best for**: Large datasets (1000+ records), simple mappings
- **Pros**: Much faster, optimized for throughput
- **Cons**: Less flexible, all-or-nothing on errors

### Python Batch Pattern
- **Best for**: Complex transformations, aggregations
- **Pros**: Full Python power, single database transaction
- **Cons**: All processing in Python, memory constraints

Choose iterator when you need per-item control and can accept slower throughput.

## Files

- `http_to_postgres_iterator.yaml` - Main playbook
- `README.md` - This documentation

## Related Playbooks

- `http_to_databases/` - Multi-database distribution with iterator
- `http_to_postgres_transfer/` - Bulk transfer pattern (faster for large datasets)
- `http_to_postgres_bulk/` - Python-based bulk processing
