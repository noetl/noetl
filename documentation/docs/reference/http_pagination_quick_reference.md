# HTTP Pagination - Quick Reference

## Minimal Example

```yaml
- step: fetch_data
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

## Pagination Types

### Page Number
```yaml
continue_while: "{{ response.paging.hasMore == true }}"
next_page:
  params:
    page: "{{ (response.paging.page | int) + 1 }}"
```

### Offset-Based
```yaml
continue_while: "{{ response.has_more }}"
next_page:
  params:
    offset: "{{ response.offset + response.limit }}"
```

### Cursor-Based
```yaml
continue_while: "{{ response.next_cursor is not none }}"
next_page:
  params:
    cursor: "{{ response.next_cursor }}"
```

## Merge Strategies

- **append** - Concatenate arrays: `[1,2] + [3,4] = [1,2,3,4]`
- **extend** - Flatten nested: `[[1,2],[3,4]] = [1,2,3,4]`
- **replace** - Keep last only
- **collect** - Store all responses: `[resp1, resp2, ...]`

## With Retry

```yaml
pagination:
  retry:
    max_attempts: 3
    backoff: exponential
    initial_delay: 1
    max_delay: 30
```

## Safety Limits

```yaml
pagination:
  max_iterations: 100  # Prevent infinite loops
```

## Available Variables

In `continue_while` and `next_page` expressions:

- `{{ response }}` - Current HTTP response
- `{{ iteration }}` - Current iteration (0-based)
- `{{ accumulated }}` - Merged data so far
- `{{ workload.* }}` - Global variables
- `{{ vars.* }}` - Execution variables

## Common Patterns

### GitHub API
```yaml
continue_while: "{{ response | length == 100 }}"
next_page:
  params:
    page: "{{ iteration + 2 }}"
```

### REST API with hasMore
```yaml
continue_while: "{{ response.meta.hasMore }}"
next_page:
  params:
    page: "{{ response.meta.page + 1 }}"
```

### GraphQL Cursor
```yaml
continue_while: "{{ response.data.pageInfo.hasNextPage }}"
next_page:
  body:
    variables:
      cursor: "{{ response.data.pageInfo.endCursor }}"
```

## Testing

```bash
# Start mock server
python tests/fixtures/servers/paginated_api.py 5555

# Run tests
./tests/scripts/test_pagination.sh
```

## Files

**Implementation:**
- `noetl/plugin/controller/iterator/pagination.py` - Executor
- `noetl/plugin/controller/iterator/config.py` - Config extraction
- `noetl/plugin/controller/iterator/executor.py` - Delegation logic

**Tests:**
- `tests/fixtures/servers/paginated_api.py` - Mock server
- `tests/fixtures/playbooks/pagination/*.yaml` - Test playbooks
- `tests/scripts/test_pagination.sh` - Test runner

**Documentation:**
- `docs/http_pagination_design.md` - Design document
- `documentation/docs/features/pagination.md` - User guide
