---
sidebar_position: 8
title: Runtime State and Variables (Canonical v10)
description: Canonical runtime scopes (workload, keychain, ctx, iter, args) and mutation model for the NoETL DSL (Canonical v10)
---

# Runtime State and Variables (Canonical v10)

This document defines the canonical runtime scopes and mutation model aligned with **Canonical v10**.

Canonical principles:
- Playbook root sections are **metadata, keychain (optional), executor (optional), workload, workflow, workbook (optional)** (no playbook-root `vars`).
- A step is **admission policy + tool pipeline + next router** (Petri-net arcs).
- Mutation is expressed through **task policy actions** (`task.spec.policy.rules[].then.set_*`):
  - `set_iter` (iteration-local; always safe)
  - `set_ctx` (execution-scoped; event-sourced patch; restricted in parallel loops until reducers/atomics exist)
- Results should be **reference-first**; large payloads belong in external storage with references in events/context.
- “sink” is a *pattern* (a tool task that writes data and returns a reference), not a tool kind.

---

## 1) Overview

NoETL exposes these scopes to templates and policies:

1. **`workload`** — immutable execution input (merged defaults + request payload)
2. **`keychain`** — resolved credentials/secrets (read-only)
3. **`ctx`** — execution-scoped mutable context (cross-step state, event-sourced patches)
4. **`iter`** — iteration-scoped mutable state (isolated per iteration, safe in parallel loops)
5. **`args`** — token payload / arc inscription for the current step-run

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

### 2.2 `keychain` (resolved, read-only)
`keychain` is resolved by the runtime before execution (based on the playbook’s root `keychain` declarations) and exposed to templates as:
- `{{ keychain.<name>... }}`

`keychain` MUST be treated as read-only during execution (refresh/rotation is implemented via tools + policies, not by mutating `keychain`).

### 2.3 `ctx` (execution scope, mutable)
`ctx` is mutable state shared across steps within one execution.

**Key rule:** `ctx` mutations MUST be recorded as **event-sourced patches** (append-only events), not silent in-memory writes.

Use for:
- cross-step progress (`ctx.pages_fetched`, `ctx.total_rows`)
- references to stored artifacts (`ctx.last_result_ref`)
- session-like **non-secret** values (correlation ids, feature flags) where lifecycle is the execution

### 2.4 `iter` (iteration scope, mutable)
If `step.loop` is present, each iteration has an isolated `iter` scope.

Use for:
- iterator binding (`iter.<iterator>`)
- pagination state (`iter.page`, `iter.cursor`, `iter.has_more`)
- per-iteration metrics (`iter.rows_inserted`)

In **parallel** loop mode, `iter` is always safe because it is isolated per iteration.

### 2.5 `args` (token payload)
`args` is the immutable payload carried by the incoming token (arc inscription). It is the canonical way to pass small inputs across steps:
- authored at `step.next.arcs[].args`
- consumed as `{{ args.* }}` in the downstream step

---

## 3) Writing variables (canonical mechanism)

In Canonical v10 there is **no `vars:` extraction block** and no legacy `eval`.
All updates occur via **task policy rules** after a task produces an `outcome`.

### 3.1 `set_iter`
Writes iteration-local state (preferred for pagination and loop-local progress).

### 3.2 `set_ctx`
Writes execution-scoped state as an event-sourced patch.

If reducers/atomics are not supported yet, the runtime SHOULD reject or restrict `set_ctx` from parallel iterations to avoid races (implementation-defined; MUST be documented).

---

## 4) Reading variables in templates

Canonical access patterns:
- `{{ workload.api_url }}`
- `{{ keychain.openai_token }}`
- `{{ ctx.last_ref }}`
- `{{ iter.endpoint.path }}`
- `{{ args.page_size }}`

Pipeline locals:
- `{{ _prev }}`
- `{{ _task }}`
- `{{ _attempt }}`
- `{{ outcome.status }}`

> If you want a pipeline-local value visible to routing (`step.next.arcs[].when`), write it to `ctx` via `set_ctx` (or pass it forward via `next.arcs[].args` if it is small and deterministic).

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

> If you keep legacy `/api/vars/{execution_id}` endpoints for compatibility, they should be reinterpreted as `ctx` patches (execution-scope).

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

### 7.2 Shared mutation
When `loop.spec.mode: parallel`, multiple step runs/iterations execute concurrently. To avoid races:
- Prefer writing outputs to external storage (db/object/kv) and returning references.
- Promote only stable references/counters into `ctx` using reducers/aggregation steps.
- If reducers are not supported, the runtime MUST reject ambiguous shared writes.

---

## 8) Recommended patterns

### 8.1 Pagination state
Keep cursor/page counters in `iter.*`, updated via `then.set_iter` in task policy rules.

### 8.2 Cross-step handoff
Write a ResultRef into `ctx` (or pass via `next.arcs[].args` if it is small).

### 8.3 Operator approval
External system patches `ctx.approved = true`. Next routing uses `next.arcs[].when` on `ctx.approved`.

---

## Links
- DSL Specification (canonical): `dsl/spec.md`
- Execution Model (canonical): `dsl/execution_model.md`
- Retry Handling (canonical): `retry_mechanism_v2.md`
- Result Storage (canonical): `result_storage_canonical_v10.md`
- Pipeline Execution (canonical): `pipeline_execution_v2.md`
