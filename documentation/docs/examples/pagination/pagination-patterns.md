---
sidebar_position: 1
title: Pagination Patterns
description: HTTP pagination patterns for fetching large datasets
---

# Pagination Patterns

NoETL supports multiple HTTP pagination patterns for efficiently fetching large datasets from APIs.

## Overview

When fetching paginated data, use the `loop.pagination` block on HTTP steps:

```yaml
- step: fetch_all_data
  tool: http
  method: GET
  endpoint: "https://api.example.com/data"
  params:
    page: 1
  loop:
    pagination:
      type: response_based
      continue_while: "{{ response.data.hasMore }}"
      next_page:
        params:
          page: "{{ (response.data.page | int) + 1 }}"
      merge_strategy: append
      merge_path: data.items
      max_iterations: 100
```

## Pagination Types

### Page-Number Pagination

The most common pattern using `page` and `pageSize` parameters:

```yaml
- step: fetch_assessments
  tool: http
  method: GET
  endpoint: "https://api.example.com/assessments"
  params:
    page: 1
    pageSize: 10
  loop:
    pagination:
      type: response_based
      continue_while: "{{ response.data.paging.hasMore }}"
      next_page:
        params:
          page: "{{ (response.data.paging.page | int) + 1 }}"
      merge_strategy: append
      merge_path: data.data
      max_iterations: 50
```

**Use Case:** Most REST APIs, user-facing pagination

**API Response Example:**
```json
{
  "data": [
    {"id": 1, "name": "Item 1"},
    {"id": 2, "name": "Item 2"}
  ],
  "paging": {
    "page": 1,
    "pageSize": 10,
    "hasMore": true,
    "total": 35
  }
}
```

### Offset-Based Pagination

SQL-style `offset` and `limit` parameters:

```yaml
- step: fetch_users
  tool: http
  method: GET
  endpoint: "https://api.example.com/users"
  params:
    offset: 0
    limit: 10
  loop:
    pagination:
      type: response_based
      continue_while: "{{ response.data.has_more }}"
      next_page:
        params:
          offset: "{{ (response.data.offset | int) + (response.data.limit | int) }}"
      merge_strategy: append
      merge_path: data.data
      max_iterations: 100
```

**Use Case:** SQL-backed APIs, direct database pagination

**API Response Example:**
```json
{
  "data": [...],
  "offset": 0,
  "limit": 10,
  "total": 100,
  "has_more": true
}
```

### Cursor-Based Pagination

Opaque cursor tokens for stateless navigation:

```yaml
- step: fetch_events
  tool: http
  method: GET
  endpoint: "https://api.example.com/events"
  params:
    cursor: ""
    limit: 10
  loop:
    pagination:
      type: response_based
      continue_while: "{{ response.data.next_cursor is defined and response.data.next_cursor }}"
      next_page:
        params:
          cursor: "{{ response.data.next_cursor }}"
      merge_strategy: append
      merge_path: data.events
      max_iterations: 100
```

**Use Case:** GraphQL APIs, cloud services (AWS, GCP), large datasets

**API Response Example:**
```json
{
  "events": [...],
  "next_cursor": "eyJpZCI6MTAwfQ==",
  "has_more": true
}
```

## Configuration Options

### Pagination Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `type` | string | Yes | Pagination type: `response_based` |
| `continue_while` | string | Yes | Jinja2 condition to continue |
| `next_page` | object | Yes | Parameters for next request |
| `merge_strategy` | string | Yes | How to merge results: `append`, `replace` |
| `merge_path` | string | Yes | JSON path to extract items from response |
| `max_iterations` | int | No | Safety limit (default: 100) |

### Merge Strategies

**append**: Accumulate items from all pages
```yaml
merge_strategy: append
merge_path: data.items
# Result: [page1_items..., page2_items..., page3_items...]
```

**replace**: Only keep last page (useful for summary)
```yaml
merge_strategy: replace
merge_path: data
# Result: {last_page_data}
```

## Advanced Patterns

### Pagination with Retry

Handle transient failures during pagination:

```yaml
- step: fetch_with_retry
  tool: http
  method: GET
  endpoint: "https://api.example.com/flaky-endpoint"
  params:
    page: 1
  retry:
    max_attempts: 3
    initial_delay: 1.0
    backoff_multiplier: 2.0
    retryable_status_codes: [429, 500, 502, 503, 504]
  loop:
    pagination:
      type: response_based
      continue_while: "{{ response.data.hasMore }}"
      next_page:
        params:
          page: "{{ (response.data.page | int) + 1 }}"
      merge_strategy: append
      merge_path: data.items
```

