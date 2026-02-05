---
sidebar_position: 8
title: Runtime State and Variables (Canonical)
description: Canonical runtime scopes (workload, ctx, vars, iter) and external mutation model for NoETL DSL v2
---

# Runtime State and Variables (Canonical v2)

This document replaces legacy “vars system” semantics with the **canonical v2** runtime model.

Canonical principles:
- Playbook root sections are **metadata, executor, workload, workflow, workbook** (no playbook-root `vars`).
- A step is **`when` + `tool` (ordered pipeline) + `next`**.
- Mutation is expressed through **tool-level `eval` writes**:
  - `set_iter` (iteration-local)
  - `set_vars` (step-run-local)
  - `set_ctx` (execution-scoped, event-sourced patch)
- Results should be **reference-first**; large payloads belong in external storage with references in events/context.
- “sink” is a *pattern* (a tool task that writes data and returns a reference), not a tool kind.

---

## 1) Overview

NoETL exposes four distinct scopes to templates and the runtime:

1. **`workload`** — immutable execution input (merged defaults + request payload)
2. **`ctx`** — execution-scoped mutable context (cross-step state, event-sourced patches)
3. **`vars`** — step-run-scoped mutable state (local to a single step run)
4. **`iter`** — iteration-scoped mutable state (isolated per iteration, safe in parallel loops)

Additionally, there are pipeline-local variables:
- `_prev`, `_task`, `_attempt`, `outcome`, and a `results` map (implementation-defined)

---

## 2) Scope semantics

### 2.1 `workload` (immutable)
`workload` is computed once at execution start by merging:
- playbook workload defaults
- execution request payload overrides

`workload` MUST be treated as immutable for the execution instance.

Use for:
- endpoints, credentials keys, configuration defaults
- initial page sizes / concurrency hints
- static policies, thresholds

### 2.2 `ctx` (execution scope, mutable)
`ctx` is mutable state shared across steps within one execution.

**Key rule:** `ctx` mutations MUST be recorded as **event-sourced patches** (append-only events), not silent in-memory writes.

Use for:
- cross-step progress (`ctx.pages_fetched`, `ctx.total_rows`)
- references to stored artifacts (`ctx.last_result_ref`)
- session-like values (tokens, correlation ids) where lifecycle is the execution

### 2.3 `vars` (step scope, mutable)
`vars` is mutable state local to a **single step run** (one token consumption).

Use for:
- intermediate flags and decisions used by `next[].when`
- step-local counters
- pipeline decisions that don’t need to survive across steps

`vars` does not persist beyond the step run unless explicitly promoted into `ctx`.

### 2.4 `iter` (iteration scope, mutable)
If `step.loop` is present, each iteration has an isolated `iter` scope.

Use for:
- iterator binding (`iter.<iterator>`)
- pagination state (`iter.page`, `iter.cursor`, `iter.has_more`)
- per-iteration metrics (`iter.rows_inserted`)

In **parallel** loop mode, `iter` is always safe because it is isolated per iteration.

---

## 3) Writing variables (canonical mechanism)

In canonical v2, there is **no step-level `vars:` extraction block**.
All updates occur via `eval` directives after a tool task produces an `outcome`.

### 3.1 `set_iter`
Writes iteration-local state (preferred for pagination and loop-local progress).

### 3.2 `set_vars`
Writes step-run-local state.

### 3.3 `set_ctx`
Writes execution-scoped state as an event-sourced patch.

### 3.4 `set_shared` (optional future)
For parallel loops, shared writes require explicit reducer/atomic semantics (optional profile).
If unsupported, the runtime MUST reject `set_shared` or any ambiguous shared mutation.

---

## 4) Reading variables in templates

Canonical access patterns:
- `{{ workload.api_url }}`
- `{{ ctx.last_ref }}`
- `{{ vars.ok }}`
- `{{ iter.endpoint.path }}`

Pipeline locals:
- `{{ _prev }}`
- `{{ _task }}`
- `{{ _attempt }}`
- `{{ outcome.status }}`

> If you want a pipeline-local value visible to `next[].when`, write it to `vars` or `ctx` using `eval`.

---

## 5) External mutation (API model)

Legacy docs described a “variables API” for external systems. In canonical v2, external mutation should be modeled explicitly as one of:

### 5.1 Workload override (start-time only)
External systems override `workload` values at execution request time. This is immutable thereafter.

### 5.2 Execution context patch (mid-execution)
External systems MAY patch `ctx` during execution for:
- approvals
- dynamic configuration toggles
- operator interventions
- sensor/session state updates

This is a **first-class event** and must be auditable.

Recommended semantics:
- API accepts a JSON patch-like payload (or key-value map)
- server records `ctx.patched` (or equivalent) event
- patch becomes visible as `ctx.*` to subsequent step runs

### 5.3 Token injection (advanced)
External systems MAY inject new tokens by calling an API that schedules a step with `args`. This is distinct from variable mutation and should be treated as orchestration input.

> If you keep legacy `/api/vars/{execution_id}` endpoints for compatibility, they should be reinterpreted as `ctx` patches (execution-scope), not “step vars”.

---

## 6) Metadata tracking

State changes should be traceable through the event log. For each `ctx` patch, recommended metadata includes:
- who/what performed the patch (principal)
- reason / message
- timestamp
- correlation id

Reads through an API are not required to increment access counters in the canonical spec (implementation choice). If you keep access counters, store them in projections, not in the authoritative event log.

---

## 7) Parallel loops and safety

### 7.1 Safe by default
- Read-only access to `workload` and `ctx` is safe.
- Writing to `iter` is safe (isolated).
- Writing to `vars` is safe (per step run).

### 7.2 Shared mutation
When `loop.spec.mode: parallel`, multiple step runs/iterations execute concurrently. To avoid races:
- Prefer writing outputs to external storage (db/object/kv) and returning references.
- Promote only stable references/counters into `ctx` using reducers/aggregation steps.
- If reducers are not supported, the runtime MUST reject ambiguous shared writes.

---

## 8) Recommended patterns

### 8.1 Pagination state
Keep cursor/page counters in `iter.*`, updated via `eval.set_iter`.

### 8.2 Cross-step handoff
Write a ResultRef into `ctx` (or pass via `next[].args` if it is small).

### 8.3 Operator approval
External system patches `ctx.approved = true`. Next routing uses `next[].when` on `ctx.approved`.

---

## Links
- Execution Model (canonical): `execution_model_v2.md`
- Retry Handling (canonical): `retry_mechanism_v2.md`
- Result Storage (canonical): `result_storage_v2.md`
- Pipeline Execution (canonical): `pipeline_execution_v2.md`
