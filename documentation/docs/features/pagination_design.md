# HTTP Pagination Loop Feature Design

## Overview

Add support for paginated HTTP API calls within iterator loops, allowing automatic continuation based on response inspection.

## Use Case

```yaml
- step: fetch_all_assessments
  tool: http
  url: "{{ workload.api_url }}/assessments"
  method: GET
  loop:
    pagination:
      type: response_based
      continue_while: "{{ response.paging.hasMore == true }}"
      next_page:
        params:
          page: "{{ (response.paging.page | int) + 1 }}"
          pageSize: "{{ response.paging.pageSize }}"
      merge_strategy: append
      merge_path: "data"
      max_iterations: 100
    retry:
      max_attempts: 3
      backoff: exponential
      initial_delay: 1
```

## Loop Pagination Attributes

### `pagination` Block

**`type`** (string, required)
- `response_based` - Continue based on response inspection
- `cursor_based` - Use cursor/token from response (future)
- `offset_based` - Use offset/limit pattern (future)

**`continue_while`** (jinja2 expression, required)
- Boolean expression evaluated against response
- Available variables:
  - `{{ response }}` - Full HTTP response body
  - `{{ iteration }}` - Current iteration number (0-based)
  - `{{ accumulated }}` - Merged results so far

**`next_page`** (object, required)
- Defines how to modify request for next iteration

**`next_page.params`** (object, optional)
- Query parameters to update/add
- Supports Jinja2 expressions with response access

**`next_page.body`** (object, optional)
- Request body modifications for POST/PUT
- Supports Jinja2 expressions

**`next_page.headers`** (object, optional)
- Header modifications
- Useful for cursor tokens

**`merge_strategy`** (string, required)
- `append` - Append arrays at merge_path
- `extend` - Flatten nested arrays
- `replace` - Keep only last response
- `collect` - Store all responses as array

**`merge_path`** (string, optional)
- JSONPath to data array in response
- Default: root level
- Examples: `data`, `results`, `items`

**`max_iterations`** (integer, optional)
- Safety limit to prevent infinite loops
- Default: 1000

### `retry` Block (reuse existing retry mechanism)

**`max_attempts`** (integer, optional)
- Number of retry attempts per request
- Default: 1 (no retry)

**`backoff`** (string, optional)
- `fixed` or `exponential`
- Default: fixed

**`initial_delay`** (number, optional)
- Seconds to wait before first retry
- Default: 1

**`max_delay`** (number, optional)
- Maximum backoff delay in seconds
- Default: 60

## Implementation Plan

### Phase 1: Core Pagination Loop (Current)

1. **Extend iterator config** (`noetl/plugin/controller/iterator/config.py`)
   - Extract `pagination` block from loop config
   - Validate pagination attributes

2. **Add pagination executor** (`noetl/plugin/controller/iterator/pagination.py`)
   - New module for pagination logic
   - `execute_paginated_http()` function
   - Response inspection and continuation logic
   - Result merging strategies

3. **Update iterator executor** (`noetl/plugin/controller/iterator/executor.py`)
   - Detect pagination block
   - Delegate to pagination executor
   - Handle merged results

4. **Add retry integration** (`noetl/plugin/controller/iterator/retry.py`)
   - Reuse existing retry mechanism
   - Apply retry per HTTP request
   - Exponential backoff support

### Phase 2: Test Infrastructure

1. **Mock HTTP server** (`tests/fixtures/servers/paginated_api.py`)
   - Flask-based mock API
   - Configurable page size
   - Realistic pagination response
   - Error injection for retry testing

2. **Test playbooks** (`tests/fixtures/playbooks/pagination/`)
   - `test_pagination_basic.yaml` - Simple pagination
   - `test_pagination_merge.yaml` - Array merging
   - `test_pagination_retry.yaml` - Failed requests
   - `test_pagination_limits.yaml` - Max iterations

3. **Test script** (`tests/scripts/test_pagination.sh`)
   - Start mock server
   - Run test playbooks
   - Validate merged results
   - Cleanup