### Safety Limits

Prevent infinite loops with `max_iterations`:

```yaml
- step: limited_fetch
  tool: http
  method: GET
  endpoint: "https://api.example.com/large-dataset"
  params:
    page: 1
  loop:
    pagination:
      type: response_based
      continue_while: "{{ response.data.hasMore }}"
      next_page:
        params:
          page: "{{ (response.data.page | int) + 1 }}"
      merge_strategy: append
      merge_path: data.items
      max_iterations: 5  # Only fetch first 5 pages
```

**Use Case:** Data sampling, cost control, time-constrained jobs

### Iterator with Pagination

Process multiple endpoints, each with pagination:

```yaml
workflow:
  - step: start
    next:
      - step: iterate_endpoints

  - step: iterate_endpoints
    tool: iterator
    collection: "{{ workload.api_endpoints }}"
    element: current_endpoint
    mode: sequential
    next:
      - step: fetch_endpoint_data

  - step: fetch_endpoint_data
    tool: http
    method: GET
    endpoint: "{{ vars.current_endpoint.url }}"
    params:
      page: 1
    loop:
      pagination:
        type: response_based
        continue_while: "{{ response.data.hasMore }}"
        next_page:
          params:
            page: "{{ (response.data.page | int) + 1 }}"
        merge_strategy: append
        merge_path: data.items
    next:
      - step: process_data

  - step: process_data
    tool: python
    code: |
      def main(items, endpoint_name):
          return {
              "endpoint": endpoint_name,
              "item_count": len(items),
              "status": "complete"
          }
    args:
      items: "{{ fetch_endpoint_data.data }}"
      endpoint_name: "{{ vars.current_endpoint.name }}"
    next:
      - step: end

  - step: end
```

## Complete Example

Fetch all users and save to PostgreSQL:

```yaml
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: paginated_data_sync
  path: examples/pagination/sync_users

workload:
  api_base_url: "https://api.example.com"

workflow:
  - step: start
    next:
      - step: fetch_all_users

  - step: fetch_all_users
    tool: http
    method: GET
    endpoint: "{{ workload.api_base_url }}/users"
    params:
      page: 1
      per_page: 100
    loop:
      pagination:
        type: response_based
        continue_while: "{{ response.data.meta.has_more }}"
        next_page:
          params:
            page: "{{ (response.data.meta.page | int) + 1 }}"
        merge_strategy: append
        merge_path: data.users
        max_iterations: 100
    vars:
      all_users: "{{ result.data }}"
    next:
      - step: save_to_database

  - step: save_to_database
    tool: postgres
    auth:
      type: postgres
      credential: app_database
    query: |
      INSERT INTO users (id, email, name, created_at)
      SELECT 
        (u->>'id')::int,
        u->>'email',
        u->>'name',
        (u->>'created_at')::timestamp
      FROM jsonb_array_elements('{{ vars.all_users | tojson }}'::jsonb) u
      ON CONFLICT (id) DO UPDATE SET
        email = EXCLUDED.email,
        name = EXCLUDED.name
    vars:
      rows_affected: "{{ result.data.command_1[0].count }}"
    next:
      - step: log_complete

  - step: log_complete
    tool: python
    code: |
      def main(user_count, rows_affected):
          return {
              "status": "complete",
              "users_fetched": user_count,
              "rows_affected": rows_affected
          }
    args:
      user_count: "{{ vars.all_users | length }}"
      rows_affected: "{{ vars.rows_affected }}"
    next:
      - step: end

  - step: end
```

## Response Format

After pagination completes, the step result contains merged data:

```json
{
  "id": "task-uuid",
  "status": "success",
  "data": [
    // All items from all pages merged together
    {"id": 1, "name": "User 1"},
    {"id": 2, "name": "User 2"},
    // ... up to max_iterations * page_size items
  ]
}
```

## Best Practices

1. **Always set `max_iterations`**: Prevent runaway pagination
2. **Use appropriate page sizes**: Balance between requests and payload size
3. **Handle rate limits**: Add retry configuration for 429 responses
4. **Log progress**: Use Python steps to track pagination progress
5. **Test with small limits first**: Validate logic before full fetch

## See Also

- [HTTP Tool Reference](/docs/reference/tools/http)
- [HTTP Pagination Quick Reference](/docs/reference/http_pagination_quick_reference)
- [Retry Configuration](/docs/reference/unified_retry)
