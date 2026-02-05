---
sidebar_position: 4
title: DSL Specification
description: Complete technical specification for NoETL DSL v2 - Petri Net execution model (canonical)
---

# NoETL DSL v2 Specification (Canonical)

This document defines the **canonical** NoETL DSL v2 execution model and its runtime semantics.
It is intended to be used as the implementation target for the control plane (**server.py**) and data plane (**worker.py**) as well as for fixture playbooks.

## Status and Scope

This canonical spec intentionally simplifies earlier designs:

- **Canonical step = `when + tool(pipeline) + next`** (Petri-net transition form).
- **No `pipe:` construct**. A `step.tool` list is always an ordered pipeline.
- **No step-level `case: when: then:` for normal execution**.
  - `case` may exist later as an advanced feature (multi-body/event-listener steps), but is not required for the baseline.
- All behavior and runtime knobs are under **`spec`** at the nearest scope (playbook/step/loop/tool/next).

---

## 1. Playbook Document Model

### 1.1 Root Sections (only)

A playbook document MUST contain only these root sections:

- `apiVersion`
- `kind`
- `metadata`
- `executor` (optional)
- `workload`
- `workflow`
- `workbook` (optional)

> **NOTE:** `vars` MUST NOT exist at playbook root level.

### 1.2 Example Root Layout

```yaml
apiVersion: noetl.io/v2
kind: Playbook

metadata:
  name: example
  path: examples/example
  version: "2.0"
  description: Example playbook

executor:
  kind: distributed
  spec:
    # server/worker/queue selection knobs (implementation-defined)
    pool: default

workload:
  # immutable merged execution input (defaults + request payload)
  api_url: "https://example.com"

workflow:
  - step: start
    ...

workbook:
  # optional catalog of named tasks/tools (future/optional)
  tasks: {}
```

---

## 2. Execution Model (Petri Net / State Machine)

### 2.1 Tokens

Execution is modeled as **tokens** moving through steps.

Token envelope (minimum):
- `execution_id`
- `step` (target step name)
- `args` (arc inscription payload; optional)
- optional: `trace_id`, `parent_step_run_id`

Tokens are created by:
- initial execution request (start token)
- firing of `next[]` arcs from completed steps

### 2.2 Steps as Transitions

A **step** is a Petri-net transition:
- `step.when` is the transition **enable guard**
- `step.tool` is the transition **action** (pipeline executed by a worker)
- `step.next[]` are the outgoing **arcs** producing new tokens

---

## 3. Scopes and State

NoETL separates immutable input from mutable execution state and local runtime state.

### 3.1 `workload` (immutable)
`workload` is immutable for the execution instance and is the merge of:
- playbook `workload` defaults
- execution request payload overrides

### 3.2 `ctx` (execution scope, mutable)
`ctx` is mutable state shared across steps within one playbook execution.
Typical uses:
- session state
- counters and progress
- references to externally stored results (table ranges, object keys, etc.)

**Persistence rule:** `ctx` updates MUST be recorded as event-sourced **patches** (not full snapshots).

### 3.3 `vars` (step scope, mutable)
`vars` is mutable state local to a **single step run** (one token consumption).

### 3.4 `iter` (iteration scope, mutable)
When a step has a `loop`, each iteration has isolated `iter` scope:
- `iter.<iterator>` binds current element
- `iter.index` identifies iteration
- `iter.*` holds pagination state (page, has_more, etc.)

### 3.5 Pipeline locals
Within a step pipeline:
- `_prev`: previous task output
- `_task`: current task label
- `_attempt`: attempt counter for current task

### 3.6 Precedence recommendation
For reads in templates:
`args` (step input) → `ctx` (execution state) → `workload` (defaults)

For writes:
- per-iteration → `iter`
- per-step transient → `vars`
- cross-step shared → `ctx`

---

## 4. Canonical Step Specification

### 4.1 Step Shape

