---
sidebar_position: 16
title: Retry Handling (Canonical v10)
description: Canonical retry model for NoETL DSL using task policy rules (retry/jump/break/fail/continue) — no eval/expr, no step-level retry blocks
---

# Retry Handling (Canonical v10)

Canonical v10 treats retry as **task outcome policy**, not a special step-level feature:

- There is **no** step-level `retry:` block in the canonical DSL.
- Retry is expressed via **task policy rules**: `task.spec.policy.rules` (`when` → `then.do: retry`).
- Tool implementations MAY still offer internal retry knobs under `task.spec`, but canonical orchestration retry is policy-driven so it remains deterministic and observable.

Related canonical docs:
- `documentation/docs/reference/dsl/noetl_step_spec.md`
- `documentation/docs/reference/dsl/spec.md`

---

## 1) Canonical retry placement

Retry belongs to **task scope**:

```yaml
- fetch_page:
    kind: http
    method: GET
    url: "{{ workload.api_url }}/items"
    spec:
      policy:
        rules:
          - when: "{{ outcome.status == 'error' and outcome.http.status in [429,500,502,503,504] }}"
            then: { do: retry, attempts: 10, backoff: exponential, delay: 2.0 }
          - when: "{{ outcome.status == 'error' }}"
            then: { do: fail }
          - else:
              then: { do: continue }
```

This keeps retry:
- **per-task** (retry fetch but not transform/store)
- **deterministic** (recorded as policy decisions + attempts)
- compatible with pagination/polling (same control actions)

---

## 2) Policy rule schema (canonical)

```yaml
spec:
  policy:
    rules:
      - when: "{{ <bool expr> }}"
        then:
          do: retry|continue|jump|break|fail
          attempts: 5
          backoff: none|linear|exponential
          delay: 1.0
          to: <task_label>           # only for jump
          set_iter: { ... }          # optional
          set_ctx: { ... }           # optional
      - else:
          then: { do: continue }
```

Defaults:
- If `spec.policy` is omitted:
  - ok → `continue`
  - error → `fail`
- If policy is present but no rule matches and there is no `else`:
  - default → `continue` (canonical v10 default)

---

## 3) Retry conditions (examples)

### 3.1 HTTP retry on 5xx and 429

```yaml
- fetch_page:
    kind: http
    method: GET
    url: "{{ workload.api_url }}/api/v1/items"
    params:
      page: "{{ iter.page }}"
      pageSize: "{{ workload.page_size }}"
    spec:
      timeout: { connect: 5, read: 15 }
      policy:
        rules:
          - when: "{{ outcome.status == 'error' and outcome.http.status in [429,500,502,503,504] }}"
            then: { do: retry, attempts: 10, backoff: exponential, delay: 2.0 }
          - when: "{{ outcome.status == 'error' and outcome.http.status in [401,403] }}"
            then: { do: fail }
          - when: "{{ outcome.status == 'error' }}"
            then: { do: retry, attempts: 3, backoff: linear, delay: 1.0 }
          - else:
              then: { do: continue }
```

### 3.2 Postgres retry on deadlock/serialization failure

```yaml
- store_page:
    kind: postgres
    auth: pg_k8s
    command: "INSERT INTO ..."
    spec:
      policy:
        rules:
          - when: "{{ outcome.status == 'error' and outcome.pg.code in ['40001','40P01'] }}"
            then: { do: retry, attempts: 5, backoff: exponential, delay: 2.0 }
          - when: "{{ outcome.status == 'error' }}"
            then: { do: fail }
          - else:
              then: { do: continue }
```

### 3.3 Python retry on transient exceptions

```yaml
- transform:
    kind: python
    args: { data: "{{ _prev }}" }
    code: |
      result = do_transform(data)
    spec:
      policy:
        rules:
          - when: "{{ outcome.status == 'error' and 'timeout' in (outcome.error.message|lower) }}"
            then: { do: retry, attempts: 3, backoff: linear, delay: 1.0 }
          - when: "{{ outcome.status == 'error' }}"
            then: { do: fail }
          - else:
              then: { do: continue }
```

