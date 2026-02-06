---
sidebar_position: 5
title: Pagination (Canonical)
description: Canonical pagination patterns for NoETL DSL v2 — streaming pagination with task policy (retry/jump/break) and outer-loop fan-out
---

# Pagination Handling — Canonical v10

This document merges:
- the **streaming pagination example** (no fall-through) fileciteturn31file0
- the **HTTP pagination quick reference** fileciteturn31file1

…and updates everything to the **Canonical v10** DSL:

- **No** `eval:` blocks
- **No** `expr:` keyword
- **No** `step.when`
- **No** `step.spec.next_mode` (routing mode belongs to `next.spec.mode`)
- Pagination is implemented as an **ordered stream** inside one iteration using **task policy** (`retry|jump|break|fail|continue`)
- “Sink” is not a tool kind — storage is **just a tool task** that returns a reference

---

## 1) Mental model

You usually want **two layers**:

1) **Outer fan-out** over items (endpoints/cities/hotels) via `step.loop`
   - can be **parallel** and even **distributed**
2) **Inner stream** per item (pages/rooms) processed **sequentially** on a **single worker lease**
   - implemented by a pipeline with `jump` back to `fetch_page` until `break`

This gives you:
- parallelism where safe (across independent items)
- determinism where required (within one item’s pagination stream)

---

## 2) Text diagram (two layers)

### 2.1 Outer fan-out (loop parallel / distributed)

```
SERVER (control plane)
  |
  | token(step=fetch_all_endpoints, args={...})
  v
SCHEDULE step.run (and loop plan)  ──────────────────────────────┐
  |                                                               |
  v                                                               |
WORKERS (data plane) execute iterations in parallel                |
  |                                                               |
  |-- iteration(endpoint=A)  [single lease, sequential pages]      |
  |-- iteration(endpoint=B)  [single lease, sequential pages]      |
  |-- iteration(endpoint=C)  ...                                   |
  |                                                               |
  +--> worker emits loop.done  ────────────────────────────────────┘
  |
  v
SERVER evaluates next.arcs on event=loop.done
  |
  +--> validate_results (next token(s))
```

### 2.2 One iteration = sequential pagination stream (worker-local)

```
(init_iter)
   |
(fetch_page) --policy retry--> (fetch_page)
   |
(route_by_status) --jump--> store_200
      |             |
      |             +--jump--> paginate
      |
      +--jump--> store_404
                    |
                    +--jump--> paginate

(paginate)
   |
   +--jump--> fetch_page   [if iter.has_more]
   |
  break                   [if not iter.has_more]
```

Key property: **no fall-through**. Router and store tasks use `jump` so you never “accidentally” execute both store branches.

---

## 3) Canonical variables & wrappers

### 3.1 Canonical tool outcome

Every tool task produces a final `outcome` object:

- `outcome.status`: `ok|error`
- `outcome.result`: success output (small payload or reference)
- `outcome.error`: error object (`kind`, `retryable`, message, details)
- kind helpers (HTTP, Postgres, etc.): `outcome.http.status`, `outcome.pg.code`, ...

Task policy rules evaluate **over `outcome`**.

### 3.2 HTTP wrapper note (practical)
Many HTTP executors wrap API payloads (example from older docs): the API body sits under `.data`.

In canonical form, your policy reads are generally:

- `outcome.http.status`
- `outcome.result.data` (if your HTTP kind wraps the body under `result.data`)
- or `outcome.result` (if your HTTP kind returns the body directly)

**Canonical recommendation:** standardize HTTP kind to return:
- `outcome.result.data` = API body (object)
- `outcome.http.status` = HTTP status code

Then templates can be stable.

---

## 4) Canonical pattern: parallel outer loop + sequential stream per iteration

This example:
- loops over endpoints in parallel
- per endpoint, fetches pages sequentially
- retries transient HTTP and DB errors
- routes storage by HTTP status (200 vs 404)
- uses `iter` for paging state
- ends iteration via `break`
- transitions to next step via `next.arcs` on `loop.done` / `step.failed`

