---
sidebar_position: 2
title: Loop Iteration
description: Loop over collections using the loop step attribute
---

# Loop Iteration

The `loop:` step attribute enables iterating over collections with configurable execution modes. State is managed via NATS KV snapshots.

**Important**: `loop:` is a step-level attribute, NOT a tool kind. It modifies how a step executes.

## Basic Usage

```yaml
- step: process_items
  tool:
    kind: python
    libs: {}
    args:
      item: "{{ current_item }}"
    code: |
      result = {"processed_id": item["id"]}
  loop:
    in: "{{ workload.items }}"
    iterator: current_item
    mode: sequential
  next:
    - step: end
```

## Configuration

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `in` | string/array | Yes | Jinja2 expression or array to iterate over |
| `iterator` | string | Yes | Variable name for current item |
| `mode` | string | No | `sequential` (default) or `parallel` |

## Execution Modes

### Sequential Mode

Items processed one at a time, in order:

```yaml
- step: fetch_weather
  tool:
    kind: http
    method: GET
    url: "https://api.weather.com/city/{{ city.name }}"
    params:
      lat: "{{ city.lat }}"
      lon: "{{ city.lon }}"
  loop:
    in: "{{ workload.cities }}"
    iterator: city
    mode: sequential
  next:
    - step: end
```

### Parallel Mode

Items processed concurrently (limited by worker pool):

```yaml
- step: fetch_data
  tool:
    kind: http
    method: GET
    url: "{{ url }}"
  loop:
    in: "{{ workload.urls }}"
    iterator: url
    mode: parallel
  next:
    - step: end
```

## Accessing Iterator Variables

Within the loop body, access the current element directly by the iterator name:

```yaml
- step: fetch_weather
  tool:
    kind: http
    method: GET
    url: "https://api.weather.com/city/{{ city.name }}"
    params:
      lat: "{{ city.lat }}"
      lon: "{{ city.lon }}"
  loop:
    in: "{{ workload.cities }}"
    iterator: city
    mode: sequential
```

## Loop with Sink

Save results from each iteration:

```yaml
- step: process_and_save
  tool:
    kind: python
    libs: {}
    args:
      record: "{{ current_record }}"
    code: |
      result = {"processed_id": record["id"], "status": "complete"}
  loop:
    in: "{{ workload.records }}"
    iterator: current_record
    mode: parallel
  case:
    - when: "{{ event.name == 'step.exit' and response is defined }}"
      then:
        sink:
          tool:
            kind: postgres
            auth: "{{ workload.pg_auth }}"
            table: processed_records
```

## Nested Loops

For multi-dimensional processing, use separate steps with loops:

```yaml
- step: process_categories
  tool:
    kind: python
    libs: {}
    args:
      category: "{{ cat }}"
    code: |
      result = {"category_id": category["id"], "items": category["items"]}
  loop:
    in: "{{ workload.categories }}"
    iterator: cat
    mode: sequential
  vars:
    current_items: "{{ result.items }}"
  next:
    - step: process_items

- step: process_items
  tool:
    kind: python
    libs: {}
    args:
      item: "{{ current_item }}"
    code: |
      result = {"item_id": item["id"], "processed": True}
  loop:
    in: "{{ vars.current_items }}"
    iterator: current_item
    mode: sequential
  next:
    - step: end
```

## HTTP Pagination with Loop

Combine HTTP pagination with iteration for complex data fetching:

```yaml
- step: fetch_all_pages
  tool:
    kind: http
    method: GET
    url: "{{ workload.api_url }}"
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
  vars:
    all_items: "{{ result.data }}"
  next:
    - step: process_items

- step: process_items
  tool:
    kind: python
    libs: {}
    args:
      item: "{{ current_item }}"
    code: |
      result = {"item_id": item["id"], "transformed": True}
  loop:
    in: "{{ vars.all_items }}"
    iterator: current_item
    mode: parallel
  next:
    - step: end
```

## Working Examples

See complete loop playbooks:
- [iterator_save_test/](https://github.com/noetl/noetl/tree/master/tests/fixtures/playbooks/iterator_save_test)
- [loop_with_pagination/](https://github.com/noetl/noetl/tree/master/tests/fixtures/playbooks/pagination/loop_with_pagination)
- [http_iterator_save_postgres/](https://github.com/noetl/noetl/tree/master/tests/fixtures/playbooks/data_transfer/http_iterator_save_postgres)
