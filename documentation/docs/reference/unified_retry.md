---
sidebar_position: 15
title: Unified Retry System
description: Universal retry architecture for error recovery and success-driven repetition (pagination, polling, streaming)
---

# Unified Retry System

## Overview

Unified retry is an architectural pattern that unifies error recovery and success-driven repetition under a single `retry` concept. Instead of treating pagination as a separate concern, we recognize that **pagination is just success-side of retry** - where successful responses trigger re-invocation with updated parameters.

### Conceptual Shift

**Traditional View:**
- `retry` = "re-run the tool on error"
- Separate pagination system for responses
- Tool-specific iteration logic

**Unified View:**
- `retry` = "re-run the tool on error AND/OR success, with optional state updates and aggregation"
- Pagination, polling, cursor loops, and streaming are all **"success-side retry"**
- Universal pattern across ALL tools (HTTP, Postgres, Python, etc.)

This makes retry a universal **"response handler / re-invocation controller"**.

## Architecture

### Core Components

#### 1. RetryPolicy (Error-Side Retry)
- Original error retry logic
- Expression-based conditions
- Exponential backoff with jitter
- Backward compatible with existing configs

#### 2. SuccessRetryPolicy (Success-Side Retry)
- **`while`**: Continuation condition evaluated on responses
- **`next_call`**: Templates for building next request
- **`collect`**: Result aggregation (append/replace/merge)
- **`per_iteration`**: Side effects (sink, logging)

#### 3. UnifiedRetryPolicy (Orchestration)
- Detects unified structure (`on_error`, `on_success`)
- Routes execution to appropriate handler
- Supports combining both policies

### Execution Flow

```
execute_with_retry()
├── Parse retry config (bool, int, dict)
├── Create UnifiedRetryPolicy
└── Route based on policy:
    ├── on_error only → _execute_with_error_retry()
    │   └── Attempt loop with backoff and error handling
    │
    └── on_success → _execute_with_success_retry()
        ├── Iteration loop
        ├── Execute task per iteration
        ├── Check continuation condition (with DotDict support)
        ├── Aggregate results
        ├── Execute per-iteration effects
        └── Build next request
```

### Response Unwrapping

The retry system automatically handles HTTP response envelopes:
- HTTP responses: `{'id': ..., 'status': 'success', 'data': <actual_response>}`
- System unwraps to `actual_response` for condition evaluation
- Converts to `DotDict` for Jinja2 dot notation support
- Enables `{{ response.data.has_more }}` instead of `{{ response['data']['has_more'] }}`

## Playbook Syntax

### Basic Success-Side Retry (Pagination)

```yaml
- step: fetch_data
  tool: http
  url: "{{ api_url }}/data"
  params:
    page: 1
    pageSize: 100
  
  # Unified retry with success-side repetition
  retry:
    on_success:
      # Continue while API indicates more data
      while: "{{ response.data.has_more == true }}"
      max_attempts: 50
      
      # How to build next request
      next_call:
        params:
          page: "{{ (response.data.page | int) + 1 }}"
          pageSize: "{{ response.data.pageSize }}"
      
      # How to aggregate results
      collect:
        strategy: append      # append | replace | merge
        path: data.items      # Extract from response.data.items
        into: pages           # Store in {{ pages }}
```

### Combined Error + Success Retry

```yaml
- step: robust_pagination
  tool: http
  url: "{{ api_url }}/data"
  params:
    page: 1
  
  retry:
    # Error-side: Handle transient failures
    on_error:
      when: "{{ error.status in [429, 500, 502, 503] }}"
      max_attempts: 5
      backoff_multiplier: 2.0
      initial_delay: 1.0
    
    # Success-side: Pagination
    on_success:
      while: "{{ response.data.has_more }}"
      max_attempts: 100
      next_call:
        params:
          page: "{{ (response.data.page | int) + 1 }}"
      collect:
        strategy: append
        path: data.items
```

### Per-Iteration Side Effects

