---
sidebar_position: 2
title: Loop Iteration (Canonical)
description: Loop over collections using the step loop attribute (iter-scoped state, sequential/parallel modes)
---

# Loop Iteration (Canonical)

The `loop:` **step attribute** enables iterating over collections with configurable execution modes.

**Important**
- `loop:` is a **step-level attribute**, not a tool kind.
- In canonical v2, step execution is: **`when` + `tool` (ordered pipeline) + `next`**.
- Loop state is held in **iteration scope** (`iter.*`) and is emitted via events; implementations MAY snapshot to an external store, but canonical semantics do not require “NATS KV snapshots”.

---

## Basic Usage

```yaml
- step: process_items
  tool:
    - process:
        kind: python
        args:
          item: "{{ iter.current_item }}"
        code: |
          result = {"processed_id": item["id"]}
  loop:
    spec:
      mode: sequential
    in: "{{ workload.items }}"
    iterator: current_item
  next:
    - step: end
```

---

## Configuration

| Field | Type | Required | Description |
|------|------|----------|-------------|
| `in` | string/array | Yes | Jinja2 expression or array to iterate over |
| `iterator` | string | Yes | Name bound into `iter.<iterator>` for the current element |
| `spec.mode` | string | No | `sequential` (default) or `parallel` |
| `spec.max_in_flight` | int | No | Parallel concurrency limit (optional) |

---

## Execution Modes

### Sequential Mode

Items processed one at a time, in order:

```yaml
- step: fetch_weather
  tool:
    - fetch:
        kind: http
        method: GET
        url: "https://api.weather.com/city/{{ iter.city.name }}"
        params:
          lat: "{{ iter.city.lat }}"
          lon: "{{ iter.city.lon }}"
  loop:
    spec: { mode: sequential }
    in: "{{ workload.cities }}"
    iterator: city
  next:
    - step: end
```

### Parallel Mode

Items processed concurrently (bounded by `spec.max_in_flight` or worker capacity):

```yaml
- step: fetch_data
  tool:
    - fetch:
        kind: http
        method: GET
        url: "{{ iter.url }}"
  loop:
    spec:
      mode: parallel
      max_in_flight: 20
    in: "{{ workload.urls }}"
    iterator: url
  next:
    - step: end
```

---

## Accessing Iterator Variables (Canonical)

Inside a loop iteration, the current element is always available at:

- `iter.<iterator>`

Examples:
- `iterator: city` → `iter.city`
- `iterator: endpoint` → `iter.endpoint`

```yaml
- step: fetch_weather
  tool:
    - fetch:
        kind: http
        url: "https://api.weather.com/city/{{ iter.city.name }}"
        params:
          lat: "{{ iter.city.lat }}"
          lon: "{{ iter.city.lon }}"
  loop:
    spec: { mode: sequential }
    in: "{{ workload.cities }}"
    iterator: city
```

---

## Loop + “Sink” (pattern)

There is **no special `sink` tool kind**.
A “sink” is simply a tool task that writes to storage and returns a reference (ResultRef).

```yaml
- step: process_and_save
  loop:
    spec: { mode: parallel, max_in_flight: 10 }
    in: "{{ workload.records }}"
    iterator: record

  tool:
    - transform:
        kind: python
        args:
          record: "{{ iter.record }}"
        code: |
          result = {"processed_id": record["id"], "status": "complete"}

    - store:
        kind: postgres
        auth: "{{ workload.pg_auth }}"
        command: "INSERT INTO processed_records (...) VALUES (...)"

  next:
    - step: end
```

---

## Nested Loops (Recommended Pattern)

Rather than nesting loop blocks inside a single step, use **separate steps** and pass the collection via `next[].args` or `ctx` references.

```yaml
- step: process_categories
  loop:
    spec: { mode: sequential }
    in: "{{ workload.categories }}"
    iterator: cat

  tool:
    - extract_items:
        kind: python
        args:
          category: "{{ iter.cat }}"
        code: |
          result = {"items": category["items"], "category_id": category["id"]}
        eval:
          - else:
              do: continue
              set_ctx:
                current_items: "{{ result.items }}"

  next:
    - step: process_items

- step: process_items
  loop:
    spec: { mode: sequential }
    in: "{{ ctx.current_items }}"
    iterator: item

  tool:
    - process:
        kind: python
        args:
          item: "{{ iter.item }}"
        code: |
          result = {"item_id": item["id"], "processed": True}

  next:
    - step: end
```

> In parallel loops, prefer `iter` for state updates. Shared writes to `vars` must be explicit (`set_shared`) or deterministically mapped per implementation.

---

## HTTP Pagination (Canonical v2)

Pagination is expressed with **pipeline control flow** (`eval: jump`) and `iter` state, not with `loop.pagination:` blocks.

```yaml
- step: fetch_all_pages
  tool:
    - init:
        kind: noop
        eval:
          - else:
              do: continue
              set_iter: { page: 1 }

    - fetch_page:
        kind: http
        method: GET
        url: "{{ workload.api_url }}"
        params:
          page: "{{ iter.page }}"
        eval:
          - expr: "{{ outcome.status == 'error' and outcome.http.status in [429,500,502,503,504] }}"
            do: retry
            attempts: 10
            backoff: exponential
            delay: 2
          - expr: "{{ outcome.status == 'error' }}"
            do: fail
          - else:
              do: continue
              set_iter:
                has_more: "{{ outcome.result.data.hasMore | default(false) }}"

    - store_page:
        kind: postgres
        auth: pg_k8s
        command: "INSERT INTO pages (...) VALUES (...)"
        eval:
          - expr: "{{ outcome.status == 'error' and outcome.pg.code in ['40001','40P01'] }}"
            do: retry
            attempts: 5
            backoff: exponential
            delay: 2
          - expr: "{{ outcome.status == 'error' }}"
            do: fail
          - else:
              do: continue

    - paginate:
        kind: noop
        eval:
          - expr: "{{ iter.has_more == true }}"
            do: jump
            to: fetch_page
            set_iter:
              page: "{{ (iter.page | int) + 1 }}"
          - else:
              do: break

  next:
    - step: end
```

---

## Working Examples (Repo)

- iterator + save: `tests/fixtures/playbooks/iterator_save_test`
- loop + pagination: `tests/fixtures/playbooks/pagination/loop_with_pagination`
- data transfer: `tests/fixtures/playbooks/data_transfer/http_iterator_save_postgres`
