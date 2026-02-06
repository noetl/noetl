---
sidebar_position: 4
title: DSL Specification
description: Complete technical specification for NoETL DSL v2 — Canonical (Petri Net)
---

# NoETL DSL v2 Specification (Canonical)

This document defines the **canonical** NoETL DSL v2 model and runtime semantics.
It is the implementation target for:
- **Control plane**: `server.py` (orchestrator, router, scheduler, event log)
- **Data plane**: `worker.py` (tool execution + task policy control inside a step/iteration)

> Canonical intent: **Petri-net token routing on the server** + **deterministic task pipelines on the worker**.

---

## Status and Scope

Canonical v2 intentionally simplifies earlier designs:

- **Canonical step = admission policy + tool pipeline + next router**
- **No `pipe:` construct** — `step.tool` is always an ordered pipeline
- **No step-level `case: when: then:` for baseline execution**
  - `case` may be introduced later only as an advanced multi-listener / multi-body feature
- All knobs and behaviors are expressed under **`spec`**, with policies under **`spec.policy`**
- `when` is the **only** conditional keyword in the DSL

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

> **NOTE:** root-level `vars` MUST NOT exist.

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
    pool: default
    policy:
      # global runtime defaults (implementation-defined)
      results:
        reference_first: true
      limits:
        max_payload_bytes: 1048576

workload:
  api_url: "https://example.com"

workflow:
  - step: start
    ...

workbook:
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
- initial execution request (entry token)
- firing of `next.arcs[]` from completed steps

### 2.2 Steps as Transitions

A **step** is a Petri-net transition with:
- **Admission gate**: `step.spec.policy.admit` (server-side)
- **Action**: `step.tool` pipeline (worker-side)
- **Outgoing arcs**: `step.next.arcs[]` (server-side)

There is **no** `step.when` field in canonical v2.
All gating and routing must be expressed via `spec.policy` (step scope) and `next` (routing scope).

---

## 3. Scopes and State

NoETL separates immutable input from mutable execution state and local iteration state.

### 3.1 `workload` (immutable)
`workload` is immutable for the execution instance and is the merge of:
- playbook `workload` defaults
- execution request payload overrides

### 3.2 `ctx` (execution scope, mutable)
`ctx` is mutable state shared across steps within one playbook execution.

Typical uses:
- session state
- progress counters
- references to externally stored results (table ranges, object keys, etc.)

**Persistence rule:** `ctx` updates MUST be recorded as event-sourced **patches** (not full snapshots).

### 3.3 `iter` (iteration scope, mutable)
When a step has a `loop`, each iteration has isolated `iter` scope:
- `iter.<iterator>` binds the current element
- `iter.index` identifies iteration
- `iter.*` holds streaming/pagination state (page, has_more, status codes, etc.)

### 3.4 Pipeline locals (within a step/iteration)
Within a pipeline:
- `_prev`: previous task output (canonical: previous task’s `outcome.result`)
- `_task`: current task label
- `_attempt`: attempt counter for current task

### 3.5 Nested loops
Canonical addressing:
- `iter` is current iteration scope
- `iter.parent` is outer iteration scope
- `iter.parent.parent` for deeper nesting

### 3.6 Read precedence recommendation
For reads in templates:
`args` (token inscription) → `ctx` (execution state) → `iter` (iteration state) → `workload` (defaults)

> Note: in practice `iter` is only available when a loop is active; otherwise it is absent.

---

## 4. Canonical Step Specification

### 4.1 Step Shape (canonical)

```yaml
- step: <name>
  desc: <optional>

  spec:
    # step-level knobs (timeouts, leases, etc.) — implementation-defined
    policy:
      admit:                          # server-side admission gate (optional)
        mode: exclusive               # exclusive | inclusive (default exclusive)
        rules:
          - when: "{{ <expr> }}"
            then: { allow: true }
          - else:
              then: { allow: false }

  loop:                               # optional
    spec:
      mode: sequential | parallel     # default sequential
      max_in_flight: 10               # optional
      policy:
        exec: distributed | local     # optional intent hint
    in: "{{ <collection expr> }}"
    iterator: <name>

  tool:                               # ordered pipeline
    - <task_label_1>: { ... }
    - <task_label_2>: { ... }

  next:                               # server-side routing router
    spec:
      mode: exclusive | inclusive     # default exclusive
      policy: {}                      # reserved
    arcs:
      - step: <next_step>
        when: "{{ <expr> }}"          # default true
        args: { ... }                 # arc inscription
```

