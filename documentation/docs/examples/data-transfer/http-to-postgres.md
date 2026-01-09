---
sidebar_position: 1
title: HTTP to PostgreSQL
description: Transfer data from HTTP APIs to PostgreSQL databases
---

# HTTP to PostgreSQL Data Transfer

This guide demonstrates various patterns for transferring data from HTTP APIs to PostgreSQL databases.

:::tip Working Examples
Complete, tested data transfer playbooks are available in the repository:
- [tests/fixtures/playbooks/data_transfer/](https://github.com/noetl/noetl/tree/master/tests/fixtures/playbooks/data_transfer)
:::

## Pattern Overview

| Pattern | Complexity | Best For |
|---------|------------|----------|
| Transfer Tool | Low | Simple field mapping, production ETL |
| Python Batch | Medium | Custom transformations |
| Iterator | High | Large datasets, per-record logic |
| Direct SQL | Low | Quick prototypes |

## Transfer Tool Pattern

The simplest approach using NoETL's built-in transfer tool:

```yaml
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: http_to_postgres_transfer
  path: data_transfer/http_to_postgres_transfer

workload:
  api_url: "https://jsonplaceholder.typicode.com/posts"
  target_table: "public.posts"

workflow:
  - step: start
    next:
      - step: transfer_data

  - step: transfer_data
    tool: transfer
    source:
      type: http
      url: "{{ workload.api_url }}"
      method: GET
    target:
      type: postgres
      auth:
        type: postgres
        credential: pg_demo
      table: "{{ workload.target_table }}"
      mode: insert
    mapping:
      post_id: id
      user_id: userId
      title: title
      body: body
    next:
      - step: end

  - step: end
```

**Advantages:**
- No code required
- Declarative field mapping
- Built-in error handling
- Automatic batching

## Python Batch Pattern

For custom transformations and validation:

```yaml
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: http_to_postgres_python
  path: data_transfer/http_to_postgres_python

workload:
  api_url: "https://jsonplaceholder.typicode.com/posts"

workflow:
  - step: start
    next:
      - step: fetch_data

  - step: fetch_data
    tool: http
    method: GET
    endpoint: "{{ workload.api_url }}"
    vars:
      posts: "{{ result.data }}"
    next:
      - step: transform_data

  - step: transform_data
    tool:
      kind: python
      code: |
      def main(posts):
          """Transform and validate posts data."""
          transformed = []
          for post in posts:
              # Validate required fields
              if not post.get('id') or not post.get('title'):
                  continue
              
              transformed.append({
                  'post_id': post['id'],
                  'user_id': post.get('userId', 0),
                  'title': post['title'][:255],  # Truncate if needed
                  'body': post.get('body', '')[:1000],
                  'word_count': len(post.get('body', '').split())
              })
          
          return {'records': transformed, 'count': len(transformed)}
    args:
      posts: "{{ vars.posts }}"
    vars:
      transformed_posts: "{{ result.data.records }}"
    next:
      - step: insert_data

  - step: insert_data
    tool:
      kind: postgres
      auth:
      type: postgres
      credential: pg_demo
    query: |
      INSERT INTO public.posts (post_id, user_id, title, body, word_count)
      SELECT 
        (p->>'post_id')::int,
        (p->>'user_id')::int,
        p->>'title',
        p->>'body',
        (p->>'word_count')::int
      FROM jsonb_array_elements('{{ vars.transformed_posts | tojson }}'::jsonb) p
      ON CONFLICT (post_id) DO UPDATE SET
        title = EXCLUDED.title,
        body = EXCLUDED.body,
        word_count = EXCLUDED.word_count
      RETURNING post_id;
    vars:
      inserted_count: "{{ result.data.command_1 | length }}"
    next:
      - step: end

  - step: end
```

**Advantages:**
- Full control over transformations
- Custom validation logic
- Dynamic field generation

## Iterator Pattern

For large datasets or per-record processing:

```yaml
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: http_to_postgres_iterator
  path: data_transfer/http_to_postgres_iterator

workload:
  api_url: "https://jsonplaceholder.typicode.com/posts"

workflow:
  - step: start
    next:
      - step: fetch_data

  - step: fetch_data
    tool:
      kind: http
      method: GET
      endpoint: "{{ workload.api_url }}"
    vars:
      all_posts: "{{ result.data }}"
    next:
      - step: process_posts

  - step: process_posts
    tool: iterator
    collection: "{{ vars.all_posts }}"
    element: current_post
    mode: sequential
    next:
      - step: insert_post

  - step: insert_post
    tool:
      kind: postgres
      auth:
      type: postgres
      credential: pg_demo
    query: |
      INSERT INTO public.posts (post_id, user_id, title, body)
      VALUES (
        {{ vars.current_post.id }},
        {{ vars.current_post.userId }},
        '{{ vars.current_post.title | replace("'", "''") }}',
        '{{ vars.current_post.body | replace("'", "''") }}'
      )
      ON CONFLICT (post_id) DO UPDATE SET
        title = EXCLUDED.title,
        body = EXCLUDED.body;
    next:
      - step: end

  - step: end
```

**Advantages:**
- Lower memory footprint
- Per-record error handling
- Progress tracking

## Direct SQL Pattern

Quick prototyping with direct JSON insertion:

```yaml
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: http_to_postgres_direct
  path: data_transfer/http_to_postgres_direct

workload:
  api_url: "https://jsonplaceholder.typicode.com/posts"

workflow:
  - step: start
    next:
      - step: fetch_and_insert

  - step: fetch_and_insert
    tool:
      kind: http
      method: GET
      endpoint: "{{ workload.api_url }}"
    vars:
      raw_data: "{{ result.data }}"
    next:
      - step: bulk_insert

  - step: bulk_insert
    tool:
      kind: postgres
      auth:
      type: postgres
      credential: pg_demo
    query: |
      INSERT INTO public.posts_raw (data, fetched_at)
      VALUES (
        '{{ vars.raw_data | tojson }}'::jsonb,
        NOW()
      );
    next:
      - step: end

  - step: end
```

**Advantages:**
- Minimal configuration
- Fast prototyping
- Preserves raw data

## Paginated API Transfer

For APIs with pagination:

```yaml
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: paginated_api_transfer
  path: data_transfer/paginated_api

workload:
  api_base: "https://api.example.com"

workflow:
  - step: start
    next:
      - step: fetch_all_pages

  - step: fetch_all_pages
    tool:
      kind: http
      method: GET
      endpoint: "{{ workload.api_base }}/items"
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
        merge_path: data.items
        max_iterations: 50
    vars:
      all_items: "{{ result.data }}"
    next:
      - step: batch_insert

  - step: batch_insert
    tool:
      kind: python
      code: |
      def main(items, batch_size=1000):
          """Split items into batches for efficient insertion."""
          batches = []
          for i in range(0, len(items), batch_size):
              batches.append(items[i:i+batch_size])
          return {
              'batches': batches,
              'total_items': len(items),
              'batch_count': len(batches)
          }
    args:
      items: "{{ vars.all_items }}"
    vars:
      batches: "{{ result.data.batches }}"
    next:
      - step: insert_batches

  - step: insert_batches
    tool: iterator
    collection: "{{ vars.batches }}"
    element: batch
    mode: sequential
    next:
      - step: insert_batch

  - step: insert_batch
    tool:
      kind: postgres
      auth:
      type: postgres
      credential: pg_demo
    query: |
      INSERT INTO public.items (id, name, value, updated_at)
      SELECT 
        (item->>'id')::int,
        item->>'name',
        (item->>'value')::numeric,
        NOW()
      FROM jsonb_array_elements('{{ vars.batch | tojson }}'::jsonb) item
      ON CONFLICT (id) DO UPDATE SET
        name = EXCLUDED.name,
        value = EXCLUDED.value,
        updated_at = EXCLUDED.updated_at;
    next:
      - step: end

  - step: end
```

## Multi-Database Transfer

Transfer to multiple databases in parallel:

```yaml
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: http_to_multi_db
  path: data_transfer/multi_db

workload:
  api_url: "https://api.example.com/data"

workflow:
  - step: start
    next:
      - step: fetch_data

  - step: fetch_data
    tool:
      kind: http
      method: GET
      endpoint: "{{ workload.api_url }}"
    vars:
      data: "{{ result.data }}"
    next:
      - step: postgres_insert
      - step: analytics_insert  # Parallel execution

  - step: postgres_insert
    tool:
      kind: postgres
      auth:
      type: postgres
      credential: pg_primary
    query: |
      INSERT INTO app_data.records (data, source)
      VALUES ('{{ vars.data | tojson }}'::jsonb, 'api')
    next:
      - step: end

  - step: analytics_insert
    tool: duckdb
    auth:
      type: gcs
      credential: gcp_service_account
    query: |
      COPY (
        SELECT 
          value->>'id' as id,
          value->>'name' as name,
          current_timestamp as ingested_at
        FROM (
          SELECT unnest(from_json('{{ vars.data | tojson }}', '["json"]')) as value
        )
      ) TO 'gs://analytics-bucket/ingested/{{ execution_id }}.parquet' (FORMAT PARQUET);
    next:
      - step: end

  - step: end
```

## Error Handling

Handle API and database errors gracefully:

```yaml
- step: fetch_data
  tool: http
  method: GET
  endpoint: "{{ workload.api_url }}"
  retry:
    max_attempts: 3
    initial_delay: 1.0
    retryable_status_codes: [429, 500, 502, 503]
  next:
    - when: "{{ fetch_data.status == 'error' }}"
      then:
        - step: handle_fetch_error
    - step: process_data

- step: handle_fetch_error
  tool: python
  code: |
    def main(error):
        return {
            'status': 'failed',
            'error': error,
            'action': 'manual_review_required'
        }
  args:
    error: "{{ fetch_data.error }}"
  next:
    - step: end
```

## Performance Tips

1. **Batch inserts**: Use `jsonb_array_elements` for bulk operations
2. **Use COPY for large datasets**: DuckDB + GCS for high throughput
3. **Parallel execution**: Split data and process concurrently
4. **Connection pooling**: Enable for high-frequency inserts
5. **Appropriate page sizes**: Balance API limits and memory

## See Also

- [HTTP Tool Reference](/docs/reference/tools/http)
- [PostgreSQL Tool Reference](/docs/reference/tools/postgres)
- [Pagination Patterns](/docs/examples/pagination/pagination-patterns)
- [Data Transfer Playbooks](https://github.com/noetl/noetl/tree/master/tests/fixtures/playbooks/data_transfer)
