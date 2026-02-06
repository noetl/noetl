---
sidebar_position: 6
title: Execution Model (Canonical)
description: Event-sourced execution model with control plane and data plane architecture (Petri-net canonical runtime)
---

# NoETL DSL & Event-Sourced Execution Model (Control Plane / Data Plane) — Canonical (Updated)

## Abstract
NoETL is a declarative orchestration system for APIs, databases, scripts, and agentic workflows, built around **event sourcing**: every meaningful state transition is emitted as an immutable event and persisted for replay, observability, and optimization. The same execution model extends to **quantum computation orchestration** (parameter sweeps, job submission, polling, result capture, provenance).

This document specifies the **canonical execution model** aligned with the latest DSL decisions:
- Root playbook sections (`metadata`, `executor`, `workload`, `workflow`, `workbook`)
- Runtime scopes (`workload`, `ctx`, `iter`, pipeline locals)
- **Petri-net semantics** (token → step transition → next arcs)
- Control plane vs data plane responsibilities
- Ordered pipeline execution (`step.tool`)
- Task-level control via **`task.spec.policy.rules`** (no legacy `eval`, no `expr`)
- Loop scheduling (server) with iteration execution (worker)
- Reference-first result storage (no special “sink” kind)

---

## 1) Architecture overview

NoETL follows an event-driven, distributed worker model where **all execution emits structured events** for replay, observability, and optimization.

### 1.1 Components

- **Server (control plane)**
  - API endpoints (start execution, receive events, query executions)
  - Resolves and validates playbooks
  - Persists the append-only **event log**
  - Evaluates **step admission** via `step.spec.policy.admit.rules` (no `step.when`)
  - Evaluates **routing** via `step.next.arcs[].when`
  - Schedules step runs and (optionally distributed) loop iterations
  - Enforces payload/reference policies (max payload bytes, reference-first)

- **Worker pool (data plane)**
  - Pure background worker pool (**no HTTP endpoints**)
  - Claims step-run commands (and/or iteration-run commands) from queue
  - Executes the step pipeline (`step.tool`) deterministically
  - Applies **task policies** (`task.spec.policy.rules`) for retry/jump/break/fail/continue
  - Emits task/step/loop-iteration events back to server

- **Queue / pubsub** (commonly NATS)
  - Distributes run commands to workers
  - May be used for leases/coordination (implementation-defined)

- **Event Log**
  - Append-only event store used for replay and audit
  - Exportable to analytics/observability stores (ClickHouse, OTEL, etc.)

### 1.2 High-level sequence (canonical)

```
Client → Server API: playbook.execution.requested
Server → Event Log: request persisted
Server: validate + resolve + merge workload + init ctx
Server: evaluate start step admission (admit.rules)
Server → Queue: step.run.enqueued (token enters transition)

Worker → Queue: step.run.claimed
Worker → Server: task.* + iteration.* + step.* events (with outcomes / references)
Server → Event Log: persist worker events
Server: evaluate next.arcs routing on terminal boundary events
Server → Queue: enqueue next step.run(s) OR complete workflow
```

---

## 2) Domain model (entities)

### 2.1 Playbook (root structure)
A **Playbook** is the top-level YAML document. **Root sections are limited** to:

- `apiVersion`, `kind`
- `metadata`
- `executor` (optional)
- `workload`
- `workflow`
- `workbook` (optional)

> Root-level `vars` MUST NOT exist.

### 2.2 Workflow
A **Workflow** is a list of steps that form a directed graph via `next` **arcs**.
Conventions:
- entry routing is via admission + explicit arcs (see §7)
- termination occurs when no runnable tokens remain

### 2.3 Step (Petri-net transition)
A **Step** is a Petri-net transition:
- **Admission gate**: `step.spec.policy.admit` (server-side)
- **Firing**: `step.tool` ordered pipeline (worker-side)
- **Outgoing arcs**: `step.next.arcs[]` (server-side routing)

There is **no** `step.when` field in the canonical model.

### 2.4 Tool / Task
A **Task** is a labeled tool invocation in the pipeline.
A **Tool kind** is an execution primitive (`http`, `postgres`, `duckdb`, `python`, `secrets`, etc.).

