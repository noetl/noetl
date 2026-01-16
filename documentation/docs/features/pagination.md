# HTTP Pagination

NoETL provides automatic pagination support for HTTP actions, allowing you to fetch all pages of data with declarative configuration.

## Overview

Many REST APIs return data in pages to limit response sizes. NoETL's pagination feature automatically:
- Makes sequential HTTP requests while data remains
- Merges results across pages
- Handles retry for failed requests
- Prevents infinite loops with safety limits

## Quick Start

```yaml
- step: fetch_all_data
  tool: http
  url: "{{ api_url }}/data"
  params:
    page: 1
    pageSize: 100
  loop:
    pagination:
      type: response_based
      continue_while: "{{ response.data.paging.hasMore == true }}"
      next_page:
        params:
          page: "{{ (response.data.paging.page | int) + 1 }}"
      merge_strategy: append
      merge_path: data.data
```

This configuration:
1. Starts with `page=1`
2. Fetches data from API
3. Checks if `response.data.paging.hasMore` is true (note: `response.data` accesses the API response)
4. If true, increments page number and repeats
5. Merges all data arrays into single result (using `data.data` to extract from wrapper then API structure)

## Pagination Patterns

### Page Number Pagination

Most common pattern using page numbers:

```yaml
- step: fetch_assessments
  tool: http
  url: "{{ api_url }}/assessments"
  params:
    page: 1
    pageSize: 100
  loop:
    pagination:
      type: response_based
      continue_while: "{{ response.data.paging.hasMore == true }}"
      next_page:
        params:
          page: "{{ (response.data.paging.page | int) + 1 }}"
          pageSize: "{{ response.data.paging.pageSize }}"
      merge_strategy: append
      merge_path: data.data
      max_iterations: 50
```

**API Response Format:**
```json
{
  "data": [{"id": 1}, {"id": 2}, ...],
  "paging": {
    "hasMore": true,
    "page": 1,
    "pageSize": 100,
    "total": 350
  }
}
```

**Note:** The HTTP executor wraps responses as `{id, status, data: <api_response>}`, which is why we use:
- `response.data.paging.hasMore` (not `response.paging.hasMore`)
- `merge_path: data.data` (not `merge_path: data`)

### Offset-Based Pagination

Uses offset and limit parameters:

```yaml
- step: fetch_users
  tool: http
  url: "{{ api_url }}/users"
  params:
    offset: 0
    limit: 100
  loop:
    pagination:
      type: response_based
      continue_while: "{{ response.data.has_more == true }}"
      next_page:
        params:
          offset: "{{ (response.data.offset | int) + (response.data.limit | int) }}"
          limit: "{{ response.data.limit }}"
      merge_strategy: append
      merge_path: data.users
```

**API Response Format:**
```json
{
  "users": [{"id": 1}, {"id": 2}, ...],
  "has_more": true,
  "offset": 0,
  "limit": 100,
  "total": 850
}
```

### Cursor-Based Pagination

Uses opaque continuation tokens:

```yaml
- step: fetch_events
  tool: http
  url: "{{ api_url }}/events"
  params:
    limit: 100
  loop:
    pagination:
      type: response_based
      continue_while: "{{ response.data.next_cursor is not none and response.data.next_cursor != '' }}"
      next_page:
        params:
          cursor: "{{ response.data.next_cursor }}"
          limit: "{{ response.data.limit }}"
      merge_strategy: append
      merge_path: data.events
```

**API Response Format:**
```json
{
  "events": [{"id": 1}, {"id": 2}, ...],
  "next_cursor": "eyJpZCI6MTAwfQ==",
  "limit": 100
}
```

## Configuration Reference

### `loop.pagination` Block

#### `type` (string, required)

Pagination type identifier. Currently supported:
- `response_based` - Continuation based on response inspection

#### `continue_while` (expression, required)

Jinja2 expression evaluated after each request to determine if pagination should continue.

**Available Variables:**
- `{{ response }}` - Full HTTP executor result with structure `{id, status, data: <api_response>}`
- `{{ iteration }}` - Current iteration number (0-based)
- `{{ accumulated }}` - Merged results so far

**Important:** HTTP responses are wrapped by the executor. Access API response fields via `response.data.*`:

**Examples:**
```yaml
# Boolean flag - note response.data.paging
continue_while: "{{ response.data.paging.hasMore == true }}"

# Next cursor exists - note response.data.next_cursor
continue_while: "{{ response.data.next_cursor is not none }}"

# Combined conditions
continue_while: "{{ response.data.has_more and iteration < 100 }}"
```

#### `next_page` (object, required)

Defines how to update the HTTP request for the next page.

