# Cursor-Based Pagination Test

This folder contains a test for **cursor-based pagination** using NoETL's unified retry system with `retry.on_success`.

## 🎯 Test Type

**✅ Cursor-Based Pagination**
- Opaque cursor tokens for navigation
- Stateless and efficient for large datasets
- Common in modern REST APIs (GraphQL, cloud APIs)

## Overview

The `test_pagination_cursor.yaml` playbook demonstrates **cursor-based pagination** where:
- API returns `next_cursor` token for next page
- Client passes cursor in subsequent requests
- NoETL automatically continues until cursor is null/empty
- Results are merged using `append` strategy

**Test Scenario:**
- **Endpoint**: `/api/v1/events`
- **Page Size**: 10 items per request
- **Total Items**: 35 (requires 4 cursor hops)
- **Continuation**: `response.next_cursor` is not null/empty

## Files

- `test_pagination_cursor.yaml` - Playbook definition with cursor pagination
- `test_cursor_pagination.ipynb` - **Validation notebook**
- `README.md` - This file

## Pagination Configuration

```yaml
retry:
  on_success:
    while: "{{ response.next_cursor is not none and response.next_cursor != '' }}"
    max_attempts: 10
    next_call:
      params:
        cursor: "{{ response.next_cursor }}"
        limit: "{{ response.limit }}"
    collect:
      strategy: append
      path: events
      into: pages
```

**Key Features:**
- **While condition**: Continue while cursor exists and is not empty
- **Next page**: Pass `next_cursor` from previous response
- **Merge strategy**: Append `events` arrays from each page
- **Safety limit**: Max 10 attempts to prevent infinite loops

## Expected Response Format

```json
{
  "events": [
    {"id": 1, "type": "login", "timestamp": "2025-01-01T10:00:00Z"},
    {"id": 2, "type": "action", "timestamp": "2025-01-01T10:05:00Z"}
  ],
  "next_cursor": "eyJpZCI6MTB9",
  "limit": 10
}
```

**Last Page Response:**
```json
{
  "events": [
    {"id": 35, "type": "logout", "timestamp": "2025-01-01T12:00:00Z"}
  ],
  "next_cursor": null,
  "limit": 10
}
```

## How to Run

### Option 1: Using Notebook (Recommended)
```bash
# Open and run all cells
jupyter notebook test_cursor_pagination.ipynb
```

### Option 2: Using NoETL API
```bash
curl -X POST http://localhost:8082/api/run/playbook \
  -H "Content-Type: application/json" \
  -d '{"path": "tests/pagination/cursor"}'
```

### Option 3: Using Task Runner
```bash
task test:pagination:cursor
```

## Expected Results

**✅ Success Criteria:**
- All 35 events fetched across 4 cursor hops
- Final merged result has length 35
- Pagination stopped automatically when `next_cursor == null`
- All events have sequential IDs (1-35)

**📊 Event Flow:**
1. `playbook_started` - Execution begins
2. `action_started` - First HTTP call (no cursor)
3. `action_completed` - Page 1 fetched (10 events) with cursor A
4. `action_started` - Page 2 (cursor A)
5. `action_completed` - Page 2 fetched (10 events) with cursor B
6. `action_started` - Page 3 (cursor B)
7. `action_completed` - Page 3 fetched (10 events) with cursor C
8. `action_started` - Page 4 (cursor C)
9. `action_completed` - Page 4 fetched (5 events) with null cursor
10. `step_completed` - Pagination finished
11. `playbook_completed` - Success

## Validation

The notebook validates:
- ✅ Total event count (35 events)
- ✅ No duplicate events
- ✅ Sequential IDs (1 through 35)
- ✅ Correct cursor navigation (4 hops)
- ✅ Merge strategy worked correctly
- ✅ Cursor nulled on last page

## Advantages of Cursor Pagination

**vs Page Numbers:**
- ✅ No skipped/duplicate items during data changes
- ✅ Consistent performance (no OFFSET queries)
- ✅ Works well with real-time data

**vs Offset:**
- ✅ Efficient for large datasets
- ✅ Database-friendly (indexed seeks vs scans)
- ✅ Prevents "page drift" issues

## Implementation Details

**Server-Side:**
- Cursor encoded as base64 JSON: `{"id": 10}`
- Cursor points to last item in previous page
- Server decodes cursor and uses as WHERE condition
- Empty/null cursor signals end of data

**Client-Side (NoETL):**
- Opaque cursor handling (no decoding needed)
- Automatic null/empty detection
- Continuation until cursor disappears
- Clean merge of all pages
