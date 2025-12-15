# Max Iterations Safety Limit Test

This folder contains a test for **max_iterations safety limit** using NoETL's unified retry system with `retry.on_success`.

## 🎯 Test Type

**✅ Safety Limit Protection**
- Prevents infinite pagination loops
- Controlled data fetching
- Resource usage protection

## Overview

The `test_pagination_max_iterations.yaml` playbook demonstrates **max_attempts safety limit** where:
- API has more pages available than max_attempts
- NoETL stops pagination after reaching max_attempts
- Prevents runaway pagination loops
- Useful for controlled data sampling

**Test Scenario:**
- **Endpoint**: `/api/v1/assessments`
- **Page Size**: 10 items per page
- **Total Available**: 35 items (4 pages)
- **Max Attempts**: 2 (fetch only first 2 pages)
- **Expected Items**: 20 (2 pages × 10 items)

## Files

- `test_pagination_max_iterations.yaml` - Playbook definition with limited pagination
- `test_max_iterations.ipynb` - **Validation notebook**
- `README.md` - This file

## Pagination Configuration

```yaml
retry:
  on_success:
    while: "{{ response.paging.hasMore == true }}"
    max_attempts: 2  # ONLY FETCH 2 PAGES
    next_call:
      params:
        page: "{{ (response.paging.page | int) + 1 }}"
    collect:
      strategy: append
      path: data
      into: pages
```

**Key Features:**
- **While condition**: Continue while `paging.hasMore == true` (still true after 2 pages)
- **Max attempts**: Hard limit of 2 pages regardless of hasMore
- **Actual behavior**: Stops at 20 items (not all 35)
- **Safety first**: Prevents infinite loops from buggy APIs

## Expected Response Format

**Page 1:**
```json
{
  "data": [{"id": 1}, {"id": 2}, ..., {"id": 10}],
  "paging": {
    "page": 1,
    "pageSize": 10,
    "hasMore": true,
    "total": 35
  }
}
```

**Page 2 (Last fetched):**
```json
{
  "data": [{"id": 11}, {"id": 12}, ..., {"id": 20}],
  "paging": {
    "page": 2,
    "pageSize": 10,
    "hasMore": true,  # Still true, but max_attempts reached
    "total": 35
  }
}
```

## How to Run

### Option 1: Using Notebook (Recommended)
```bash
# Open and run all cells
jupyter notebook test_max_iterations.ipynb
```

### Option 2: Using NoETL API
```bash
curl -X POST http://localhost:8082/api/run/playbook \
  -H "Content-Type: application/json" \
  -d '{"path": "tests/pagination/max_iterations"}'
```

### Option 3: Using Task Runner
```bash
task test:pagination:max-iterations
```

## Expected Results

**✅ Success Criteria:**
- Only 20 items fetched (not all 35)
- Pagination stopped after 2 pages
- `max_attempts` limit respected
- No infinite loop
- Validation confirms exactly 20 items

**📊 Event Flow:**
1. `playbook_started` - Execution begins
2. `action_started` - First HTTP call (page 1)
3. `action_completed` - Page 1 fetched (10 items, hasMore=true)
4. `action_started` - Page 2 (automatic)
5. `action_completed` - Page 2 fetched (10 items, hasMore=true)
6. **STOP** - max_attempts=2 reached (even though hasMore=true)
7. `step_completed` - Pagination finished early
8. `playbook_completed` - Success

**Note:** No page 3 or 4 fetched despite `hasMore=true`

## Validation

The notebook validates:
- ✅ Total item count = 20 (not 35)
- ✅ Page count = 2 (stopped early)
- ✅ Sequential IDs (1 through 20 only)
- ✅ max_attempts enforced correctly
- ✅ No infinite loop occurred

## Use Cases

**1. Data Sampling:**
```yaml
# Fetch first 100 records for preview
max_attempts: 10  # 10 pages × 10 items
```

**2. Cost Control:**
```yaml
# Limit API calls to prevent billing issues
max_attempts: 50
```

**3. Time Constraints:**
```yaml
# Batch job with time limit
max_attempts: 100  # Fetch what we can in time window
```

**4. Safety Net:**
```yaml
# Protect against infinite loops from buggy APIs
max_attempts: 1000  # Reasonable upper bound
```

## Comparison with Unlimited Pagination

| Aspect | Unlimited (max_attempts: 10000) | Limited (max_attempts: 2) |
|--------|--------------------------------|---------------------------|
| Items Fetched | All 35 | Only 20 |
| Pages Fetched | 4 | 2 |
| API Calls | 4 | 2 |
| Respects hasMore | Yes, until false | No, stops at limit |
| Use Case | Production data fetch | Sampling/preview |

## Implementation Details

**Server-Side:**
- Tracks attempt count independently
- Ignores `while` condition once max_attempts reached
- Returns partial results (20 items)
- No error or warning (intended behavior)

**Client-Side (NoETL):**
- Set appropriate max_attempts for your use case
- Consider data volume vs API rate limits
- Use conservative limits for untested APIs
- Monitor execution logs for "max attempts reached" messages