### 4.2 Step admission (server)
Admission is defined only by `step.spec.policy.admit.rules`.

Rules are evaluated top-to-bottom:
- First matching `when` wins (exclusive admission)
- `else` is recommended
- If `admit` is omitted, default admission is **allow**

Admission evaluation inputs:
- `ctx`, `workload`, and the incoming token `event` / `args` (implementation-defined naming)
- No step-local pipeline variables are available at admission time

---

## 5. Step Body = Ordered Pipeline (`step.tool`)

### 5.1 Pipeline Task (canonical)
Each entry in `step.tool` is a labeled **task** that invokes a tool `kind`.

Canonical task form:

```yaml
- fetch_page:
    kind: http
    spec:
      timeout: { connect: 5, read: 15 }
      policy:
        rules:
          - when: "{{ outcome.status == 'error' and outcome.http.status in [429,500,502,503,504] }}"
            then: { do: retry, attempts: 10, backoff: exponential, delay: 2.0 }
          - else:
              then: { do: continue }
    method: GET
    url: "{{ workload.api_url }}/path"
    params: { ... }
```

### 5.2 Tool runtime knobs (`task.spec`)
All tool runtime knobs belong under `task.spec`:
- timeouts
- connection pooling
- sandbox/resource hints
- internal retry (optional; see §6.4)

### 5.3 Tool outcome envelope (`outcome`)
Every tool returns exactly one final outcome:

- `outcome.status`: `"ok"` | `"error"`
- `outcome.result`: value or reference (on ok)
- `outcome.error`: object (on error)
- `outcome.meta`: attempt, duration, timestamps, trace ids, etc.

Kind-specific stable fields (examples):
- HTTP: `outcome.http.status`, `outcome.http.headers`
- Postgres: `outcome.pg.code`, `outcome.pg.sqlstate`
- Python: `outcome.py.exception_type`

---

## 6. Task-level Flow Control (`task.spec.policy.rules`)

### 6.1 Purpose
`task.spec.policy.rules` maps an outcome to a deterministic directive for the pipeline.

### 6.2 Syntax (canonical)
```yaml
spec:
  policy:
    rules:
      - when: "{{ <bool expr> }}"
        then:
          do: continue | retry | jump | break | fail
          attempts: <int>                # retry
          backoff: none | linear | exponential
          delay: <seconds|expr>
          to: <task_label>               # jump
          set_iter: { ... }              # iteration write (preferred in loops)
          set_ctx: { ... }               # execution patch
      - else:
          then:
            do: continue
```

### 6.3 Defaults
If `task.spec.policy` is omitted:
- ok → continue
- error → fail

If `rules` exist but nothing matches and no `else`:
- default is **continue** (canonical)

### 6.4 Two retry layers (optional)
1) **Tool-internal retry** (inside `task.spec` knobs; e.g., HTTP client retry)
2) **Canonical policy retry** (`then.do: retry`)

Order:
- Task executes using `task.spec` runtime knobs
- Task emits a single final `outcome`
- Policy evaluates that outcome
- Policy may retry the whole task (canonical)

Recommendation:
- Keep tool-internal retry minimal
- Prefer canonical policy retry for deterministic event sourcing and observability

### 6.5 Directive semantics
- `continue`: advance to next task
- `retry`: rerun current task with attempt++ (bounded by `attempts`)
- `jump`: set program counter to `to`
- `break`: stop pipeline successfully (iteration done / step done)
- `fail`: stop pipeline as failure (iteration failed / step failed)

### 6.6 Parallel loop safety
If `loop.spec.mode: parallel`:
- `set_iter` is always safe (isolated per iteration)
- `set_ctx` MUST be restricted:
  - write-once per key or append-only strategies, OR
  - reject conflicting writes unless reducers/atomics exist (future)

---

## 7. Loop Specification (`step.loop`)

