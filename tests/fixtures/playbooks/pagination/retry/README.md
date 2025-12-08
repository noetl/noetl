# Pagination with Retry Test

This folder contains a test for **pagination combined with error retry** using NoETL's unified retry system with both `retry.on_error` and `retry.on_success`.

## 🎯 Test Type

**✅ Pagination + Error Handling**
- Automatic retry on failed requests
- Combined with pagination continuation
- Production-grade resilience

## Overview

The `test_pagination_retry.yaml` playbook demonstrates **dual retry strategy** where:
- `retry.on_error`: Automatically retries failed HTTP requests (500/502/503)
- `retry.on_success`: Continues pagination until all pages fetched
- Both work together for robust data fetching
- Handles transient failures during multi-page operations

**Test Scenario:**
- **Endpoint**: `/api/v1/flaky` (intentionally fails on page 2, first attempt)
- **Page Size**: 10 items per page
- **Total Items**: 35 (requires 4 pages)
- **Failure Point**: Page 2 returns 500 on first attempt
- **Expected**: Automatic retry succeeds, all 35 items fetched

## Files

- `test_pagination_retry.yaml` - Playbook definition with error retry + pagination
- `test_retry_pagination.ipynb` - **Validation notebook**
- `README.md` - This file

## Dual Retry Configuration

```yaml
retry:
  on_error:
    when: "{{ error.status in [500, 502, 503] }}"
    max_attempts: 3
    backoff_multiplier: 2.0
    initial_delay: 0.5
  on_success:
    while: "{{ response.paging.hasMore == true }}"
    max_attempts: 10
    next_call:
      params:
        page: "{{ (response.paging.page | int) + 1 }}"
    collect:
      strategy: append
      path: data
      into: pages
```

**Key Features:**
- **Error retry**: Up to 3 attempts for 5xx errors with exponential backoff
- **Pagination**: Continue fetching pages until `hasMore == false`
- **Combined resilience**: Handles both transient failures and multi-page continuation
- **Backoff strategy**: 0.5s → 1.0s → 2.0s between retries

## Expected Behavior

**Page 2 Failure Scenario:**

The test server's `/api/v1/flaky` endpoint is configured to fail on the **first attempt** for page 2, then succeed on subsequent retries. This simulates real-world transient errors.

1. **First Attempt (FAILS):**
```json
Request: GET /api/v1/flaky?page=2&fail_on=2
Response: 500 Internal Server Error
{"detail": "Simulated failure"}
Action: Worker-side retry triggered by on_error policy
```

2. **Second Attempt (SUCCEEDS):**
```json
Request: GET /api/v1/flaky?page=2&fail_on=2 (same params, attempt counter tracked server-side)
Response: 200 OK
{
  "data": [{"id": 11, "value": "item_11"}, ..., {"id": 20, "value": "item_20"}],
  "paging": {"page": 2, "pageSize": 10, "hasMore": true}
}
Action: Continue to page 3 via on_success pagination
```

**Note:** The server tracks request attempts per page in-memory, failing only the first attempt per page number.

## How to Run

### Option 1: Using Notebook (Recommended)
```bash
# Open and run all cells
jupyter notebook test_retry_pagination.ipynb
```

### Option 2: Using NoETL API
```bash
curl -X POST http://localhost:8082/api/run/playbook \
  -H "Content-Type: application/json" \
  -d '{"path": "tests/pagination/retry"}'
```

### Option 3: Using Task Runner
```bash
task test:pagination:retry
```

## Expected Results

**✅ Success Criteria:**
- All 35 items fetched despite page 2 failure on first attempt
- Worker-side error retry succeeded on page 2 second attempt
- No manual intervention required
- Final result complete and correct with `retry_worked: true`
- Execution logs show retry attempt with backoff delay

**📊 Actual Execution Flow:**

The retry system operates at the **worker level** (not server-side event orchestration):

1. **Page 1 - Success Iteration:**
   - Worker executes HTTP request for page 1
   - Returns 200 with 10 items
   - `on_success` condition evaluates: `hasMore == true` → continue

2. **Page 2 - Retry Iteration:**
   - **Attempt 1:** Worker sends request → receives 500 error
   - **Error Detection:** `error.status == 500` matches `on_error.when` condition
   - **Retry Decision:** `should_retry()` returns `True` (attempt 1 < max_attempts 3)
   - **Backoff:** Worker sleeps 0.5s before retry
   - **Attempt 2:** Worker sends same request → receives 200 with 10 items
   - `on_success` condition evaluates: `hasMore == true` → continue

