---
sidebar_position: 12
title: Pipeline Execution (Canonical)
description: Atomic, ordered task pipelines inside a step using tool-level eval (no pipe/case)
---

# Pipeline Execution (Canonical)

Pipeline execution in NoETL enables an **atomic, ordered sequence of tool tasks** executed **within a single step run** on a **single worker**. It provides:

- **Clojure-style data threading** using `_prev`
- **Per-task flow control** using `eval: - expr:` directives
- **Deterministic replay** via event sourcing
- **No special `pipe:` construct** and **no step-level `case: when: then:` required** for normal execution

In canonical v2:
- A step body is an ordered **pipeline**: `step.tool: [ task1, task2, ... ]`
- Routing is handled at step level: `step.next[]`
- Retry/pagination/polling/early-exit are expressed per task via `eval`

---

## Overview

A step run is dispatched by the server to a worker. The worker executes `step.tool` in order, applying `eval` after each task to decide how to proceed.

```
token → step.when (server) → step.run dispatched
                         ↓
                  worker executes:
  task1 → eval → task2 → eval → task3 → eval → terminal
                         ↓
                step.done / step.failed / loop.done
                         ↓
          server evaluates step.next[] (next_mode)
```

---

## Key Features

| Feature | Description |
|---------|-------------|
| **Data Threading** | `_prev` carries the previous task output |
| **Atomic Execution** | Entire `step.tool` pipeline runs on one worker for the step run |
| **Per-Task Flow Control** | `eval` handles retry/jump/break/fail/continue after each task |
| **Control Actions** | `continue`, `retry`, `break`, `jump`, `fail` |
| **Outcome Object** | `outcome` provides structured access to results/errors |
| **Runtime Context** | `_task`, `_prev`, `_attempt`, `outcome` available in templates |
| **Scoped Writes** | `set_iter`, `set_vars`, `set_ctx`, optional `set_shared` |
| **No special DSL blocks** | No `pipe:` and no `case: then:` required for pipelines |

---

## Canonical Structure

A canonical step pipeline:

```yaml
- step: fetch_transform_store
  tool:
    - fetch:
        kind: http
        url: "..."
        eval:
          - expr: "{{ outcome.status == 'error' and outcome.error.retryable == true }}"
            do: retry
            attempts: 5
            backoff: exponential
            delay: 1.0
          - expr: "{{ outcome.status == 'error' }}"
            do: fail
          - else:
              do: continue

    - transform:
        kind: python
        args:
          data: "{{ _prev }}"
        code: |
          result = transform(data)

    - store:
        kind: postgres
        query: "INSERT INTO ... VALUES ({{ _prev }})"
        eval:
          - expr: "{{ outcome.error.kind == 'db_deadlock' }}"
            do: retry
            attempts: 3
          - else:
              do: continue
              set_vars:
                store_ok: true

  next:
    - step: continue
      when: "{{ vars.store_ok == true }}"
    - step: failed
      when: "{{ vars.store_ok != true }}"
```

> `next[]` is evaluated by the **server** after the worker emits `step.done/step.failed/loop.done`. `next` is **not** part of the pipeline list.

---

## Runtime Variables

Available during pipeline execution:

| Variable | Type | Scope | Description |
|----------|------|-------|-------------|
| `_task` | string | Pipeline-local | Current task label |
| `_prev` | any | Pipeline-local | Previous task result |
| `_attempt` | int | Pipeline-local | Retry attempt number (1-based) |
| `outcome` | object | Pipeline-local | Current task outcome envelope |
| `results` | dict | Pipeline-local | Task results by label |
| `vars` | dict | Step-run | Mutable step state (local to this step run) |
| `iter` | dict | Iteration | Per-iteration state (isolated in parallel loops) |
| `ctx` | dict | Execution | Cross-step mutable execution state (event-sourced patches) |

---

## Variable Scoping

### Step-scoped variables (`vars`)
- Mutable state local to a single step run
- Set via `eval.set_vars`
- Visible to subsequent tasks in the same step and to `next[].when` evaluation

### Iteration-scoped variables (`iter`)
- Exists only within a loop iteration
- Isolated per iteration, safe in parallel loops
- Set via `eval.set_iter`
- Recommended location for pagination state (`page`, `has_more`, etc.)

### Execution-scoped context (`ctx`)
- Shared across steps within an execution
- Updated via `eval.set_ctx` (must be persisted as patches/events)
- Recommended location for cross-step references (ResultRefs, counters)

### Pipeline locals
- `_prev`, `_task`, `_attempt`, `outcome`, `results`
- Only valid during pipeline execution
- To expose values outside the pipeline, write to `vars`, `iter`, or `ctx`

---

## The `outcome` Object

After each task runs, `outcome` is populated:

```yaml
outcome:
  status: "success" | "error"
  result: <tool output>         # if success
  error:                        # if error
    kind: "rate_limit"
    retryable: true
    code: "HTTP_429"
    message: "Too Many Requests"
    retry_after: 60
  meta:
    attempt: 1
    duration_ms: 150
  # Tool-specific helpers:
  http:
    status: 429
    headers: {...}
  pg:
    code: "23505"
    sqlstate: "23505"
  py:
    exception: "ValueError"
    traceback: "..."
```

---

## Default Behavior

If `eval` is omitted for a task, canonical defaults apply:
- **Success** → `continue`
- **Error** → `fail`

