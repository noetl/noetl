---
sidebar_position: 2
title: Iterator
description: Loop over collections with the iterator step type
---

# Iterator

The iterator enables looping over collections with configurable execution modes.

## Basic Usage

```yaml
- step: process_items
  tool: iterator
  collection: "{{ workload.items }}"
  element: item
  mode: sequential
  next:
    - step: process_single_item
```

## Configuration

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `collection` | string/array | Yes | Jinja2 expression or array to iterate over |
| `element` | string | Yes | Variable name for current item |
| `mode` | string | No | `sequential` (default) or `async` |

## Execution Modes

### Sequential Mode

Items processed one at a time, in order:

```yaml
- step: sequential_loop
  tool: iterator
  collection: "{{ workload.cities }}"
  element: city
  mode: sequential
  next:
    - step: fetch_weather
```

### Async Mode

Items processed in parallel (limited by worker pool):

```yaml
- step: parallel_loop
  tool: iterator
  collection: "{{ workload.urls }}"
  element: url
  mode: async
  next:
    - step: fetch_data
```

## Accessing Iterator Variables

Within the loop body, access the current element:

```yaml
- step: fetch_weather
  tool: http
  url: "https://api.weather.com/city/{{ iterator.city.name }}"
  params:
    lat: "{{ iterator.city.lat }}"
    lon: "{{ iterator.city.lon }}"
```

## Iterator with Save

Save results from each iteration:

```yaml
- step: process_and_save
  tool: iterator
  collection: "{{ workload.records }}"
  element: record
  mode: async
  next:
    - step: transform_record

- step: transform_record
  tool: python
  code: |
    def main(input_data):
        return {"processed": input_data["record"]["id"]}
  args:
    record: "{{ iterator.record }}"
  save:
    tool: postgres
    auth: "{{ workload.pg_auth }}"
    table: processed_records
    mode: insert
```

## Nested Iteration

Iterators can be nested for multi-dimensional processing:

```yaml
- step: outer_loop
  tool: iterator
  collection: "{{ workload.categories }}"
  element: category
  next:
    - step: inner_loop

- step: inner_loop
  tool: iterator
  collection: "{{ iterator.category.items }}"
  element: item
  next:
    - step: process_item
```

## Pagination with Iterator

Combine HTTP pagination with iteration for complex data fetching:

```yaml
- step: fetch_all_pages
  tool: http
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
  next:
    - step: process_items

- step: process_items
  tool: iterator
  collection: "{{ fetch_all_pages.data }}"
  element: item
  mode: async
  next:
    - step: transform_item
```

## Working Examples

See complete iterator playbooks:
- [iterator_save_test/](https://github.com/noetl/noetl/tree/master/tests/fixtures/playbooks/iterator_save_test)
- [loop_with_pagination/](https://github.com/noetl/noetl/tree/master/tests/fixtures/playbooks/pagination/loop_with_pagination)
- [http_iterator_save_postgres/](https://github.com/noetl/noetl/tree/master/tests/fixtures/playbooks/data_transfer/http_iterator_save_postgres)
