---
sidebar_position: 15
title: Unified Retry System
description: Universal retry architecture for error recovery and success-driven repetition (pagination, polling, streaming)
---

# Unified Retry System

## Overview

Unified retry uses a single `when`/`then` pattern for both error recovery and success-driven repetition (pagination, polling, streaming). This provides a consistent conditional structure across the entire DSL.

### Conceptual Shift

**Traditional View:**
- `retry` = "re-run the tool on error"
- Separate pagination system for responses
- Tool-specific iteration logic

**Unified View:**
- `retry` = array of conditional policies evaluated in order
- Error retry, pagination, polling, and streaming all use same `when`/`then` pattern
- **First matching policy executes** (short-circuit evaluation)
- Universal pattern across ALL tools (HTTP, Postgres, Python, etc.)

This makes retry a universal **"response handler / re-invocation controller"** with consistent, predictable evaluation semantics.

## Architecture

### Evaluation Semantics

**First Match Wins** - Retry policies evaluated in order:

1. Execute action → get result or error
2. Evaluate retry policies **in order** (top to bottom)
3. **First policy with truthy `when` executes** (short-circuit)
4. If no match → action completes (no retry)

**Order matters** - Place specific conditions before general ones.

### Core Components

#### 1. Error Retry Policy
- Expression-based error conditions
- Exponential backoff with jitter
- Max attempts and delay configuration

#### 2. Success Continuation Policy
- Continuation conditions for pagination/polling
- **`next_call`**: Templates for building next request
- **`collect`**: Result aggregation (append/replace/merge)
- **`sink`**: Per-iteration side effects

#### 3. UnifiedRetryHandler (Orchestration)
- Evaluates policies in order
- Routes to error or success handler based on context
- Supports complex multi-condition scenarios

### Execution Flow

```
execute_with_retry()
├── Parse retry config (list of when/then policies)
├── Execute action
├── Evaluate retry policies in order:
│   ├── Check policy[0].when condition
│   │   ├── If truthy → execute policy[0].then
│   │   └── If falsy → check next policy
│   ├── Check policy[1].when condition
│   │   └── ...
│   └── No match → complete
└── Route based on matched policy:
    ├── Error policy → _execute_with_error_retry()
    │   └── Attempt loop with backoff and error handling
    │
    └── Success policy → _execute_with_success_retry()
        ├── Iteration loop
        ├── Execute task per iteration
        ├── Check continuation condition
        ├── Aggregate results
        ├── Execute per-iteration sink (if defined)
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
  tool:
    kind: http
    url: "{{ api_url }}/data"
    params:
      page: 1
      pageSize: 100
  
  # Unified retry with when/then pattern
  retry:
    - when: "{{ response.data.has_more == true }}"
      then:
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
  tool:
    kind: http
    url: "{{ api_url }}/data"
    params:
      page: 1
  
  retry:
    # Error-side: Handle transient failures
    - when: "{{ error.status in [429, 500, 502, 503] }}"
      then:
        max_attempts: 5
        backoff_multiplier: 2.0
        initial_delay: 1.0
    
    # Success-side: Pagination
    - when: "{{ response.data.has_more }}"
      then:
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
  tool:
    kind: http
    url: "{{ api_url }}/events"
    params:
      offset: 0
      limit: 1000
  
  retry:
    - when: "{{ response.data | length == 1000 }}"
      then:
        max_attempts: 100
        
        next_call:
          params:
            offset: "{{ (response.offset | int) + 1000 }}"
        
        collect:
          strategy: append
          path: data.events
        
        # Save each page as it's fetched
        sink:
          tool:
            kind: postgres
            auth: pg_creds
            table: raw_events
          args:
            events: "{{ page.data }}"
            page_number: "{{ _retry.index }}"
            fetched_at: "{{ now() }}"
```

### Backward Compatibility

**Legacy syntax** - Deprecated but still supported during transition:

```yaml
# OLD FORMAT (deprecated)
retry:
  on_error:
    when: "{{ error.status == 429 }}"
    max_attempts: 3
  on_success:
    while: "{{ response.has_more }}"
    next_call: ...

# NEW FORMAT (recommended)
retry:
  - when: "{{ error.status == 429 }}"
    then:
      max_attempts: 3
  - when: "{{ response.has_more }}"
    then:
      next_call: ...
```

