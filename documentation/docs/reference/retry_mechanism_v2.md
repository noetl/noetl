---
sidebar_position: 16
title: Retry Handling (Canonical)
description: Canonical retry model for NoETL DSL v2 using tool-level eval (retry/jump/break/fail/continue)
---

# Retry Handling (Canonical)

NoETL v2 (canonical) treats retry as **pipeline control flow**, not a special step-level feature.

- There is **no step-level `retry:` block** in the canonical DSL.
- Retry is expressed using **tool-level `eval` rules** (ordered `expr → do` directives).
- Tool implementations MAY support internal retries under `tool.spec`, but canonical orchestration-level behavior is driven by `eval` so it is deterministic, observable, and uniform across tool kinds.

This document aligns with:
- `dsl_specification_v2.md`
- `formal_specification_v2.md`
- `noetl_canonical_step_spec_v2.md` fileciteturn9file0

---

## 1) Why retry moved to `eval`

Older NoETL docs used a generic `retry:` policy wrapper around all tool executions. The canonical model refactors this into tool-level `eval` because:

- **One mechanism** handles retry, pagination, polling, compensation, and early-exit.
- Retry decisions are **event-sourced** as pipeline transitions (`task.processed` + directive).
- Retry can be **task-specific** (retry fetch but not transform; retry store on deadlock).
- Works naturally with the Petri-net model: step pipelines are deterministic programs.

---

## 2) Core concepts

### 2.1 `outcome`
Every tool completion produces one `outcome` envelope:

- `outcome.status`: `success | error`
- `outcome.result`: output (on success)
- `outcome.error`: error object (on error)
- `outcome.meta`: attempt, duration, trace ids, timestamps

Kind helpers MAY exist:
- HTTP: `outcome.http.status`, `outcome.http.headers`
- Postgres: `outcome.pg.code`
- Python: `outcome.py.exception`

### 2.2 `eval`
`eval` is an ordered list of rules that maps an `outcome` to a directive:

- `continue` → proceed to next task
- `retry` → rerun this task with backoff/delay
- `jump` → set pipeline program counter to another labeled task
- `break` → end step successfully
- `fail` → end step with failure

**First match wins** (YAML order).

---

## 3) Canonical `eval` schema for retry

```yaml
eval:
  - expr: "{{ <bool expr> }}"
    do: retry
    attempts: 5
    backoff: exponential | linear | fixed
    delay: 1.0                # seconds or expression
  - else:
      do: continue
```

### Defaults if `eval` omitted
- success → `continue`
- error → `fail`

This is the Rust-like safe default.

---

## 4) Retry conditions (examples)

### 4.1 HTTP retry on 5xx and 429

```yaml
- fetch_page:
    kind: http
    spec:
      timeout: { connect: 5, read: 15 }
    method: GET
    url: "{{ workload.api_url }}/api/v1/assessments"
    params: { page: "{{ iter.page }}", pageSize: "{{ iter.endpoint.page_size }}" }
    eval:
      - expr: "{{ outcome.status == 'error' and outcome.http.status in [429, 500, 502, 503, 504] }}"
        do: retry
        attempts: 10
        backoff: exponential
        delay: "{{ outcome.http.headers['retry-after'] | default(2) }}"
      - expr: "{{ outcome.status == 'error' }}"
        do: fail
      - else:
          do: continue
```

### 4.2 Postgres retry on deadlock/serialization failure

```yaml
- store_page:
    kind: postgres
    auth: pg_k8s
    command: "INSERT INTO ..."
    eval:
      - expr: "{{ outcome.status == 'error' and outcome.pg.code in ['40001','40P01'] }}"
        do: retry
        attempts: 5
        backoff: exponential
        delay: 2.0
      - expr: "{{ outcome.status == 'error' }}"
        do: fail
      - else:
          do: continue
```

### 4.3 Python retry on transient exceptions

```yaml
- transform:
    kind: python
    args: { data: "{{ _prev }}" }
    code: " ... "
    eval:
      - expr: "{{ outcome.status == 'error' and 'timeout' in (outcome.error.message|lower) }}"
        do: retry
        attempts: 3
        backoff: fixed
        delay: 1.0
      - expr: "{{ outcome.status == 'error' }}"
        do: fail
      - else:
          do: continue
```

---

## 5) Backoff semantics (canonical)

### 5.1 Backoff types
- `fixed`: `delay` is constant per attempt
- `linear`: `delay * attempt`
- `exponential`: `delay * 2^(attempt-1)` (recommended)

### 5.2 Jitter
If you need jitter, model it as an expression in `delay` (renderer-provided helper) or as a `tool.spec` option if implemented.

Example (if you expose `rand()` helper to templates):

```yaml
delay: "{{ 2.0 * (0.5 + rand()) }}"
```

> If jitter helpers are not available, keep jitter in the tool implementation (`tool.spec.jitter: true`) and leave orchestration retry deterministic.

---

## 6) Observability and event sourcing

Each retry attempt MUST be observable as events:

- `task.started` (attempt N)
- `task.processed` (outcome + attempt N)
- optional: `task.retry_scheduled` (delay/backoff decision)

The worker is responsible for emitting these events; the server persists them.

---

## 7) Relationship to pagination and polling

Retry is a subset of pipeline control flow. Canonical patterns:

- **Retry** (same task again): `do: retry`
- **Pagination** (loop inside pipeline): `do: jump` to `fetch_page` and increment `iter.page`
- **Polling** (repeat until condition): `do: jump` to `poll` with `delay` via retry-style sleep (implementation-defined)

---

## 8) Migration guidance (from old `retry:` blocks)

If you previously had:

```yaml
retry:
  max_attempts: 5
  retry_when: "{{ status_code >= 500 }}"
```

Map it to:

```yaml
eval:
  - expr: "{{ outcome.status == 'error' and outcome.http.status >= 500 }}"
    do: retry
    attempts: 5
    backoff: exponential
    delay: 1.0
  - expr: "{{ outcome.status == 'error' }}"
    do: fail
  - else:
      do: continue
```

---

## 9) Best practices

- Keep retry conditions **specific** (retryable vs non-retryable).
- Prefer retry on **idempotent** operations (GET, safe inserts with dedupe keys, etc.).
- Use bounded attempts and reasonable delays to avoid runaway execution.
- For parallel loops, avoid shared mutable writes; store progress in `iter` or external references.