All runtime knobs are expressed under `task.spec` (with `spec` merge precedence).

### 2.5 Loop
`loop` is a step modifier that repeats the step pipeline over a collection:
- `loop.in`: collection expression
- `loop.iterator`: iterator binding in `iter.<iterator>`
- `loop.spec.mode`: `sequential` (default) or `parallel`
- optional: `loop.spec.policy.exec: distributed|local` (placement intent)

Loop scheduling is **server-owned**; iteration execution is **worker-owned** (see §6).

### 2.6 Next (arcs)
`next` is a routing **router object**:
- `next.spec.mode`: exclusive|inclusive (fan-out control)
- `next.arcs[]`: each arc has `when` guard + `args` inscription payload

---

## 3) Runtime scopes (state model)

NoETL separates immutable input from mutable execution state and local iteration state.

### 3.1 `workload` (immutable)
At execution start, the server builds **MergedWorkload** by merging:
1) playbook `workload` defaults
2) execution request payload overrides

`workload` is then immutable for the execution instance.

### 3.2 `ctx` (execution scope, mutable)
`ctx` is mutable state shared across steps within one execution:
- progress counters
- session state
- references to externally stored results

**Persistence rule:** `ctx` updates MUST be recorded as event-sourced **patches** (not full snapshots).

### 3.3 `iter` (iteration scope, mutable)
If a step has a `loop`, each iteration has isolated `iter` scope:
- `iter.<iterator>` binds current element
- `iter.index`
- `iter.*` holds pagination/streaming state (page, has_more, status codes, etc.)

### 3.4 Nested loops
Canonical addressing uses a parent chain:
- `iter` is current iteration
- `iter.parent` is outer iteration
- `iter.parent.parent` for deeper nesting

### 3.5 Pipeline locals
Within a step pipeline (or within an iteration pipeline):
- `_prev`: previous task output (canonical: previous task’s `outcome.result`)
- `_task`: current task label
- `_attempt`: attempt counter for current task

### 3.6 Read/write guidance (canonical)
- Reads commonly use: token `args` → `ctx` → `iter` → `workload`
- Writes:
  - iteration-local: `set_iter`
  - cross-step: `set_ctx` (restricted for parallel loops until reducers/atomics exist)

---

## 4) Canonical step execution

### 4.1 Canonical step form
A canonical step contains:
- `spec` (step knobs + step policies)
- optional `loop`
- `tool` pipeline (ordered list of labeled tasks)
- `next` router (arcs)

There is **no canonical need** for special step-level constructs like `case`, `retry`, or `sink`:
- retry/pagination/polling = task policy rules
- sink = just a storage tool task that returns a reference

### 4.2 Fan-out mode belongs to `next` (not step spec)
Routing fan-out is controlled by:
- `next.spec.mode: exclusive|inclusive` (default exclusive)

---

## 5) Tool execution and task-level flow control (policy)

### 5.1 Tool `outcome`
Each tool invocation produces exactly one final `outcome` envelope:
- `outcome.status`: `ok|error`
- `outcome.result`: success output (or a reference)
- `outcome.error`: error object with stable fields (`kind`, `retryable`, etc.)
- `outcome.meta`: duration, attempt, trace ids

### 5.2 Tool runtime policy (`task.spec`)
All runtime knobs are under `task.spec`:
- timeouts, pooling, internal retry (optional)
- sandbox/resource hints
- kind-specific knobs

### 5.3 Task policy (`task.spec.policy.rules`) — pipeline control
`task.spec.policy.rules` is an ordered rule list mapping `outcome` to a directive:

- `continue`: advance to next task
- `retry`: rerun current task (bounded attempts, backoff)
- `jump`: jump to another task label (pagination/routing inside pipeline)
- `break`: end the pipeline successfully (iteration done / step done)
- `fail`: end the pipeline with failure (iteration failed / step failed)

Default behavior if task policy omitted:
- ok → continue
- error → fail

Task policy supports scoped writes:
- `set_iter` (iteration-local; preferred in loops)
- `set_ctx` (execution-scoped patch; restricted in parallel loops)

