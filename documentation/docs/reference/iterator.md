---
sidebar_position: 2
title: Loop Iteration (Canonical)
description: Loop over collections using the step loop attribute (iter-scoped state, sequential/parallel modes) — Canonical v10
---

# Loop Iteration (Canonical v10)

The `loop:` **step attribute** enables iterating over collections with configurable execution modes.

**Key rules**
- `loop:` is a **step-level attribute**, **not** a tool kind.
- A canonical step is: **`spec.policy` (admission/lifecycle) + `tool` (ordered pipeline) + `next` (router with arcs)**.
- Loop state is held in **iteration scope** (`iter.*`). Each iteration has its own isolated `iter`.
- **No legacy `eval` / `expr`.** Task outcome handling uses **`task.spec.policy.rules`** with `when`.
- **No special “sink” kind.** Storage is just a tool task that writes data and returns a reference (ResultRef).

---

## Basic Usage

```yaml
- step: process_items

  loop:
    spec:
      mode: sequential
    in: "{{ workload.items }}"
    iterator: item

  tool:
    - process:
        kind: python
        args:
          item: "{{ iter.item }}"
        code: |
          result = {"processed_id": item["id"]}
        spec:
          policy:
            rules:
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then: { do: continue }

  next:
    spec: { mode: exclusive }
    arcs:
      - step: end
        when: "{{ event.name == 'loop.done' }}"
```

---

## Configuration

| Field | Type | Required | Description |
|------|------|----------|-------------|
| `in` | string/array | Yes | Jinja2 expression (string) or literal array to iterate over |
| `iterator` | string | Yes | Name bound as `iter.<iterator>` for the current element |
| `spec.mode` | string | No | `sequential` (default) or `parallel` |
| `spec.max_in_flight` | int | No | Parallel concurrency limit (optional) |
| `spec.policy.exec` | string | No | `distributed` \| `local` (placement intent; server may ignore) |

---

## Execution Modes

### Sequential mode

Items are processed one at a time, in order.

```yaml
- step: fetch_weather

  loop:
    spec: { mode: sequential }
    in: "{{ workload.cities }}"
    iterator: city

  tool:
    - fetch:
        kind: http
        method: GET
        url: "https://api.weather.com/city/{{ iter.city.name }}"
        params:
          lat: "{{ iter.city.lat }}"
          lon: "{{ iter.city.lon }}"
        spec:
          timeout: { connect: 5, read: 15 }
          policy:
            rules:
              - when: "{{ outcome.status == 'error' and outcome.http.status in [429,500,502,503,504] }}"
                then: { do: retry, attempts: 10, backoff: exponential, delay: 2.0 }
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then: { do: continue }

  next:
    spec: { mode: exclusive }
    arcs:
      - step: end
        when: "{{ event.name == 'loop.done' }}"
```

### Parallel mode

Items are processed concurrently (bounded by `spec.max_in_flight` and/or worker capacity).  
Each iteration has its own `iter` scope, so **`set_iter` is always safe**.

```yaml
- step: fetch_data

  loop:
    spec:
      mode: parallel
      max_in_flight: 20
      policy:
        exec: distributed   # optional intent
    in: "{{ workload.urls }}"
    iterator: url

  tool:
    - fetch:
        kind: http
        method: GET
        url: "{{ iter.url }}"
        spec:
          policy:
            rules:
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then: { do: continue }

  next:
    spec: { mode: exclusive }
    arcs:
      - step: end
        when: "{{ event.name == 'loop.done' }}"
```

---

## Accessing iterator variables

Inside a loop iteration, the current element is always available at:

- `iter.<iterator>`

Examples:
- `iterator: city` → `iter.city`
- `iterator: endpoint` → `iter.endpoint`

---

## Loop + Storage (pattern)

There is **no special `sink` tool kind**. A “sink” is simply a tool task that writes to storage and returns a **reference** (ResultRef).

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
        spec:
          policy:
            rules:
              - when: "{{ outcome.status == 'error' and outcome.pg.code in ['40001','40P01'] }}"
                then: { do: retry, attempts: 5, backoff: exponential, delay: 2.0 }
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then: { do: continue }

  next:
    spec: { mode: exclusive }
    arcs:
      - step: end
        when: "{{ event.name == 'loop.done' }}"
```

---

## Nested loops (canonical)

Canonical v10 supports nested loops via a **parent chain**:

- `iter` is the current iteration
- `iter.parent` is the outer iteration
- `iter.parent.parent` for deeper nesting

This enables patterns like:
- cities processed in parallel
- hotels per city processed in parallel
- rooms per hotel processed sequentially with streaming pagination inside the hotel iteration

> Implementation note: the server schedules iterations; the worker guarantees each iteration’s task pipeline is a single logical thread (one worker lease).

---

## HTTP pagination inside a loop (canonical streaming pattern)

Pagination is expressed using **task control flow** (`jump` + `break`) and **iteration state** (`set_iter`).

```yaml
- step: fetch_all_pages

  loop:
    spec: { mode: parallel, max_in_flight: 10 }
    in: "{{ workload.endpoints }}"
    iterator: endpoint

  tool:
    - init:
        kind: noop
        spec:
          policy:
            rules:
              - else:
                  then:
                    do: continue
                    set_iter: { page: 1, has_more: true }

    - fetch_page:
        kind: http
        method: GET
        url: "{{ workload.api_url }}{{ iter.endpoint.path }}"
        params:
          page: "{{ iter.page }}"
          pageSize: "{{ iter.endpoint.page_size }}"
        spec:
          timeout: { connect: 5, read: 15 }
          policy:
            rules:
              - when: "{{ outcome.status == 'error' and outcome.http.status in [429,500,502,503,504] }}"
                then: { do: retry, attempts: 10, backoff: exponential, delay: 2.0 }
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then:
                    do: continue
                    set_iter:
                      has_more: "{{ outcome.result.data.paging.hasMore | default(false) }}"
                      page: "{{ outcome.result.data.paging.page | default(iter.page) }}"
                      items: "{{ outcome.result.data.data | default([]) }}"

    - store_page:
        kind: postgres
        auth: pg_k8s
        command: "INSERT INTO pages (...) VALUES (...)"
        spec:
          policy:
            rules:
              - when: "{{ outcome.status == 'error' and outcome.pg.code in ['40001','40P01'] }}"
                then: { do: retry, attempts: 5, backoff: exponential, delay: 2.0 }
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then: { do: continue }

    - paginate:
        kind: noop
        spec:
          policy:
            rules:
              - when: "{{ iter.has_more == true }}"
                then:
                  do: jump
                  to: fetch_page
                  set_iter:
                    page: "{{ (iter.page | int) + 1 }}"
              - else:
                  then: { do: break }

  next:
    spec: { mode: exclusive }
    arcs:
      - step: end
        when: "{{ event.name == 'loop.done' }}"
```

---

## Working Examples (Repo)

- iterator + save: `tests/fixtures/playbooks/iterator_save_test`
- loop + pagination: `tests/fixtures/playbooks/pagination/loop_with_pagination`
- data transfer: `tests/fixtures/playbooks/data_transfer/http_iterator_save_postgres`