These two are equivalent:

```yaml
- fetch:
    kind: http
    url: "..."
    # no eval → default behavior

- fetch:
    kind: http
    url: "..."
    eval:
      - expr: "{{ outcome.status == 'error' }}"
        do: fail
      - else:
          do: continue
```

---

## Control Actions

### continue
Proceed to the next task.

### retry
Retry the current task:

```yaml
eval:
  - expr: "{{ outcome.error.retryable }}"
    do: retry
    attempts: 5
    backoff: exponential
    delay: 1.0
```

### break
Stop the pipeline successfully (emit `step.done`) and return to step-level routing:

```yaml
eval:
  - expr: "{{ iter.has_more == false }}"
    do: break
```

### jump
Jump to a named task label (used for pagination/polling loops inside a step):

```yaml
eval:
  - expr: "{{ iter.has_more == true }}"
    do: jump
    to: fetch
    set_iter:
      page: "{{ (iter.page | int) + 1 }}"
```

### fail
Stop the pipeline with error (emit `step.failed`):

```yaml
eval:
  - expr: "{{ outcome.error.kind == 'auth' }}"
    do: fail
```

---

## Setting Variables

### set_vars (step-run scope)
```yaml
eval:
  - else:
      do: continue
      set_vars:
        processed: true
```

### set_iter (iteration scope)
```yaml
eval:
  - else:
      do: continue
      set_iter:
        has_more: "{{ outcome.result.data.paging.hasMore }}"
        page: "{{ outcome.result.data.paging.page }}"
```

### set_ctx (execution scope)
```yaml
eval:
  - else:
      do: continue
      set_ctx:
        last_ref: "{{ outcome.result._ref }}"
```

### set_shared (optional reducers/atomics)
In parallel loops, shared writes MUST be explicit and reducer-based (optional feature).

---

## Practical Examples

### Example 1: Pagination with Fetch → Transform → Store (jump loop)

```yaml
- step: paginate_store
  loop:
    spec: { mode: sequential }
    in: "{{ workload.endpoints }}"
    iterator: endpoint

  tool:
    - init:
        kind: noop
        eval:
          - else:
              do: continue
              set_iter: { page: 1 }

    - fetch:
        kind: http
        url: "{{ workload.api_url }}{{ iter.endpoint.path }}"
        params: { page: "{{ iter.page }}", pageSize: "{{ iter.endpoint.page_size }}" }
        eval:
          - expr: "{{ outcome.error.kind == 'rate_limit' }}"
            do: retry
            attempts: 10
            delay: "{{ outcome.error.retry_after | default(5) }}"
          - expr: "{{ outcome.error.retryable }}"
            do: retry
            attempts: 5
            backoff: exponential
            delay: 2.0
          - expr: "{{ outcome.status == 'error' }}"
            do: fail
          - else:
              do: continue
              set_iter:
                has_more: "{{ outcome.result.data.paging.hasMore | default(false) }}"
                items: "{{ outcome.result.data.data | default([]) }}"

    - transform:
        kind: python
        args: { data: "{{ _prev }}" }
        code: |
          items = data.get("data", {}).get("data", [])
          result = {"items": items}

    - store:
        kind: postgres
        query: "INSERT INTO results ..."
        eval:
          - expr: "{{ outcome.error.kind == 'db_deadlock' }}"
            do: retry
            attempts: 3
            backoff: linear
            delay: 1.0
          - expr: "{{ outcome.status == 'error' }}"
            do: fail
          - else:
              do: continue

    - paginate:
        kind: noop
        eval:
          - expr: "{{ iter.has_more == true }}"
            do: jump
            to: fetch
            set_iter:
              page: "{{ (iter.page | int) + 1 }}"
          - else:
              do: break

  next:
    - step: complete
```

### Example 2: Conditional processing (jump to fallback)

```yaml
- step: validate_and_process
  tool:
    - validate:
        kind: python
        args: { data: "{{ args.input }}" }
        code: |
          result = {"valid": len(data) > 0, "data": data}

    - process_valid:
        kind: python
        args: { validated: "{{ _prev }}" }
        code: |
          if not validated["valid"]:
              raise ValueError("Invalid data")
          result = expensive_processing(validated["data"])
        eval:
          - expr: "{{ outcome.py.exception == 'ValueError' }}"
            do: jump
            to: fallback
          - else:
              do: continue

    - fallback:
        kind: python
        code: |
          result = {"status": "skipped", "reason": "invalid data"}
```

---

## Pipeline Result (conceptual)

A pipeline yields a terminal step status:

- `step.done` on success / `break`
- `step.failed` on `fail` or unhandled errors

Additionally, the worker can provide:
- final `_prev` (last result)
- `results` map for debugging
- references stored in `ctx/vars/iter`

---

## Best Practices

1. Use pipelines for **tightly coupled operations** (fetch → transform → store).
2. Prefer task-local `eval` rather than global retry wrappers.
3. Use `jump` for pagination/polling loops; keep state in `iter`.
4. For large payloads, externalize results and pass **references**.
5. In parallel loops, avoid shared writes; use `iter` or reducer-based `set_shared`.

---

## Related Documentation

- Result Storage (canonical): `result_storage_v2.md`
- Retry Mechanism (canonical): `retry_mechanism_v2.md`
- Execution Model (canonical): `execution_model_v2.md`