**Subfields:**

##### `next_page.params` (object, optional)

Query parameters to update/add for next request. Access API response via `response.data.*`:

```yaml
next_page:
  params:
    page: "{{ (response.data.paging.page | int) + 1 }}"
    cursor: "{{ response.data.next_page_token }}"
```

##### `next_page.body` (object, optional)

Request body modifications for POST/PUT requests. Access API response via `response.data.*`:

```yaml
next_page:
  body:
    offset: "{{ (response.data.offset | int) + (response.data.limit | int) }}"
```

##### `next_page.headers` (object, optional)

Header modifications (useful for cursor tokens). Access API response via `response.data.*`:

```yaml
next_page:
  headers:
    X-Continuation-Token: "{{ response.data.continuation_token }}"
```

#### `merge_strategy` (string, required)

How to combine results across pages:

- **`append`** - Concatenate arrays at `merge_path`
  ```python
  # Page 1: [1, 2, 3]
  # Page 2: [4, 5, 6]
  # Result: [1, 2, 3, 4, 5, 6]
  ```

- **`extend`** - Flatten nested arrays
  ```python
  # Page 1: [[1, 2], [3, 4]]
  # Page 2: [[5, 6], [7, 8]]
  # Result: [1, 2, 3, 4, 5, 6, 7, 8]
  ```

- **`replace`** - Keep only last response
  ```python
  # Page 1: {"data": [1, 2, 3]}
  # Page 2: {"data": [4, 5, 6]}
  # Result: {"data": [4, 5, 6]}
  ```

- **`collect`** - Store all responses as array
  ```python
  # Page 1: {"data": [1, 2], "page": 1}
  # Page 2: {"data": [3, 4], "page": 2}
  # Result: [
  #   {"data": [1, 2], "page": 1},
  #   {"data": [3, 4], "page": 2}
  # ]
  ```

#### `merge_path` (string, optional)

JSONPath to data array in response. Uses dot notation to navigate through the HTTP executor wrapper and API response structure.

**Important:** HTTP responses are wrapped as `{id, status, data: <api_response>}`, so paths must account for this:

```yaml
merge_path: "data.data"           # response.data['data'] - API response has "data" field
merge_path: "data.result.items"   # response.data['result']['items']
merge_path: "data.users"          # response.data['users']
```

If omitted, merges entire response including wrapper.

#### `max_iterations` (integer, optional)

Safety limit to prevent infinite loops. Default: 1000

```yaml
max_iterations: 50  # Stop after 50 pages
```

### `loop.pagination.retry` Block (optional)

Retry configuration applied to each HTTP request:

#### `max_attempts` (integer, optional)

Number of retry attempts per request. Default: 1 (no retry)

```yaml
retry:
  max_attempts: 3  # Try up to 3 times
```

#### `backoff` (string, optional)

Backoff strategy: `fixed` or `exponential`. Default: `fixed`

```yaml
retry:
  backoff: exponential  # 1s, 2s, 4s, 8s...
```

#### `initial_delay` (number, optional)

Seconds to wait before first retry. Default: 1

```yaml
retry:
  initial_delay: 0.5  # Wait 500ms
```

#### `max_delay` (number, optional)

Maximum backoff delay in seconds. Default: 60

```yaml
retry:
  max_delay: 10  # Cap at 10 seconds
```

## Complete Example

```yaml
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: paginated_data_fetch
  path: examples/pagination

workload:
  api_url: https://api.example.com
  api_key: "{{ secret.API_KEY }}"

workflow:
  - step: start
    next:
      - step: fetch_all_records

  - step: fetch_all_records
    desc: Fetch all records with automatic pagination
    tool: http
    url: "{{ workload.api_url }}/v1/records"
    method: GET
    headers:
      Authorization: "Bearer {{ workload.api_key }}"
    params:
      page: 1
      pageSize: 100
      sortBy: created_at
    loop:
      pagination:
        type: response_based
        continue_while: "{{ response.data.pagination.hasMore == true }}"
        next_page:
          params:
            page: "{{ (response.data.pagination.page | int) + 1 }}"
            pageSize: "{{ response.data.pagination.pageSize }}"
        merge_strategy: append
        merge_path: data.data
        max_iterations: 100
        retry:
          max_attempts: 3
          backoff: exponential
          initial_delay: 1
          max_delay: 30
    next:
      - step: save_to_database

  - step: save_to_database
    desc: Save all fetched records
    tool: postgres
    auth:
      type: postgres
      credential: prod_db
    command: |
      INSERT INTO records (id, name, value, created_at)
      SELECT
        (data->>'id')::int,
        data->>'name',
        data->>'value',
        (data->>'created_at')::timestamp
      FROM jsonb_array_elements('{{ fetch_all_records | tojson }}'::jsonb) AS data
      ON CONFLICT (id) DO UPDATE SET
        name = EXCLUDED.name,
        value = EXCLUDED.value,
        created_at = EXCLUDED.created_at
    next:
      - step: end

  - step: end
    desc: Workflow complete
```