```yaml
- step: paginate_with_sink
  tool: http
  url: "{{ api_url }}/events"
  params:
    offset: 0
    limit: 1000
  
  retry:
    on_success:
      while: "{{ response.data | length == 1000 }}"
      max_attempts: 100
      
      next_call:
        params:
          offset: "{{ (response.offset | int) + 1000 }}"
      
      collect:
        strategy: append
        path: data.events
      
      # Save each page as it's fetched
      per_iteration:
        sink:
          tool: postgres
          auth: pg_creds
          table: raw_events
          args:
            events: "{{ page.data }}"
            page_number: "{{ _retry.index }}"
            fetched_at: "{{ now() }}"
```

### Backward Compatibility

Legacy retry configs are automatically treated as `on_error` only:

```yaml
# Old syntax (still works)
retry:
  when: "{{ error.status == 429 }}"
  max_attempts: 3
  backoff_multiplier: 2.0

# Equivalent to:
retry:
  on_error:
    when: "{{ error.status == 429 }}"
    max_attempts: 3
    backoff_multiplier: 2.0
```

## Reserved Variables

### Available in Templates

- **`{{ _retry.index }}`** - Current iteration number (1-based)
- **`{{ _retry.count }}`** - Total iterations executed (updated at end)
- **`{{ response }}`** - Most recent successful response (as DotDict)
- **`{{ page }}`** - Alias for current iteration response
- **`{{ pages }}`** - Accumulated results (if `collect.into` specified)
- **`{{ iteration }}`** - Same as `_retry.index`

### Context in next_call Templates

When building next request, you have access to:
- `response` - Current response data (unwrapped and converted to DotDict)
- `page` - Same as response
- `_retry.index`, `_retry.count` - Iteration counters
- All workload variables
- All vars block variables

## Tool-Agnostic Patterns

Unified retry works with **ALL tools**, not just HTTP.

### HTTP Pagination Examples

#### Page-Based Pagination
```yaml
retry:
  on_success:
    while: "{{ response.data.page < response.data.totalPages }}"
    next_call:
      params:
        page: "{{ (response.data.page | int) + 1 }}"
    collect:
      strategy: append
      path: data.items
```

#### Offset-Based Pagination
```yaml
retry:
  on_success:
    while: "{{ response.data.has_more }}"
    next_call:
      params:
        offset: "{{ (response.data.offset | int) + (response.data.limit | int) }}"
        limit: "{{ response.data.limit }}"
    collect:
      strategy: append
      path: data.users
```

#### Cursor-Based Pagination
```yaml
retry:
  on_success:
    while: "{{ response.data.nextCursor is not none }}"
    next_call:
      params:
        cursor: "{{ response.data.nextCursor }}"
    collect:
      strategy: append
      path: data.results
```

#### URL-Based Pagination
```yaml
retry:
  on_success:
    while: "{{ response.data.links.next is not none }}"
    next_call:
      url: "{{ response.data.links.next }}"
    collect:
      strategy: append
      path: data.items
```

### Postgres Cursor Pagination

```yaml
- step: fetch_large_table
  tool: postgres
  auth: db_creds
  query: |
    SELECT * FROM orders 
    WHERE id > {{ cursor_id | default(0) }} 
    ORDER BY id 
    LIMIT {{ page_size }}
  args:
    cursor_id: 0
    page_size: 1000
  
  retry:
    on_success:
      while: "{{ response | length == page_size }}"
      max_attempts: 1000
      
      next_call:
        args:
          cursor_id: "{{ response[-1].id }}"
          page_size: 1000
      
      collect:
        strategy: append
```

### Python Polling

```yaml
- step: wait_for_job
  tool: python
  code: |
    def main(input_data):
        import requests
        job_id = input_data['job_id']
        resp = requests.get(f"https://api.example.com/jobs/{job_id}")
        return resp.json()
  args:
    job_id: "{{ job_id }}"
  
  retry:
    on_success:
      while: "{{ response.status in ['pending', 'running'] }}"
      max_attempts: 60
      
      next_call:
        args:
          job_id: "{{ job_id }}"  # Same input, check again
      
      collect:
        strategy: replace  # Only keep latest status
```

### DuckDB Incremental Export