```yaml
- step: <name>
  desc: <optional>

  spec:
    next_mode: exclusive | inclusive   # default: exclusive
    # optional (implementation-defined):
    # timeout: 300
    # lease: { mode: single_owner, ttl: 30, heartbeat: 5 }

  when: "{{ <expr> }}"                 # default: true

  loop:
    spec:
      mode: sequential | parallel      # default: sequential
      # optional:
      # max_in_flight: 10
    in: "{{ <collection expr> }}"
    iterator: <name>

  tool:
    - <task_label_1>: { ... }
    - <task_label_2>: { ... }

  next:
    - step: <next_step>
      when: "{{ <expr> }}"            # default: true
      args: { ... }
```

### 4.2 `spec.next_mode` (step)
Controls how `next[]` arcs are fired:
- `exclusive` (default): first matching `next[]` (YAML order)
- `inclusive`: all matching `next[]` fire (fan-out)

### 4.3 Step enable guard (`step.when`)
Evaluated by the **server** when routing a token to a step.
If omitted, `true`.

---

## 5. Step Body = Ordered Pipeline (`step.tool`)

### 5.1 Pipeline Task
Each entry in `step.tool` is a labeled task with a tool invocation.

Canonical task form:

```yaml
- fetch_page:
    kind: http
    spec: { ... }   # runtime knobs
    ...inputs...
    eval: [ ... ]   # outcome -> directive mapping (optional)
```

### 5.2 Tool runtime knobs (`tool.spec`)
All tool policy and runtime knobs belong under `spec`:
- timeouts
- connection pooling
- internal retry policy (optional)
- resource hints / sandbox settings

### 5.3 Tool outcome envelope (`outcome`)
Every tool returns exactly one final outcome:

- `outcome.status`: `"success"` | `"error"`
- `outcome.result`: value (success)
- `outcome.error`: object (error)
- `outcome.meta`: attempt, duration, trace ids, timestamps

Optional helpers:
- HTTP: `outcome.http.status`, `outcome.http.headers`
- Postgres: `outcome.pg.code`, `outcome.pg.message`
- Python: `outcome.py.exception`

---

## 6. Tool-level Flow Control (`eval`)

### 6.1 Purpose
`eval` maps a tool outcome to a deterministic control directive for the pipeline.

### 6.2 Syntax

```yaml
eval:
  - expr: "{{ <bool expr> }}"
    do: continue | retry | jump | break | fail
    attempts: <int>                # retry
    backoff: fixed | linear | exponential
    delay: <seconds|expr>
    to: <task_label>               # jump
    set_iter: { ... }              # iteration-scoped write (preferred in loops)
    set_vars: { ... }              # step-scoped write
    set_ctx: { ... }               # execution-scoped patch
    set_shared: { ... }            # explicit shared write (reducers/atomics; optional feature)
    set_prev: <value>              # override pipeline _prev
  - else:
      do: continue
```

### 6.3 Defaults (if eval omitted)
If `eval` is omitted (or no match + no else):
- success → `continue`
- error → `fail`

### 6.4 Directive semantics
- `continue`: advance to next task
- `retry`: rerun current task with attempt++ (bounded by `attempts`)
- `jump`: set program counter to `to`
- `break`: stop pipeline successfully (step emits `step.done`)
- `fail`: stop pipeline as failure (step emits `step.failed`)

### 6.5 Parallel loop safety
If `loop.spec.mode: parallel`:
- `set_iter` is always safe (isolated per iteration)
- writes to shared `vars` require explicit intent (e.g., `set_shared` reducers/atomics) OR must be deterministically mapped to iteration scope (implementation must choose one and document it)

---

## 7. Loop Specification (`step.loop`)

### 7.1 Syntax

```yaml
loop:
  spec:
    mode: sequential | parallel
    # max_in_flight: 10
  in: "{{ workload.items }}"
  iterator: item
```

### 7.2 Semantics
- The step pipeline runs once per element of `loop.in`
- Each iteration has isolated `iter` scope
- When all iterations complete, worker emits `loop.done`

---

## 8. Routing (`step.next[]`)

### 8.1 Ownership
**Server** evaluates `next[]` when it receives a terminal step event:
- `step.done`
- `step.failed`
- `loop.done`

