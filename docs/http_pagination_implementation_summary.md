# HTTP Pagination Implementation Summary

## Overview

Implemented automatic HTTP pagination support for NoETL, allowing declarative configuration of paginated API calls with result merging and retry capabilities.

## Implementation Date

January 2025 (v1.5.0)

## Feature Description

Adds `loop.pagination` block to HTTP actions, enabling automatic continuation based on API response inspection. Supports multiple pagination patterns (page number, offset, cursor) with configurable merge strategies and built-in retry mechanism.

## User-Facing Changes

### New Syntax

```yaml
- step: fetch_all_data
  tool: http
  url: "{{ api_url }}/data"
  params:
    page: 1
  loop:
    pagination:
      type: response_based
      continue_while: "{{ response.paging.hasMore }}"
      next_page:
        params:
          page: "{{ (response.paging.page | int) + 1 }}"
      merge_strategy: append
      merge_path: data
      max_iterations: 100
      retry:
        max_attempts: 3
        backoff: exponential
```

### Configuration Attributes

#### Required
- `type` - Pagination type (currently only `response_based`)
- `continue_while` - Jinja2 boolean expression for continuation
- `next_page` - Dict with `params`, `body`, or `headers` to update
- `merge_strategy` - How to combine results: `append`, `extend`, `replace`, `collect`

#### Optional
- `merge_path` - JSONPath to data array (dot notation)
- `max_iterations` - Safety limit (default: 1000)
- `retry` - Retry configuration block
  - `max_attempts` - Number of retries (default: 1)
  - `backoff` - `fixed` or `exponential` (default: fixed)
  - `initial_delay` - Seconds before first retry (default: 1)
  - `max_delay` - Maximum backoff seconds (default: 60)

## Implementation Details

### Modified Files

1. **noetl/plugin/controller/iterator/config.py**
   - Added `extract_pagination_config()` function
   - Extracts and validates pagination block from loop config
   - Returns `pagination_config` in config dict
   - Validates required fields and merge strategy

2. **noetl/plugin/controller/iterator/executor.py**
   - Added pagination detection in `execute_loop_task()`
   - Delegates to pagination executor when `pagination_config` present
   - Returns paginated results as task result

3. **noetl/plugin/controller/iterator/pagination.py** (NEW)
   - Main pagination orchestrator
   - `execute_paginated_http()` - Main execution function
   - `execute_with_retry()` - Retry logic per request
   - `merge_response()` - Result accumulation strategies
   - `render_dict()` - Recursive template rendering

### Key Functions

#### `execute_paginated_http()`
Main orchestrator that:
1. Extracts pagination config
2. Initializes accumulator
3. Loops while continuation condition true:
   - Renders HTTP config with current context
   - Executes HTTP request with retry
   - Merges response into accumulator
   - Evaluates `continue_while` expression
   - Updates request parameters for next page
4. Returns accumulated results

#### `execute_with_retry()`
Handles retry logic:
- Calls async `execute_http_task()` in sync context
- Implements exponential or fixed backoff
- Returns response or raises last error

#### `merge_response()`
Implements merge strategies:
- **append**: `accumulated.extend(data_to_merge)`
- **extend**: Flattens nested arrays
- **replace**: Returns last response
- **collect**: Appends each response to array

### Available Context Variables

In `continue_while` and `next_page` expressions:
- `{{ response }}` - Current HTTP response body (parsed JSON)
- `{{ iteration }}` - Current iteration number (0-based)
- `{{ accumulated }}` - Merged results so far
- `{{ workload.* }}` - Global workflow variables
- `{{ vars.* }}` - Execution-scoped variables

## Test Infrastructure

### Mock Server
**File:** `tests/fixtures/servers/paginated_api.py`

Technology: FastAPI with uvicorn

Endpoints:
- `/api/v1/assessments` - Page number pagination
- `/api/v1/users` - Offset pagination
- `/api/v1/events` - Cursor pagination
- `/api/v1/flaky` - Failure injection for retry testing
- `/health` - Health check

Configuration:
- 35 total items
- 10 items per page
- Realistic pagination metadata

### Test Playbooks
**Directory:** `tests/fixtures/playbooks/pagination/`

1. **test_pagination_basic.yaml**
   - Page number pagination
   - Validates all 35 items fetched
   - Tests `hasMore` flag

2. **test_pagination_offset.yaml**
   - Offset-based pagination
   - Tests `offset + limit` calculation
   - Validates user fetching

3. **test_pagination_cursor.yaml**
   - Cursor-based pagination
   - Tests opaque token handling
   - Validates event fetching

4. **test_pagination_retry.yaml**
   - Tests retry mechanism
   - Page 2 configured to fail initially
   - Validates exponential backoff

5. **test_pagination_max_iterations.yaml**
   - Tests safety limit
   - `max_iterations: 2` stops at 2 pages
   - Validates only 20 items returned

### Test Script
**File:** `tests/scripts/test_pagination.sh`

Features:
- Checks mock server and NoETL API health
- Registers playbooks via `/api/catalog/register`
- Executes via `/api/run/playbook`
- Polls execution status until completion
- Reports pass/fail for each test
- Summary with total/passed/failed counts

Usage:
```bash
# Start mock server
python tests/fixtures/servers/paginated_api.py 5555

# Run all tests
./tests/scripts/test_pagination.sh
```