```yaml
- step: export_analytics
  tool: duckdb
  database: analytics.db
  query: |
    SELECT * FROM events 
    WHERE batch_id = {{ batch_id }}
    LIMIT {{ batch_size }}
  args:
    batch_id: 1
    batch_size: 10000
  
  retry:
    on_success:
      while: "{{ response | length == batch_size }}"
      next_call:
        args:
          batch_id: "{{ batch_id + 1 }}"
          batch_size: 10000
      collect:
        strategy: append
```

## Loop Integration

Unified retry works seamlessly with the `loop` parameter for multi-endpoint pagination:

```yaml
- step: fetch_all_endpoints
  tool: http
  loop:
    collection: "{{ workload.endpoints }}"
    element: endpoint
    mode: sequential
  
  url: "{{ api_url }}{{ endpoint.path }}"
  params:
    page: 1
    pageSize: "{{ endpoint.page_size }}"
  
  retry:
    on_error:
      when: "{{ error.status in [429, 500, 502, 503] }}"
      max_attempts: 3
      backoff_multiplier: 2.0
    
    on_success:
      while: "{{ response.data.has_more == true }}"
      max_attempts: 10
      
      next_call:
        params:
          page: "{{ (response.data.offset | int) + (response.data.limit | int) }}"
          pageSize: "{{ response.data.limit }}"
      
      collect:
        strategy: append
        path: data.users
        into: pages
      
      per_iteration:
        sink:
          tool: postgres
          auth: pg_k8s
          table: raw_data
          mode: insert
          args:
            endpoint_name: "{{ endpoint.name }}"
            page_data: "{{ page.data }}"
            iteration: "{{ _retry.index }}"
```

## Implementation Details

### File Locations

- **Core Logic:** `noetl/plugin/runtime/retry.py`
- **Classes:**
  - `DotDict` - Enables Jinja2 dot notation for dict access
  - `RetryPolicy` - Error-side retry
  - `SuccessRetryPolicy` - Success-side retry
  - `UnifiedRetryPolicy` - Orchestration
- **Functions:**
  - `execute_with_retry()` - Entry point
  - `_execute_with_error_retry()` - Error retry loop
  - `_execute_with_success_retry()` - Success retry loop with pagination
  - `_execute_iteration_with_error_retry()` - Per-iteration error handling
  - `_build_next_request()` - Request construction from templates
  - `_execute_per_iteration_effects()` - Side effect execution (sink, etc.)

### Key Design Decisions

1. **Tool-Agnostic:** Retry system doesn't know about HTTP, Postgres, or any specific tool
2. **Backward Compatible:** Legacy retry configs work unchanged
3. **Composable:** Can combine `on_error` + `on_success` for robust pagination
4. **Declarative:** Express iteration logic in YAML, not code
5. **Side Effects:** Per-iteration operations enable granular data saving
6. **DotDict Support:** Automatic conversion enables natural Jinja2 syntax
7. **Response Unwrapping:** Handles HTTP envelopes transparently

### Removed Code

With unified retry, we removed:
- Separate pagination module
- Pagination-specific code in HTTP executor
- Tool-specific pagination implementations
- Callback-based event logging (replaced with worker-driven events)

## Migration Guide

### From Old loop.pagination Syntax

**Before (deprecated):**
```yaml
tool: http
loop:
  pagination:
    type: response_based
    continue_while: "{{ response.data.paging.hasMore }}"
    next_page:
      params:
        page: "{{ (response.data.paging.page | int) + 1 }}"
    merge_strategy: append
    merge_path: data.data
```

**After (unified retry):**
```yaml
tool: http
retry:
  on_success:
    while: "{{ response.data.paging.hasMore }}"
    max_attempts: 100
    next_call:
      params:
        page: "{{ (response.data.paging.page | int) + 1 }}"
    collect:
      strategy: append
      path: data.data
```

### Variable Name Changes

- `_loop.index` → `_retry.index`
- `_loop.count` → `_retry.count`
- `pagination.sink` → `retry.on_success.per_iteration.sink`

### Response Access Changes

With DotDict support, response access is more natural:

**Before:**
```yaml
while: "{{ response['data']['paging']['hasMore'] == true }}"
```

**After:**
```yaml
while: "{{ response.data.paging.hasMore == true }}"
```

## Benefits

