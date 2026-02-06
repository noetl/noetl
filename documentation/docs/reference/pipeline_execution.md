---
sidebar_position: 12
title: Pipeline Execution (Canonical v10)
description: Atomic, ordered task pipelines inside a step using task outcome policy rules (retry/jump/break/fail/continue)
---

# Pipeline Execution (Canonical v10)

Pipeline execution in NoETL is an **atomic, ordered sequence of tasks** executed **within a single step-run** on a **single worker lease**.

Canonical v10 properties:
- **Data threading** via `_prev` (previous task result)
- **Per-task flow control** via `task.spec.policy.rules` (`when` → `then.do`)
- **Deterministic replay** via the event log (no hidden control flow)
- **No legacy `eval`/`expr`**, no step-level `case`, and **no `step.when`**
- **Server** owns step admission + routing; **worker** owns pipeline execution + task policy control

---

## Overview (control plane vs data plane)

High-level execution sequence:

```
token arrives at step
  ↓
SERVER: admission gate (step.spec.policy.admit.rules)
  ↓
SERVER: step.scheduled → dispatch step-run to worker
  ↓
WORKER: executes step.tool tasks in order
  task1 → policy → task2 → policy → ... → terminal
  ↓
WORKER: emits step.done / step.failed / loop.done
  ↓
SERVER: evaluates step.next.arcs[] on boundary event → schedules next step(s)
```

**Hard rule:** worker task policy MUST NOT start steps. Only server routing (`step.next.arcs[]`) starts steps.

---

## Canonical step shape (pipeline + router)

```yaml
- step: fetch_transform_store

  spec:
    policy:
      admit:
        rules:
          - else:
              then: { allow: true }

  tool:
    - fetch:
        kind: http
        method: GET
        url: "{{ workload.api_url }}/data"
        spec:
          policy:
            rules:
              - when: "{{ outcome.status == 'error' and outcome.http.status in [429,500,502,503,504] }}"
                then: { do: retry, attempts: 5, backoff: exponential, delay: 2 }
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then: { do: continue }

    - transform:
        kind: python
        args: { data: "{{ _prev }}" }
        code: |
          result = transform(data)

    - store:
        kind: postgres
        auth: pg_k8s
        command: "INSERT INTO ..."
        spec:
          policy:
            rules:
              - when: "{{ outcome.status == 'error' and outcome.pg.code in ['40001','40P01'] }}"
                then: { do: retry, attempts: 5, backoff: exponential, delay: 2 }
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then:
                    do: break
                    set_ctx: { store_ok: true }

  next:
    spec: { mode: exclusive }
    arcs:
      - step: continue
        when: "{{ event.name == 'step.done' and ctx.store_ok == true }}"
      - step: failed
        when: "{{ event.name == 'step.done' and ctx.store_ok != true }}"
      - step: failed
        when: "{{ event.name == 'step.failed' }}"
```

Notes:
- `step.tool` is always an **ordered pipeline** (no `pipe:` block).
- Task labels (`fetch`, `transform`, `store`) are stable identifiers for `jump` targets and event correlation.
- `step.next` is a **router object**: `next.spec` + `next.arcs[]`.

---

## Runtime variables (templates + policies)

Available during pipeline execution:

| Name | Scope | Meaning |
|---|---|---|
| `workload` | execution | immutable merged inputs |
| `keychain` | execution | resolved credentials (read-only) |
| `ctx` | execution | mutable execution context (event-sourced patches) |
| `iter` | iteration | mutable iteration context (loop only; isolated per iteration) |
| `args` | step-run | token payload / arc inscription |
| `_task` | pipeline | current task label |
| `_prev` | pipeline | previous task result (`outcome.result` of previous task) |
| `_attempt` | pipeline | attempt number for current task (1-based) |
| `outcome` | pipeline | current task outcome envelope (policy evaluation only) |
| `event` | routing | boundary event (server-side `next.arcs[].when` evaluation) |

> There is no canonical `vars` scope in v10. Use `iter` (within loops) and `ctx` (cross-step) via policy patches.

---

## Outcome envelope (`outcome`)

Each tool invocation produces exactly one final `outcome`:

- `outcome.status`: `"ok"` or `"error"`
- `outcome.result`: success output (small inline payload or reference)
- `outcome.error`: structured error object (MUST include `kind`; SHOULD include `retryable`)
- `outcome.meta`: attempt, duration, timestamps, trace ids

Tool helpers MAY be present (examples):
- HTTP: `outcome.http.status`, `outcome.http.headers`
- Postgres: `outcome.pg.code`, `outcome.pg.sqlstate`
- Python: `outcome.py.exception_type`

---

## Task policy rules (control actions)

Canonical placement: `task.spec.policy.rules`.

Shape:
```yaml
spec:
  policy:
    rules:
      - when: "{{ ... }}"
        then:
          do: continue|retry|jump|break|fail
          attempts: 5
          backoff: none|linear|exponential
          delay: 1.0
          to: some_task_label
          set_iter: { ... }
          set_ctx: { ... }
      - else:
          then: { do: continue }
```

Semantics:
- Evaluate rules top-to-bottom; first match wins; `else` is fallback.
- If `spec.policy` is omitted:
  - ok → `continue`
  - error → `fail`
- If policy is present but no rule matches and no `else` is provided:
  - default → `continue` (canonical v10 default)

---

## Streaming pagination inside a pipeline (canonical pattern)

Pagination and polling are modeled as **pipeline control flow**:
- keep counters/cursors in `iter.*`
- use a `paginate` decision task that `jump`s back to `fetch_page` or `break`s

For a full canonical example, see `documentation/docs/reference/dsl/pagination.md`.

---

## Best practices

- Prefer **policy-based retry** (`do: retry`) over tool-internal retry so events stay accurate and replayable.
- Use **`iter`** for per-item paging/cursors; use **external storage** + ResultRefs for large page bodies.
- Avoid writing conflicting keys into `ctx` from parallel iterations until reducers/atomics exist.