---

## 4) Backoff semantics (recommended)

- `none`: constant delay
- `linear`: `delay * attempt`
- `exponential`: `delay * 2^(attempt-1)`

If you need jitter, prefer implementing it in the runtime/tool layer so the orchestration policy remains deterministic and replayable.

---

## 5) Retry architecture diagram (worker-owned task policy)

Canonical v10 retry is **worker-owned task control flow** driven by `task.spec.policy.rules`:
- the worker executes a task attempt
- the worker evaluates policy rules over the resulting `outcome`
- the worker may schedule another attempt (`then.do: retry`) with backoff/delay
- the server remains authoritative for **step admission** and **routing** (`next.arcs[]`)

### 5.1 High-level overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                    NoETL Retry Architecture                          │
│                 (Worker-side Task Policy)                            │
└─────────────────────────────────────────────────────────────────────┘

┌──────────┐           ┌──────────┐           ┌──────────┐
│  Worker  │──────────►│  Server  │──────────►│ Event Log │
└──────────┘           └──────────┘           └──────────┘
     │                      │                       │
     ▼                      ▼                       ▼
Execute task attempt   Persist events          Durable replay
Evaluate policy        Evaluate routing        Projections/UI
Retry/jump/break/fail  Schedule next steps     Analytics/ops
```

### 5.2 Detailed attempt flow (single task)

```
WORKER                                              SERVER
  │                                                   │
  │ task.attempt.started (attempt=1)                   │
  │──────────────────────────────────────────────────>│ persist
  │                                                   │
  │ run tool → outcome                                │
  │                                                   │
  │ task.attempt.failed (attempt=1, outcome=error)     │
  │──────────────────────────────────────────────────>│ persist
  │                                                   │
  │ policy.task.evaluated (matched rule → do: retry)   │
  │──────────────────────────────────────────────────>│ persist (recommended)
  │                                                   │
  │ sleep(backoff/delay)                               │
  │                                                   │
  │ task.attempt.started (attempt=2)                   │
  │──────────────────────────────────────────────────>│ persist
  │                                                   │
  │ run tool → outcome                                │
  │                                                   │
  │ task.attempt.done (attempt=2, outcome=ok)          │
  │──────────────────────────────────────────────────>│ persist
  │                                                   │
  │ task.done (final outcome)                          │
  │──────────────────────────────────────────────────>│ persist
  │                                                   │
```

Notes:
- Attempts are **not** separate step-runs; they are internal to one task execution under a worker lease.
- The server does **not** compute retry decisions; it persists events and later routes on step boundary events.

---

## 6) Observability and event sourcing

Retries are represented as **multiple attempts**:
- `task.attempt.started` / `task.attempt.done|failed`
- `policy.task.evaluated` (recommended): which rule matched + which action was taken
- terminal `task.done|failed`

The worker emits attempt events and policy decisions; the server persists them.

---

## 7) Relationship to pagination and polling

Retry is one control action in the same task-policy mechanism used for:
- **pagination streams**: `do: jump` back to `fetch_page` until `do: break`
- **polling**: `do: retry` (bounded) or `do: jump` to a poll task with explicit delay handling

See `documentation/docs/reference/dsl/pagination.md` for canonical pagination.

---

## 8) Migration guidance (from legacy `retry:` blocks)

Legacy:
```yaml
retry:
  max_attempts: 5
  retry_when: "{{ status_code >= 500 }}"
```

Canonical v10:
```yaml
spec:
  policy:
    rules:
      - when: "{{ outcome.status == 'error' and outcome.http.status >= 500 }}"
        then: { do: retry, attempts: 5, backoff: exponential, delay: 1.0 }
      - when: "{{ outcome.status == 'error' }}"
        then: { do: fail }
      - else:
          then: { do: continue }
```