## Best Practices

### 1. Always Set max_iterations

Prevent infinite loops from API bugs:

```yaml
pagination:
  max_iterations: 100  # Reasonable limit
```

### 2. Use Retry for Production

APIs can be flaky, retry improves reliability:

```yaml
pagination:
  retry:
    max_attempts: 3
    backoff: exponential
```

### 3. Choose Appropriate Page Sizes

Balance between performance and memory:

```yaml
params:
  pageSize: 100  # Not too large, not too small
```

### 4. Validate Merged Results

Add validation step after pagination:

```yaml
- step: validate_data
  tool: python
  code: |
    def main(input_data):
        data = input_data['fetch_all_records']
        assert len(data) > 0, "No data fetched"
        assert len(data) < 10000, "Suspiciously large dataset"
        return {'count': len(data)}
```

### 5. Handle Empty Results

Check for data existence, accounting for HTTP wrapper:

```yaml
continue_while: "{{ response.data.data is defined and response.data.data | length > 0 and response.data.hasMore }}"
```

## HTTP Response Structure

**Critical:** The HTTP executor wraps all responses with metadata before passing them to pagination logic:

```python
# HTTP Executor Output
{
  "id": "uuid-task-id",
  "status": "success",
  "data": {
    # Your actual API response here
    "data": [...],
    "paging": {...}
  }
}
```

This means:
- Access API fields via `response.data.*` in templates
- Use `merge_path: data.data` to extract arrays (first `data` is executor wrapper, second is API field)
- Templates like `{{ response.data.paging.hasMore }}` (not `{{ response.paging.hasMore }}`)

**Example mapping:**

| API Response Field | Template Path |
|-------------------|---------------|
| `response.data` | `response.data.data` |
| `response.paging.hasMore` | `response.data.paging.hasMore` |
| `response.users` | `response.data.users` |
| `response.next_cursor` | `response.data.next_cursor` |

## Troubleshooting

### Pagination Stops Early

**Problem:** Fetching fewer items than expected

**Solutions:**
- Check `continue_while` expression logic - remember to use `response.data.*`
- Verify API response structure matches expectations
- Verify `merge_path` correctly navigates through HTTP wrapper (e.g., `data.data` not just `data`)
- Check logs for evaluation errors

### Infinite Loop

**Problem:** Pagination never stops

**Solutions:**
- Ensure `continue_while` eventually becomes false
- Set reasonable `max_iterations` limit
- Check if API `hasMore` flag is accurate
- Verify you're accessing the correct path: `response.data.hasMore` not `response.hasMore`

### Merge Errors

**Problem:** "Failed to extract merge_path"

**Solutions:**
- Remember HTTP responses are wrapped: use `data.fieldName` not just `fieldName`
- Verify `merge_path` matches response structure
- Use correct dot notation (`data.items`, not `data/items`)
- Check if path exists in all responses
- Common issue: Using `merge_path: data` when you need `merge_path: data.data`

### Retry Not Working

**Problem:** Failures not retried

**Solutions:**
- Ensure `retry` block is inside `pagination` block
- Check `max_attempts` > 1
- Verify HTTP errors are retry-able (5xx, timeouts)

## Implementation Details

### Async HTTP Execution

The pagination feature uses asynchronous HTTP calls for better performance:

- Each HTTP request is executed with `asyncio` for non-blocking I/O
- Worker threads create dedicated event loops using `asyncio.new_event_loop()`
- Retry delays use `await asyncio.sleep()` for efficient waiting
- Multiple pagination steps can run concurrently in different workers

**Performance Benefits:**
- Non-blocking HTTP calls during retry delays
- Better resource utilization in high-throughput scenarios
- Scalable to multiple concurrent pagination workflows

### Thread Safety

The pagination executor manages event loops carefully:
```python
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
try:
    return loop.run_until_complete(async_function())
finally:
    loop.close()
    asyncio.set_event_loop(None)
```

This ensures each worker thread has its own event loop, preventing conflicts in multi-threaded environments.

## See Also

- [Variables Feature](./variables) - Using pagination results in downstream steps
- [HTTP Tool Reference](/docs/reference/tools/http) - HTTP action configuration
- [Iterator Feature](./iterator) - Loop over collections vs pagination