1. **Conceptual Simplicity:** One concept (retry) instead of multiple (retry + pagination + polling)
2. **Universal Pattern:** Works with all tools, not just HTTP
3. **Composability:** Combine error recovery with success-driven iteration
4. **Flexibility:** Supports polling, cursors, streaming, pagination with same syntax
5. **Side Effects:** Per-iteration operations enable granular control
6. **Maintainability:** Less code, clearer abstractions
7. **Natural Syntax:** DotDict enables `response.field` instead of `response['field']`
8. **Automatic Unwrapping:** HTTP envelopes handled transparently

## Testing

### Test Playbooks

Validated test cases in `tests/fixtures/playbooks/pagination/`:
- `test_loop_with_pagination.yaml` - Loop + unified retry (10 iterations validated)
- `test_pagination_basic.yaml` - Basic HTTP pagination
- `test_pagination_offset.yaml` - Offset-based pagination
- `test_pagination_cursor.yaml` - Cursor-based pagination
- `test_pagination_retry.yaml` - Combined error + success retry
- `test_pagination_max_iterations.yaml` - Max iteration limits

### Verification

Run pagination tests:
```bash
task test:k8s:register-playbooks
curl -X POST http://localhost:8082/api/run/playbook \
  -H "Content-Type: application/json" \
  -d '{"path": "tests/pagination/loop_with_pagination"}'
```

Check worker logs:
```bash
kubectl logs -n noetl -l app=noetl-worker --tail=200 | \
  grep -E "(Success retry iteration|while condition evaluated)"
```

## Future Extensions

Unified retry enables new patterns:

1. **Adaptive Iteration:** Adjust page size based on performance/response time
2. **Parallel Pagination:** Fetch multiple pages concurrently (requires async support)
3. **Smart Backoff:** Rate limit aware pagination with dynamic delays
4. **Result Transformation:** Per-page data transformation before aggregation
5. **Conditional Aggregation:** Selective result collection based on content
6. **Streaming:** Continuous data ingestion with windowing

## Best Practices

### 1. Always Set max_attempts

```yaml
retry:
  on_success:
    while: "{{ response.has_more }}"
    max_attempts: 100  # Prevent infinite loops
```

### 2. Use Meaningful Variable Names

```yaml
collect:
  into: user_pages  # Clear intent, not just "pages"
```

### 3. Combine Error + Success Retry

```yaml
retry:
  on_error:
    when: "{{ error.status in [429, 500, 502, 503] }}"
    max_attempts: 3
  on_success:
    while: "{{ response.has_more }}"
    max_attempts: 50
```

### 4. Save Large Results Incrementally

```yaml
retry:
  on_success:
    per_iteration:
      sink:
        tool: postgres
        table: raw_data  # Don't accumulate in memory
```

### 5. Validate Response Structure

```yaml
while: "{{ response.data.has_more is defined and response.data.has_more == true }}"
```

## Troubleshooting

### Issue: Condition Always False

**Problem:** Pagination stops after 1 iteration

**Solution:** Check response structure with DotDict:
- HTTP responses wrap as `{'id': ..., 'status': ..., 'data': <actual_api_response>}`
- System unwraps to `actual_api_response` automatically
- Use `response.data.field` for HTTP API responses
- Check worker logs for actual response keys

### Issue: AttributeError in Template

**Problem:** `'NoneType' object has no attribute 'field'`

**Solution:** Use safe navigation:
```yaml
while: "{{ response.data.has_more is defined and response.data.has_more }}"
```

### Issue: Results Not Aggregating

**Problem:** `collect.path` doesn't match response structure

**Solution:** Verify path with logs:
```yaml
collect:
  path: data.items  # Must match actual response structure
```

## Conclusion

Unified retry represents a fundamental architectural shift from tool-specific iteration to universal response-driven repetition. By recognizing that **pagination IS retry**, we:

- Eliminate architectural duplication
- Enable powerful patterns across all tools
- Simplify conceptual model
- Improve maintainability

**Remember:** Every time you need pagination, polling, or cursor loops - think **"success-side retry"** instead.

## See Also

- [HTTP Action Type Reference](./http_action_type.md)
- [Variables Feature](./variables_feature_design.md)
- [DSL Specification](./dsl_spec.md)
- [Save Result Feature](./save_result.md)