### 8.2 `next[].when`
Each arc may have a `when` guard (default true). Guards can reference:
- terminal `event`
- `ctx`, `vars`, `workload`
- and any references produced by the step

### 8.3 Arc inscription (`next[].args`)
`args` is payload placed into the token for the next step.
This is the canonical way to pass data across steps in a Petri-net style.

---

## 9. Event Sourcing Model (Canonical)

### 9.1 Layers
- Workflow/Execution layer (server authoritative)
- Step lifecycle layer (server authoritative for scheduling; worker authoritative for execution outcome emission)
- Tool layer (worker authoritative)

### 9.2 Ownership (canonical)
| Event Type | Emitted By | Authoritative |
|-----------|------------|---------------|
| `playbook.*`, `workflow.*` | Server | Server |
| `token.*` (created/enqueued/claimed) | Server | Server |
| `step.scheduled` / `step.started` | Server | Server |
| `task.started` / `task.processed` | Worker | Worker |
| `step.done` / `step.failed` / `loop.done` | Worker | Worker |
| `next.selected` / `next.enqueued` | Server | Server |

> Note: the server may record `step.started` at scheduling time; the worker records execution completion events. Use IDs to correlate.

### 9.3 Event envelope (minimum)
Every event MUST include:
- `event_id`, `event_type`, `ts`
- `execution_id`
- `step_run_id` (when applicable)
- `task_run_id` (when applicable)
- correlation: `trace_id`, `parent_id` (optional but recommended)
- payload

---

## 10. Results and Payload Storage

### 10.1 Rule: references first
Event log should avoid huge payload bodies.
For large results:
- store externally (Postgres table, object store, etc.)
- store **references** in events and/or `ctx`

Reference shape (recommended):
```json
{ "store": "postgres.table", "key": "pagination_test_results", "range": "id:100-150", "size": 123456, "checksum": "..." }
```

### 10.2 “Sink” as a pattern
No special DSL keyword is required.
A “sink” is simply a tool task that writes to storage and returns a reference.

---

## 11. Canonical Pagination Pattern (Loop + Jump)

Pagination is expressed as a state machine inside an iteration using `jump` and `break`:

1) fetch page → set `iter.has_more`, `iter.page`, `iter.items`
2) store page (sink tool)
3) paginate:
- if `iter.has_more` → increment page and `jump` back to fetch
- else `break`

---

## 12. Compatibility / Deprecations

The following constructs from earlier drafts are **non-canonical** for this baseline:
- `pipe:`
- step-level `case: when: then:` used for normal tool pipelines
- chain-level `next_policy`, branch suppression, etc. (can be revisited as advanced case-mode later)
- root-level playbook `vars`

---

## 13. Appendix: Minimal canonical step example

```yaml
- step: fetch_transform_store
  spec: { next_mode: exclusive }
  when: "{{ true }}"

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
              set_iter: { page: 1, has_more: true }

    - fetch_page:
        kind: http
        spec: { timeout: { connect: 5, read: 15 } }
        method: GET
        url: "{{ workload.api_url }}{{ iter.endpoint.path }}"
        params:
          page: "{{ iter.page }}"
          pageSize: "{{ iter.endpoint.page_size }}"
        eval:
          - expr: "{{ outcome.status == 'error' and outcome.http.status in [429,500,502,503,504] }}"
            do: retry
            attempts: 10
            backoff: exponential
            delay: "{{ outcome.http.headers['retry-after'] | default(2) }}"
          - expr: "{{ outcome.status == 'error' }}"
            do: fail
          - else:
              do: continue
              set_iter:
                has_more: "{{ outcome.result.data.paging.hasMore | default(false) }}"
                page: "{{ outcome.result.data.paging.page | default(iter.page) }}"
                items: "{{ outcome.result.data.data | default([]) }}"

    - save_page:
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
    - step: validate_results
      when: "{{ event.name == 'loop.done' }}"
    - step: cleanup
      when: "{{ event.name == 'step.failed' }}"
```

---

## References
- NoETL canonical step/runtime prompt: `noetl_canonical_step_spec_v2.md`
