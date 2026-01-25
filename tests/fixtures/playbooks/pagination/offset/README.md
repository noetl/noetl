# Offset-Based Pagination Test

This folder contains a test for **offset-based pagination** using NoETL's unified retry system with `retry.on_success`.

## 🎯 Test Type

**✅ Offset-Based Pagination**
- Explicit offset + limit parameters
- Direct control over data window
- Common in SQL-backed APIs

## Overview

The `test_pagination_offset.yaml` playbook demonstrates **offset-based pagination** where:
- API uses `offset` and `limit` parameters
- Server returns `has_more` flag for continuation
- NoETL automatically increments offset by limit
- Results are merged using `append` strategy

**Test Scenario:**
- **Endpoint**: `/api/v1/users`
- **Limit**: 10 items per request
- **Total Items**: 35 (requires 4 pages)
- **Continuation**: `response.has_more == true`

## Files

- `test_pagination_offset.yaml` - Playbook definition with offset pagination
- `test_offset_pagination.ipynb` - **Validation notebook**
- `README.md` - This file

## Pagination Configuration

```yaml
retry:
  on_success:
    while: "{{ response.has_more == true }}"
    max_attempts: 10
    next_call:
      params:
        offset: "{{ (response.offset | int) + (response.limit | int) }}"
        limit: "{{ response.limit }}"
    collect:
      strategy: append
      path: users
      into: pages
```

**Key Features:**
- **While condition**: Continue while `has_more == true`
- **Next page**: Calculate `offset + limit` for next window
- **Merge strategy**: Append `users` arrays from each page
- **Safety limit**: Max 10 attempts to prevent infinite loops

## Expected Response Format

```json
{
  "users": [
    {"id": 1, "name": "Alice", "email": "alice@example.com"},
    {"id": 2, "name": "Bob", "email": "bob@example.com"}
  ],
  "offset": 0,
  "limit": 10,
  "has_more": true,
  "total": 35
}
```

**Last Page Response:**
```json
{
  "users": [
    {"id": 35, "name": "Zoe", "email": "zoe@example.com"}
  ],
  "offset": 30,
  "limit": 10,
  "has_more": false,
  "total": 35
}
```

## How to Run

### Option 1: Using Notebook (Recommended)
```bash
# Open and run all cells
jupyter notebook test_offset_pagination.ipynb
```

### Option 2: Using NoETL API
```bash
curl -X POST http://localhost:8082/api/run/playbook \
  -H "Content-Type: application/json" \
  -d '{"path": "tests/pagination/offset"}'
```

### Option 3: Using NoETL CLI
```bash
noetl run tests/fixtures/playbooks/pagination/offset/test_pagination_offset.yaml
```

## Expected Results

**✅ Success Criteria:**
- All 35 users fetched across 4 pages
- Final merged result has length 35
- Pagination stopped automatically when `has_more == false`
- All users have sequential IDs (1-35)
- Offset progression: 0 → 10 → 20 → 30

**📊 Event Flow:**
1. `playbook_started` - Execution begins
2. `action_started` - First HTTP call (offset=0)
3. `action_completed` - Page 1 fetched (10 users, offset=0)
4. `action_started` - Page 2 (offset=10)
5. `action_completed` - Page 2 fetched (10 users, offset=10)
6. `action_started` - Page 3 (offset=20)
7. `action_completed` - Page 3 fetched (10 users, offset=20)
8. `action_started` - Page 4 (offset=30)
9. `action_completed` - Page 4 fetched (5 users, offset=30)
10. `step_completed` - Pagination finished
11. `playbook_completed` - Success

## Validation

The notebook validates:
- ✅ Total user count (35 users)
- ✅ No duplicate users
- ✅ Sequential IDs (1 through 35)
- ✅ Correct offset progression (0, 10, 20, 30)
- ✅ Merge strategy worked correctly

## Offset Pagination Considerations

**Advantages:**
- ✅ Simple mental model (skip N, take M)
- ✅ Random access to any page
- ✅ Can jump to arbitrary positions

**Disadvantages:**
- ⚠️ Performance degrades with large offsets
- ⚠️ "Page drift" if data changes during pagination
- ⚠️ Database OFFSET query can be slow

**When to Use:**
- Small to medium datasets
- User-facing pagination with page numbers
- Rarely need deep pagination
- Stable dataset during fetch

**When to Avoid:**
- Very large datasets (millions of rows)
- Real-time data with frequent inserts
- APIs with cursor support available

## Implementation Details

**Server-Side:**
- SQL: `SELECT * FROM users LIMIT 10 OFFSET 0`
- Next: `SELECT * FROM users LIMIT 10 OFFSET 10`
- Offset increments by limit each time

**Client-Side (NoETL):**
- Automatic offset calculation from response
- Expression: `(offset | int) + (limit | int)`
- Continues until `has_more == false`
- Merges all pages into single array
