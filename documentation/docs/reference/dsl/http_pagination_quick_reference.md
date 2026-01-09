# HTTP Pagination - Quick Reference

## Important: HTTP Response Wrapper

**All HTTP responses are wrapped** by the executor as:
```json
{
  "id": "task-id",
  "status": "success",
  "data": {
    // Your actual API response here
  }
}
```

This means:
- Use `response.data.*` to access API fields (not `response.*`)
- Use `merge_path: data.fieldName` to extract data (accounts for wrapper)

## Minimal Example

```yaml
- step: fetch_data
  tool:
    kind: http
    url: "{{ api_url }}/data"
    params:
      page: 1
  loop:
    pagination:
      type: response_based
      continue_while: "{{ response.data.hasMore }}"
      next_page:
        params:
          page: "{{ response.data.page + 1 }}"
      merge_strategy: append
      merge_path: data.data
```

## Pagination Types

### Page Number
```yaml
continue_while: "{{ response.data.paging.hasMore == true }}"
next_page:
  params:
    page: "{{ (response.data.paging.page | int) + 1 }}"
merge_path: data.data  # Extract from wrapper then API response
```

### Offset-Based
```yaml
continue_while: "{{ response.data.has_more }}"
next_page:
  params:
    offset: "{{ response.data.offset + response.data.limit }}"
merge_path: data.users
```

### Cursor-Based
```yaml
continue_while: "{{ response.data.next_cursor is not none }}"
next_page:
  params:
    cursor: "{{ response.data.next_cursor }}"
merge_path: data.events
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

- `{{ response }}` - HTTP executor result: `{id, status, data: <api_response>}`
- `{{ response.data }}` - Actual API response (use this for API fields)
- `{{ iteration }}` - Current iteration (0-based)
- `{{ accumulated }}` - Merged data so far
- `{{ workload.* }}` - Global variables
- `{{ vars.* }}` - Execution variables

**Remember**: Always use `response.data.*` to access API response fields!

## Common Patterns

### GitHub API
```yaml
continue_while: "{{ response.data | length == 100 }}"
next_page:
  params:
    page: "{{ iteration + 2 }}"
merge_path: data  # GitHub API returns array directly
```

### REST API with hasMore
```yaml
continue_while: "{{ response.data.meta.hasMore }}"
next_page:
  params:
    page: "{{ response.data.meta.page + 1 }}"
merge_path: data.items
```

### GraphQL Cursor
```yaml
continue_while: "{{ response.data.data.pageInfo.hasNextPage }}"
next_page:
  body:
    variables:
      cursor: "{{ response.data.data.pageInfo.endCursor }}"
merge_path: data.data.items
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
- `noetl/tools/controller/iterator/pagination.py` - Executor
- `noetl/tools/controller/iterator/config.py` - Config extraction
- `noetl/tools/controller/iterator/executor.py` - Delegation logic

**Tests:**
- `tests/fixtures/servers/paginated_api.py` - Mock server
- `tests/fixtures/playbooks/pagination/*.yaml` - Test playbooks
- `tests/scripts/test_pagination.sh` - Test runner

**Documentation:**
- `documentation/docs/features/pagination_design.md` - Design document
- `documentation/docs/features/pagination.md` - User guide