```yaml
- step: fetch_all_endpoints

  loop:
    spec:
      mode: parallel
      max_in_flight: 10
      policy:
        exec: distributed      # optional placement intent
    in: "{{ workload.endpoints }}"
    iterator: endpoint

  tool:
    - init_iter:
        kind: noop
        spec:
          policy:
            rules:
              - else:
                  then:
                    do: continue
                    set_iter:
                      page: 1
                      has_more: true

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
              # transient retry (rate limit / gateway / service unavailable)
              - when: "{{ outcome.status == 'error' and outcome.http.status in [429,500,502,503,504] }}"
                then: { do: retry, attempts: 10, backoff: exponential, delay: 2.0 }

              # permanent fail (auth)
              - when: "{{ outcome.status == 'error' and outcome.http.status in [401,403] }}"
                then: { do: fail }

              # on success, capture status + paging fields for routing and pagination
              - else:
                  then:
                    do: continue
                    set_iter:
                      http_status: "{{ outcome.http.status | default(200) }}"
                      has_more: "{{ outcome.result.data.paging.hasMore | default(false) }}"
                      page: "{{ outcome.result.data.paging.page | default(iter.page) }}"
                      items: "{{ outcome.result.data.data | default([]) }}"

    - route_by_status:
        kind: noop
        spec:
          policy:
            rules:
              - when: "{{ iter.http_status == 404 }}"
                then: { do: jump, to: store_404 }
              - else:
                  then: { do: jump, to: store_200 }

    - store_200:
        kind: postgres
        auth: pg_k8s
        command: |
          INSERT INTO results_ok (execution_id, endpoint, page, items, items_count)
          VALUES (...)
        spec:
          policy:
            rules:
              - when: "{{ outcome.status == 'error' and outcome.pg.code in ['40001','40P01'] }}"
                then: { do: retry, attempts: 5, backoff: exponential, delay: 2.0 }
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then: { do: jump, to: paginate }

    - store_404:
        kind: postgres
        auth: pg_k8s
        command: |
          INSERT INTO results_not_found (execution_id, endpoint, page)
          VALUES (...)
        spec:
          policy:
            rules:
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then: { do: jump, to: paginate }

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
      - step: validate_results
        when: "{{ event.name == 'loop.done' }}"
      - step: cleanup
        when: "{{ event.name == 'step.failed' }}"
```

### Why this is canonical
- **No fall-through:** router `jump`s to exactly one store task; store tasks `jump` to paginate.
- **Sequential pages per iteration:** `paginate` loops via `jump` within one iteration lease.
- **Parallelism only across iterations:** controlled by `loop.spec`.

---

## 5) Routing storage by status code (more cases)

You can extend `route_by_status` for multiple stores:

```yaml
- route_by_status:
    kind: noop
    spec:
      policy:
        rules:
          - when: "{{ iter.http_status == 404 }}"
            then: { do: jump, to: store_404 }
          - when: "{{ iter.http_status == 409 }}"
            then: { do: jump, to: store_conflict }
          - when: "{{ iter.http_status in [500,502,503,504] }}"
            then: { do: jump, to: store_server_error }
          - else:
              then: { do: jump, to: store_200 }
```

This keeps “if/else” logic **inside policy**, using **only `when`**.

---

## 6) Retry in pagination streams

### 6.1 Retry the fetch itself
Retry transient errors in `fetch_page` policy (as shown above).

### 6.2 Retry storage
Retry retryable DB errors in `store_*` policy.

### 6.3 Avoid duplications
If your store is not idempotent, prefer:
- upserts
- unique keys (`execution_id`, `endpoint`, `page`)
- transaction retries with safe replays

---

## 7) While / Until (canonical guidance)

Canonical v10 uses **policy + jump/break** to implement looping.  
However, you can model a “while/until” concept by convention inside the `paginate` task:

- `while`: continue jumping while condition is true
- `until`: jump until condition becomes true

Example (until):

```yaml
- paginate:
    kind: noop
    spec:
      policy:
        rules:
          - when: "{{ iter.has_more != true }}"
            then: { do: break }
          - else:
              then:
                do: jump
                to: fetch_page
                set_iter:
                  page: "{{ (iter.page | int) + 1 }}"
```

(If you later add first-class `while/until`, compile it down to this policy form.)

---

## 8) Quick reference: expressions you can use

### 8.1 Variables available in policy rules
Inside `task.spec.policy.rules[].when` you can reference:
- `outcome.*` (status/result/error/meta + kind helpers)
- `iter.*` (if loop present)
- `ctx.*`
- `args.*`
- `_prev`, `_task`, `_attempt`
- `workload.*`

### 8.2 Common pagination guards
- page-number: `iter.has_more == true`
- cursor: `iter.next_cursor is not none`
- offset: `iter.offset < iter.total`

### 8.3 Common transient error checks
- HTTP transient: `outcome.http.status in [429,500,502,503,504]`
- DB deadlock/serialization: `outcome.pg.code in ['40001','40P01']`

---

## 9) Legacy note (non-canonical)

Older NoETL docs included a `pagination:` block with `continue_while` and `next_page` and `merge_path`. fileciteturn31file1

Canonical v10 replaces that with:
- iteration state (`iter`) + ordered tasks
- task policy + `jump/break`
- explicit storage tasks returning references

If you keep the legacy paginator for backward compatibility, treat it as a **compiler** into the canonical streaming form.

---