### 7.1 Syntax
```yaml
loop:
  spec:
    mode: sequential | parallel
    max_in_flight: 10
    policy:
      exec: distributed | local
  in: "{{ workload.items }}"
  iterator: item
```

### 7.2 Semantics
- The step pipeline runs once per element of `loop.in`
- Each iteration has isolated `iter` scope
- When all iterations complete, the worker emits a terminal loop event (`loop.done`), persisted by server

---

## 8. Routing (`step.next` router with arcs)

### 8.1 Ownership
**Server** evaluates routing when it receives terminal step events:
- `step.done`
- `step.failed`
- `loop.done` (if a loop is present)

### 8.2 `next.arcs[].when`
Each arc may have a `when` guard (default true). Guards can reference:
- terminal `event`
- `ctx`, `workload`
- references produced by the step (via `ctx` patches or outcome refs; implementation-defined access)

### 8.3 Arc inscription (`next.arcs[].args`)
`args` is payload placed into the token for the next step.
This is the canonical way to pass data across steps in Petri-net style.

### 8.4 Fan-out vs exclusive
Routing fan-out is controlled by `next.spec.mode`:
- `exclusive` (default): first matching arc fires (YAML order)
- `inclusive`: all matching arcs fire (fan-out)

---

## 9. Event Sourcing Model (Canonical)

### 9.1 Layers
- Workflow/Execution layer (server authoritative)
- Step scheduling + routing layer (server authoritative)
- Task execution layer (worker authoritative for outcomes)

### 9.2 Ownership (canonical)
| Event Type | Emitted By | Authoritative |
|-----------|------------|---------------|
| `playbook.*`, `workflow.*` | Server | Server |
| `token.*` (created/enqueued/claimed) | Server | Server |
| `step.scheduled` / `step.started` | Server | Server |
| `task.started` / `task.done` | Worker | Worker |
| `step.done` / `step.failed` / `loop.done` | Worker | Worker |
| `next.selected` / `next.enqueued` | Server | Server |

> Note: server may record `step.started` at scheduling time; worker records execution completion. Use stable run IDs to correlate.

### 9.3 Event envelope (minimum)
Every event MUST include:
- `event_id`, `event_type`, `ts`
- `execution_id`
- `step_run_id` (when applicable)
- `task_run_id` (when applicable)
- correlation: `trace_id`, `parent_id` (recommended)
- payload (metadata + references)

---

## 10. Results and Payload Storage

### 10.1 Rule: references first
Avoid huge payload bodies in the event log.
For large results:
- store externally (Postgres table, object store, etc.)
- store **references** in events and/or `ctx`

Reference shape (recommended):
```json
{ "store": "postgres.table", "key": "pagination_test_results", "range": "id:100-150", "size": 123456, "checksum": "..." }
```

### 10.2 “Sink” is a pattern, not a kind
No special DSL keyword is required.
A “sink” is simply a tool task that writes to storage and returns a reference.

---

## 11. Canonical Pagination Pattern (Streaming inside an iteration)

Pagination is expressed as a state machine inside an iteration using `jump` and `break`:

1) fetch page → set `iter.has_more`, `iter.page`, `iter.items`
2) store page (a storage tool task)
3) paginate decision task:
- if `iter.has_more` → increment page and `jump` back to fetch
- else `break`

This supports hierarchical concurrency:
- outer loops can be parallel/distributed (cities/hotels)
- inner paging is sequential per item (rooms per hotel)

---

## 12. Compatibility / Deprecations

The following constructs are **non-canonical** for baseline v2:
- `pipe:`
- legacy `eval:` blocks
- `expr:` condition keyword
- top-level `step.when`
- step-level `case: when: then:` for normal pipelines
- root-level playbook `vars`

---

## 13. Appendix: Minimal canonical step example

```yaml
- step: fetch_transform_store

  spec:
    policy:
      admit:
        rules:
          - else:
              then: { allow: true }

  loop:
    spec:
      mode: sequential
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

    - save_page:
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
    spec:
      mode: exclusive
    arcs:
      - step: validate_results
        when: "{{ event.name == 'loop.done' }}"
      - step: cleanup
        when: "{{ event.name == 'step.failed' }}"
```