### Phase 3: Documentation

1. **Feature doc** (`documentation/docs/features/pagination.md`)
   - Overview and use cases
   - Configuration examples
   - Merge strategies
   - Best practices

2. **Reference** (`documentation/docs/reference/http_pagination.md`)
   - Complete attribute reference
   - Expression examples
   - Error handling

## Response Merging Strategies

### Append Strategy
```python
# Initial: accumulated = []
# Page 1 response: {"data": [1, 2, 3]}
# Result: accumulated = [1, 2, 3]
# Page 2 response: {"data": [4, 5, 6]}
# Result: accumulated = [1, 2, 3, 4, 5, 6]
```

### Extend Strategy
```python
# Initial: accumulated = []
# Page 1 response: {"data": [[1, 2], [3, 4]]}
# Result: accumulated = [1, 2, 3, 4]
# Page 2 response: {"data": [[5, 6], [7, 8]]}
# Result: accumulated = [1, 2, 3, 4, 5, 6, 7, 8]
```

### Replace Strategy
```python
# Initial: accumulated = None
# Page 1 response: {"data": [1, 2, 3]}
# Result: accumulated = {"data": [1, 2, 3]}
# Page 2 response: {"data": [4, 5, 6]}
# Result: accumulated = {"data": [4, 5, 6]}  # Replaced
```

### Collect Strategy
```python
# Initial: accumulated = []
# Page 1 response: {"data": [1, 2, 3], "page": 1}
# Result: accumulated = [{"data": [1, 2, 3], "page": 1}]
# Page 2 response: {"data": [4, 5, 6], "page": 2}
# Result: accumulated = [{"data": [1, 2, 3], "page": 1}, {"data": [4, 5, 6], "page": 2}]
```

## Example Playbooks

### Basic Pagination
```yaml
- step: fetch_users
  tool: http
  url: "{{ workload.api_url }}/users"
  loop:
    pagination:
      type: response_based
      continue_while: "{{ response.has_more == true }}"
      next_page:
        params:
          offset: "{{ (response.offset | int) + (response.limit | int) }}"
      merge_strategy: append
      merge_path: "users"
```

### Cursor-Based Pagination
```yaml
- step: fetch_events
  tool: http
  url: "{{ workload.api_url }}/events"
  loop:
    pagination:
      type: response_based
      continue_while: "{{ response.next_cursor is defined and response.next_cursor }}"
      next_page:
        params:
          cursor: "{{ response.next_cursor }}"
      merge_strategy: append
      merge_path: "events"
```

### Page Number Pagination
```yaml
- step: fetch_assessments
  tool: http
  url: "{{ workload.api_url }}/assessments"
  params:
    page: 1
    pageSize: 100
  loop:
    pagination:
      type: response_based
      continue_while: "{{ response.paging.hasMore == true }}"
      next_page:
        params:
          page: "{{ (response.paging.page | int) + 1 }}"
      merge_strategy: append
      merge_path: "data"
      max_iterations: 50
    retry:
      max_attempts: 3
      backoff: exponential
```

## Variable Availability

Within pagination context, these variables are available in Jinja2 expressions:

- `{{ response }}` - Current HTTP response (parsed JSON)
- `{{ iteration }}` - Current iteration number (0-based)
- `{{ accumulated }}` - Merged data so far (depends on merge_strategy)
- `{{ workload }}` - Global workflow variables
- `{{ vars }}` - Execution-scoped variables

## Error Handling

1. **HTTP Errors**: Retried based on retry configuration
2. **Max Iterations**: Stops with warning, returns accumulated data
3. **Invalid Response**: Stops with error if continue_while evaluation fails
4. **Merge Errors**: Stops with error if merge_path not found

## Benefits

1. **Declarative**: No custom code needed for pagination
2. **Flexible**: Supports multiple pagination patterns
3. **Safe**: Built-in limits prevent infinite loops
4. **Resilient**: Integrated retry mechanism
5. **Debuggable**: Each iteration logged with response inspection