> Note: any legacy `eval`, `expr`, `set_vars`, or step-local `vars` are non-canonical in this model.

---

## 6) Loop semantics (canonical)

### 6.1 Server schedules iterations; worker executes them
If `step.loop` is present:
- **Server** expands the loop into iteration run commands (or a single command with loop plan), respecting `loop.spec.mode` and `max_in_flight`.
- **Worker(s)** execute the step pipeline for each iteration under isolated `iter` scope.

### 6.2 Sequential vs parallel
- `sequential`: process one iteration at a time (stable order)
- `parallel`: process multiple iterations concurrently (bounded by `max_in_flight`)

### 6.3 Parallel safety
In `parallel` mode:
- `set_iter` is always safe (iteration isolated)
- `set_ctx` must be restricted until reducers/atomics exist (implementation must document the chosen rule):
  - write-once per key
  - append-only
  - reject conflicting writes

### 6.4 Loop lifecycle events
Server must persist loop lifecycle boundaries:
- `loop.started`
- `loop.iteration.started`
- `loop.iteration.done` / `loop.iteration.failed`
- `loop.done`

---

## 7) Routing (next router) and token creation

### 7.1 Server routing responsibility
Upon receiving a terminal step event (`step.done`, `step.failed`, or `loop.done`), the server:
1) loads the step definition
2) evaluates `next.arcs[].when` guards
3) applies `next.spec.mode`
4) enqueues zero or more new step-run tokens/commands

### 7.2 Token payload (`next.arcs[].args`)
`next.arcs[].args` is the canonical cross-step payload (Petri-net arc inscription).
It becomes the input `args` available to the downstream step admission and runtime templates.

---

## 8) Event sourcing model

### 8.1 Why event sourcing
- rebuildable state by replay
- deterministic debugging and audit/provenance
- observability exports
- AI-assisted optimization

### 8.2 Minimum event set (recommended)

**Server:**
- `playbook.execution.requested`
- `playbook.request.evaluated`
- `workflow.started`
- `token.enqueued` / `step.scheduled`
- `next.evaluated` / `next.fired`
- `workflow.finished`
- `playbook.processed`

**Worker:**
- `step.started`
- `task.started`
- `task.done` (includes `outcome` or references)
- `step.done` / `step.failed`
- `loop.iteration.*` (when iteration executed)

### 8.3 Reference-first event payloads
Events SHOULD NOT carry large result bodies.
Store bulk results externally and emit references.

---

## 9) Results & storage (reference-first)

### 9.1 Default rule
- Event log contains metadata and references.
- Large payloads go to external storage:
  - Postgres tables
  - object store (S3/GCS)
  - NATS object store (if adopted)
  - vector stores, etc.

### 9.2 “Sink” is a pipeline pattern
A “sink” is simply a storage tool task executed in the pipeline that returns a reference.
No special DSL keyword is required.

---

## 10) Quantum computation orchestration (canonical fit)

Quantum workloads map naturally to:
- loop-driven parameter sweeps (`loop` with `parallel` bounded by capacity)
- tool tasks for submit/poll/fetch (task policy for retry/jump/break)
- provenance via event log and immutable `workload`
- result references stored in external stores and referenced via events/ctx patches

---

## 11) Implementation alignment (repository layout)

Assumptions used by this documentation:
- **Worker (`worker.py`)**: pure background worker pool with no HTTP endpoints
- **Server (`server.py`)**: orchestration + API endpoints
- **CLI (`clictl.py`)**: manages worker pools and server lifecycle

---

## 12) Migration notes (from older docs)

Non-canonical constructs in older docs:
- step-level `retry:` blocks
- step-level `case:` used to execute pipelines
- step-level `sink:` shortcut blocks
- playbook-root `vars:`
- step-local `vars:`
- `step.when`
- legacy `eval:` / `expr:`

Canonical replacements:
- Task-level `task.spec.policy.rules` for retry/jump/break/fail/continue
- Storage as ordinary tool tasks returning references
- Step admission via `step.spec.policy.admit.rules`
- Routing via `next.spec` + `next.arcs[]`