3. **Page 3 - Success Iteration:**
   - Worker executes HTTP request for page 3
   - Returns 200 with 10 items
   - `on_success` condition evaluates: `hasMore == true` → continue

4. **Page 4 - Final Iteration:**
   - Worker executes HTTP request for page 4
   - Returns 200 with 5 items
   - `on_success` condition evaluates: `hasMore == false` → stop

5. **Result Aggregation:**
   - Worker merges all page data: 10 + 10 + 10 + 5 = 35 items
   - Returns final result to server with all accumulated data

**Key Implementation Detail:** The entire pagination loop with error retry runs **inside the worker process** via `execute_with_retry()` wrapper. The server only sees the final aggregated result.

## Validation

The notebook validates:
- ✅ Total item count (35 items)
- ✅ All items present (IDs 1-35, values "item_1" through "item_35")
- ✅ Retry succeeded (page 2 data present after initial failure)
- ✅ Pagination completed (4 pages fetched)
- ✅ No data loss from retry
- ✅ `retry_worked: true` in validation result

**Test Server Requirements:**
- The test server must be running at `paginated-api.test-server.svc.cluster.local:5555`
- Flaky endpoint counters should be reset before test: `POST /api/v1/flaky/reset`
- Server tracks per-page attempt counts in-memory to simulate transient failures

## Retry Strategies

### Exponential Backoff

```
Attempt 1: Immediate (0s delay)
Attempt 2: 0.5s delay
Attempt 3: 1.0s delay (0.5 × 2.0)
Attempt 4: 2.0s delay (1.0 × 2.0)
```

### When to Retry

**Retry These (Transient):**
- ✅ 500 Internal Server Error
- ✅ 502 Bad Gateway
- ✅ 503 Service Unavailable
- ✅ 504 Gateway Timeout
- ✅ Network connection errors

**Don't Retry These (Permanent):**
- ❌ 400 Bad Request
- ❌ 401 Unauthorized
- ❌ 403 Forbidden
- ❌ 404 Not Found
- ❌ 422 Validation Error

## Production Considerations

**Rate Limiting:**
- Add delays between retries to respect rate limits
- Use `backoff_multiplier` to increase delays exponentially
- Consider API provider's retry policies

**Max Attempts:**
- Set realistic retry limits (3-5 typically sufficient)
- Balance between resilience and execution time
- Consider SLA requirements

**Monitoring:**
- Log all retry attempts for debugging
- Track retry success/failure rates
- Alert on excessive retries (may indicate systemic issue)

## Implementation Details

**Worker-Side Retry Architecture:**

1. **Execution Path:**
   - HTTP task with `retry.on_success` → routes through `execute_with_retry()` wrapper
   - Wrapper instantiates `UnifiedRetryPolicy` with both `on_error` and `on_success` policies
   - Calls `_execute_with_success_retry()` for pagination loop
   - Each iteration wrapped with `_execute_iteration_with_error_retry()` for resilience

2. **Error Detection:**
   - HTTP executor returns `{status: 'error', data: {status_code: 500, ...}}` for errors
   - `RetryPolicy.should_retry()` extracts `error.status` from response structure
   - Evaluates Jinja2 condition: `{{ error.status in [500, 502, 503] }}`
   - Returns `True` if condition matches and attempts < max_attempts

3. **Pagination Continuation:**
   - After successful response (even post-retry), evaluates `on_success.while` condition
   - If `True`: applies `next_call` transforms to update request parameters
   - Aggregates page data using `collect.strategy` (append/merge/replace)
   - Continues loop until condition becomes `False` or max_attempts reached

4. **Result Structure:**
   - Final result: `{status: 'success', data: [all_items], meta: {iterations: 4, ...}}`
   - Server receives single aggregated result, not per-page results
   - Validation step receives merged data array

**Key Configuration Fields:**
- `retry.on_error.when`: Jinja2 expression with access to `error.status`, `error.message`
- `retry.on_success.while`: Jinja2 expression with access to `response.paging.hasMore`
- `retry.on_error.max_attempts`: Per-iteration retry limit (3)
- `retry.on_success.max_attempts`: Total pagination iterations limit (10)
