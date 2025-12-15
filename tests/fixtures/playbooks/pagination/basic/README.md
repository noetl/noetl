# Basic Page-Number Pagination Test

This folder contains a test for **basic page-number pagination** using NoETL's unified retry system with `retry.on_success`.

## 🎯 Test Type

**✅ Page-Number Pagination**
- Simple numeric page parameter
- Most common pagination pattern
- Backend calculates offset automatically

## Overview

The `test_pagination_basic.yaml` playbook demonstrates **page-number based pagination** where:
- API uses `page` parameter (starts at 1)
- Server tracks current page and returns `hasMore` flag
- NoETL automatically continues fetching until `hasMore == false`
- Results are merged using `append` strategy

**Test Scenario:**
- **Endpoint**: `/api/v1/assessments`
- **Page Size**: 10 items per page
- **Total Items**: 35 (requires 4 pages)
- **Continuation**: `response.paging.hasMore == true`

## Files

- `test_pagination_basic.yaml` - Playbook definition with page-number pagination
- `test_basic_pagination.ipynb` - **Validation notebook**
- `README.md` - This file

## Pagination Configuration

```yaml
retry:
  on_success:
    while: "{{ response.paging.hasMore == true }}"
    max_attempts: 10
    next_call:
      params:
        page: "{{ (response.paging.page | int) + 1 }}"
        pageSize: "{{ response.paging.pageSize }}"
    collect:
      strategy: append
      path: data
      into: pages
```

**Key Features:**
- **While condition**: Continue while `paging.hasMore == true`
- **Next page**: Increment page number by 1
- **Merge strategy**: Append `data` arrays from each page
- **Safety limit**: Max 10 attempts to prevent infinite loops

## Expected Response Format

```json
{
  "data": [
    {"id": 1, "title": "Assessment 1"},
    {"id": 2, "title": "Assessment 2"}
  ],
  "paging": {
    "page": 1,
    "pageSize": 10,
    "hasMore": true,
    "total": 35
  }
}
```

## How to Run

### Option 1: Using Notebook (Recommended)
```bash
# Open and run all cells
jupyter notebook test_basic_pagination.ipynb
```

### Option 2: Using NoETL API
```bash
curl -X POST http://localhost:8082/api/run/playbook \
  -H "Content-Type: application/json" \
  -d '{"path": "tests/pagination/basic"}'
```

### Option 3: Using Task Runner
```bash
task test:pagination:basic
```

## Expected Results

**✅ Success Criteria:**
- All 35 items fetched across 4 pages
- Final merged result has length 35
- Pagination stopped automatically when `hasMore == false`
- All items have sequential IDs (1-35)

**📊 Event Flow:**
1. `playbook_started` - Execution begins
2. `action_started` - First HTTP call (page 1)
3. `action_completed` - Page 1 fetched (10 items)
4. `action_started` - Page 2 (automatic)
5. `action_completed` - Page 2 fetched (10 items)
6. `action_started` - Page 3
7. `action_completed` - Page 3 fetched (10 items)
8. `action_started` - Page 4
9. `action_completed` - Page 4 fetched (5 items)
10. `step_completed` - Pagination finished
11. `playbook_completed` - Success

## Validation

The notebook validates:
- ✅ Total item count (35 items)
- ✅ No duplicate items
- ✅ Sequential IDs (1 through 35)
- ✅ Correct page count (4 pages)
- ✅ Merge strategy worked correctly

## Implementation Details

**Server-Side:**
- Pagination state tracked in `retry.on_success` context
- Each page result stored temporarily
- Merge happens after all pages fetched
- Result stored in `pages` variable

**Benefits:**
- Clean playbook syntax
- Automatic continuation logic
- Built-in safety limits
- Declarative merge strategies