**Simple legacy format** - Automatically converted:

```yaml
# Old syntax (still works)
retry:
  when: "{{ error.status == 429 }}"
  max_attempts: 3

# Converted to:
retry:
  - when: "{{ error.status == 429 }}"
    then:
      max_attempts: 3
```

**Migration**: Use automated migration script `scripts/migrate_retry_syntax.py` to convert existing playbooks.

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
  - when: "{{ response.data.page < response.data.totalPages }}"
    then:
      max_attempts: 100
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
  - when: "{{ response.data.has_more }}"
    then:
      max_attempts: 100
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
  - when: "{{ response.data.nextCursor is not none }}"
    then:
      max_attempts: 100
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
  - when: "{{ response.data.links.next is not none }}"
    then:
      max_attempts: 100
      next_call:
        url: "{{ response.data.links.next }}"
      collect:
        strategy: append
        path: data.items
```

### Postgres Cursor Pagination

```yaml
- step: fetch_large_table
  tool:
    kind: postgres
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
    - when: "{{ response | length == page_size }}"
      then:
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
  tool:
    kind: python
    libs:
      requests: requests
    args:
      job_id: "{{ job_id }}"
    code: |
      # Pure Python code - no imports, no def main()
      # Libraries imported via libs: requests
      resp = requests.get(f"https://api.example.com/jobs/{job_id}")
      result = {"status": "success", "data": resp.json()}
  
  retry:
    - when: "{{ response.data.status in ['pending', 'running'] }}"
      then:
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
  tool:
    kind: duckdb
    database: analytics.db
    query: |
      SELECT * FROM events 
      WHERE batch_id = {{ batch_id }}
      LIMIT {{ batch_size }}
  args:
    batch_id: 1
    batch_size: 10000
  
  retry:
    - when: "{{ response | length == batch_size }}"
      then:
        max_attempts: 100
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
  tool:
    kind: http
    url: "{{ api_url }}{{ endpoint.path }}"
    params:
      page: 1
      pageSize: "{{ endpoint.page_size }}"
  loop:
    collection: "{{ workload.endpoints }}"
    element: endpoint
    mode: sequential
  
  retry:
    - when: "{{ error.status in [429, 500, 502, 503] }}"
      then:
        max_attempts: 3
        backoff_multiplier: 2.0
    
    - when: "{{ response.data.has_more == true }}"
      then:
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
            tool:
              kind: postgres
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

- **Core Logic:** `noetl/tools/runtime/retry.py`
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
tool:
  kind: http
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
tool:
  kind: http
retry:
  - when: "{{ response.data.paging.hasMore }}"
    then:
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
- `pagination.sink` → `retry[].then.per_iteration.sink` (within when/then policy)

### Response Access Changes

With DotDict support, response access is more natural:

**Before:**
```yaml
retry:
  - when: "{{ response['data']['paging']['hasMore'] == true }}"
```

**After:**
```yaml
retry:
  - when: "{{ response.data.paging.hasMore == true }}"
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

Register test playbooks:
```bash
noetl run automation/test/setup.yaml --set action=register-playbooks
```

### Verification

Run pagination tests:
```bash
noetl run automation/test/setup.yaml --set action=register-playbooks
curl -X POST http://localhost:30082/api/run/playbook \
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
  - when: "{{ response.has_more }}"
    then:
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
  - when: "{{ error.status in [429, 500, 502, 503] }}"
    then:
      max_attempts: 3
  - when: "{{ response.has_more }}"
    then:
      max_attempts: 50
```

### 4. Save Large Results Incrementally

```yaml
retry:
  - when: "{{ response.has_more }}"
    then:
      per_iteration:
        sink:
          tool: postgres
          table: raw_data  # Don't accumulate in memory
```

### 5. Validate Response Structure

```yaml
retry:
  - when: "{{ response.data.has_more is defined and response.data.has_more == true }}"
    then:
      max_attempts: 100
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
retry:
  - when: "{{ response.data.has_more is defined and response.data.has_more }}"
    then:
      max_attempts: 100
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

- [HTTP Action Type Reference](/docs/reference/http_action_type)
- [Variables Feature](./variables_feature_design)
- [DSL Specification](./spec)
- [Playbook Structure](/docs/features/playbook_structure)