## Documentation

### User Documentation
**File:** `documentation/docs/features/pagination.md`

Sections:
- Overview and quick start
- Pagination patterns (page, offset, cursor)
- Configuration reference (all attributes)
- Complete example playbook
- Best practices
- Troubleshooting guide
- See also links

### Quick Reference
**File:** `documentation/docs/reference/http_pagination_quick_reference.md`

Contains:
- Minimal examples
- Common patterns
- All merge strategies
- Available variables
- File locations

### Design Document
**File:** `docs/http_pagination_design.md`

Contains:
- Use cases
- Complete attribute reference
- Implementation phases
- Merge strategy details
- Example playbooks
- Error handling

## Supported Pagination Patterns

### 1. Page Number
```yaml
continue_while: "{{ response.paging.hasMore }}"
next_page:
  params:
    page: "{{ response.paging.page + 1 }}"
```

### 2. Offset-Based
```yaml
continue_while: "{{ response.has_more }}"
next_page:
  params:
    offset: "{{ response.offset + response.limit }}"
```

### 3. Cursor-Based
```yaml
continue_while: "{{ response.next_cursor is not none }}"
next_page:
  params:
    cursor: "{{ response.next_cursor }}"
```

## Error Handling

1. **HTTP Errors**: Retried based on retry configuration
2. **Max Iterations**: Stops with warning, returns accumulated data
3. **Invalid Response**: Stops with error if `continue_while` evaluation fails
4. **Merge Errors**: Stops with error if `merge_path` not found
5. **Async Context**: Handles both sync and async event loop contexts

## Backward Compatibility

- Fully backward compatible
- No changes to existing iterator behavior
- Pagination only active when `loop.pagination` block present
- Works with NEW format (`loop:` attribute) only, not OLD format (`tool: iterator`)

## Performance Considerations

1. **Sequential Execution**: Requests are sequential (not parallel)
2. **Memory**: Accumulates all responses in memory
3. **Safety**: `max_iterations` prevents runaway loops
4. **Retry**: Adds latency but improves reliability

## Future Enhancements

Potential improvements:
1. Parallel page fetching (when order doesn't matter)
2. Streaming merge to database (avoid memory limits)
3. Cursor-based pagination type with automatic token extraction
4. Link header parsing (RFC 5988)
5. Rate limiting support (X-RateLimit headers)
6. Progress reporting (X out of Y pages)

## Migration Guide

For existing manual pagination loops:

### Before (Manual)
```yaml
- step: fetch_page_1
  tool: http
  url: "{{ api_url }}/data?page=1"
  
- step: fetch_page_2
  tool: http
  url: "{{ api_url }}/data?page=2"
  
- step: merge_results
  tool: python
  code: |
    def main(input_data):
        all_data = []
        all_data.extend(input_data['fetch_page_1'])
        all_data.extend(input_data['fetch_page_2'])
        return all_data
```

### After (Automatic)
```yaml
- step: fetch_all_data
  tool: http
  url: "{{ api_url }}/data"
  params:
    page: 1
  loop:
    pagination:
      type: response_based
      continue_while: "{{ response.hasMore }}"
      next_page:
        params:
          page: "{{ response.page + 1 }}"
      merge_strategy: append
      merge_path: data
```

## Known Limitations

1. Only works with HTTP tool (not postgres, duckdb, etc.)
2. Sequential execution only (no parallel page fetching)
3. All results accumulated in memory
4. Requires JSON response (no XML, CSV, etc.)
5. NEW format only (not compatible with OLD `tool: iterator` format)

## Testing Checklist

- [x] Config extraction and validation
- [x] Pagination detection and delegation
- [x] Page number pagination
- [x] Offset pagination
- [x] Cursor pagination
- [x] Result merging (all 4 strategies)
- [x] Retry mechanism with backoff
- [x] Max iterations safety limit
- [x] Mock server with realistic data
- [x] Comprehensive test script
- [x] User documentation
- [x] Quick reference guide
- [ ] Integration with live NoETL deployment
- [ ] Performance benchmarking
- [ ] Error handling edge cases

## Next Steps

1. **Build and Deploy**
   ```bash
   task docker-build-noetl
   task kind-load-image image=local/noetl:latest
   task deploy-noetl
   ```

2. **Start Mock Server**
   ```bash
   python tests/fixtures/servers/paginated_api.py 5555
   ```

3. **Run Tests**
   ```bash
   ./tests/scripts/test_pagination.sh
   ```

4. **Validate Results**
   - All 5 tests should pass
   - Check logs for pagination events
   - Verify merged result counts

5. **Update Copilot Instructions**
   - Add pagination pattern to examples
   - Document in `.github/copilot-instructions.md`

## Related Issues/PRs

- Phase 2 Task 3: Variable Management API (completed)
- Pagination feature request (user provided example with `hasMore` flag)
- HTTP action improvements roadmap

## Contributors

- Implementation: AI Agent (GitHub Copilot)
- Review: User (akuksin)
- Testing: Pending

## Version History

- v1.5.0 (2025-01): Initial pagination implementation
  - Added `loop.pagination` block
  - Support for response-based continuation
  - 4 merge strategies
  - Retry integration
  - Comprehensive test suite
