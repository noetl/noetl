# Pagination Test Playbooks

This directory contains test playbooks for the HTTP pagination feature.

## Test Coverage

### test_pagination_basic.yaml
Page-number based pagination (most common pattern):
- Uses `page` and `pageSize` parameters
- Continues while `hasMore == true`
- Merges `data` arrays from each response
- Validates all 35 items fetched

### test_pagination_offset.yaml
Offset-based pagination:
- Uses `offset` and `limit` parameters
- Continues while `has_more == true`
- Merges `users` arrays from each response
- Validates all 35 users fetched

### test_pagination_cursor.yaml
Cursor-based pagination:
- Uses opaque `cursor` token
- Continues while `next_cursor` is not null/empty
- Merges `events` arrays from each response
- Validates all 35 events fetched

### test_pagination_retry.yaml
Pagination with retry mechanism:
- Page 2 configured to fail initially
- Retry config: 3 attempts, exponential backoff
- Validates retry succeeded and all items fetched

### test_pagination_max_iterations.yaml
Safety limit testing:
- `max_iterations: 2` stops after 2 pages
- Validates only 20 items fetched (not all 35)
- Ensures infinite loop protection works

### loop_with_pagination/ (Dedicated Test Suite)
Complete test suite for combining iterator loops with HTTP pagination.

**Contains:**
- `test_loop_with_pagination.yaml` - Playbook definition
- `pagination_loop_test.ipynb` - Interactive validation notebook
- `README.md` - Comprehensive documentation

**Features:**
- Iterator loop over multiple endpoints
- HTTP pagination via success-side retry per endpoint
- PostgreSQL persistence per iteration
- 5 automated validation checks
- Interactive visualizations

**See:** `loop_with_pagination/README.md` for detailed usage

## Mock Server

The test server (`tests/fixtures/servers/paginated_api.py`) provides:
- FastAPI-based implementation
- 35 total items across endpoints
- 10 items per page (default)
- Realistic pagination metadata
- Configurable failure injection for retry testing

## Running Tests

```bash
# Start mock server (in separate terminal)
python tests/fixtures/servers/paginated_api.py 5555

# Run all pagination tests
./tests/scripts/test_pagination.sh

# Run individual test
task test-pagination-basic-full
```

## Expected Results

All tests should pass:
- ✅ Basic pagination fetches all 35 items
- ✅ Offset pagination fetches all 35 users
- ✅ Cursor pagination fetches all 35 events
- ✅ Retry recovers from failures
- ✅ Max iterations limit enforced (20 items only)
