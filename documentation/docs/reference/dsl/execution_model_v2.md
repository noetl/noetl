---
sidebar_position: 6
title: Execution Model (Canonical)
description: Event-sourced execution model with control plane and data plane architecture (Petri-net canonical runtime)
---

# NoETL DSL & Event-Sourced Execution Model (Control Plane / Data Plane) — Canonical

## Abstract
NoETL is a declarative orchestration system for APIs, databases, scripts, and agentic workflows, built around **event sourcing**: every meaningful state transition is emitted as an immutable event and persisted for replay, observability, and AI/optimization. The same execution model extends naturally to **quantum computation orchestration** (parameter sweeps, job submission, polling, result capture, provenance).

This document specifies the **canonical** execution model:
- Playbook root sections and runtime scopes (`workload`, `ctx`, `vars`, `iter`)
- **Petri-net semantics** (token → step transition → next arcs)
- Control plane vs data plane responsibilities
- Pipeline execution (`step.tool`) and tool-level flow control (`eval: expr`)
- Loop execution and parallel safety rules
- Reference-first result storage

> This document is aligned with:
> - `dsl_specification_v2.md`
> - `formal_specification_v2.md`
> - `noetl_canonical_step_spec_v2.md`

---

## 1) Architecture overview

NoETL follows an event-driven, distributed worker model where **all execution emits structured events** for replay, observability, and optimization.

### 1.1 Components

- **Server (control plane)**
  - API endpoints (start execution, receive events, query executions)
  - Resolves and validates playbooks
  - Persists the append-only **event log**
  - Routes execution by evaluating `step.when` and `next[].when`
  - Enqueues step-run commands to worker pools

- **Worker pool (data plane)**
  - Pure background worker pool (**no HTTP endpoints**)
  - Claims step-run commands from queue
  - Executes the step pipeline (`step.tool`) deterministically
  - Evaluates tool-level `eval` rules (retry/jump/break/fail/continue)
  - Emits tool/task/loop/step terminal events back to server

- **Queue / pubsub** (commonly NATS)
  - Distributes step-run commands to workers
  - May be used for lightweight coordination/leases (implementation-defined)

- **Event Log**
  - Append-only event store used for replay
  - Exportable to analytical / observability stores (ClickHouse, OTEL, etc.)

### 1.2 High-level sequence (canonical)

```
Client → Server API: playbook.execution.requested
Server → Event Log: request persisted
Server: validate + resolve + merge workload + init ctx
Server → Queue: step.run.enqueued (start step)

Worker → Queue: step.run.claimed
Worker: step.started
Worker: execute step.tool pipeline (task.started/task.processed)
Worker: loop.* events (if loop present)
Worker: step.done/step.failed/loop.done
Worker → Server API: events pushed

Server → Event Log: persist worker events
Server: evaluate next[] arcs (spec.next_mode) from terminal event
Server → Queue: enqueue next step.run(s) or complete workflow
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

> `vars` MUST NOT exist at playbook root. Runtime variable scopes are `ctx`, `vars`, and `iter` (see §3).

### 2.2 Workflow
A **Workflow** is a list of steps that form a directed graph via `next[]` arcs.
Conventions:
- entry step: `start` (recommended)
- terminal: when no runnable tokens remain (or `end` step by convention)

### 2.3 Step (Petri-net transition)
A **Step** is a Petri-net transition:
- `when`: transition enable guard (server-side)
- `tool`: transition firing (worker-side pipeline)
- `next`: outgoing arcs (server-side routing)

### 2.4 Tool (execution primitive)
A **Tool** is a task kind executed by workers (e.g., `http`, `postgres`, `duckdb`, `python`, `secrets`, `playbook`).
Tool runtime knobs/policy are expressed under `tool.spec`.

### 2.5 Loop
`loop` is a step modifier that repeats the step pipeline over a collection:
- `loop.in`: collection expression
- `loop.iterator`: iterator binding in `iter.<iterator>`
- `loop.spec.mode`: `sequential` (default) or `parallel`

Loop execution is handled by the **worker** in the canonical model (see §6).

### 2.6 Next (arcs)
`next[]` is the explicit routing list. Each arc can have:
- `when` guard (server-side)
- `args` inscription payload (token input to target step)
- optional `spec` for future edge semantics

---

## 3) Runtime scopes (state model)

NoETL separates immutable input from mutable execution state and local runtime state.

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

**Persistence rule:** updates MUST be recorded as event-sourced **patches** (not full snapshots).

### 3.3 `vars` (step scope, mutable)
`vars` is mutable state local to a **single step run** (one token consumption).
Use it for transient step-local values needed for `next[].when` decisions.

### 3.4 `iter` (iteration scope, mutable)
If a step has a `loop`, each iteration has isolated `iter` scope:
- `iter.<iterator>` binds current element
- `iter.index`
- `iter.*` holds pagination state (page, has_more, etc.)

### 3.5 Pipeline locals
Within a step pipeline:
- `_prev`: previous task output
- `_task`: current task label
- `_attempt`: attempt counter for current task

### 3.6 Precedence recommendation
Reads: `args` → `ctx` → `workload`  
Writes: per-iteration → `iter`; per-step → `vars`; cross-step → `ctx`

---

## 4) Canonical step execution

### 4.1 Canonical step form
A canonical step is:

- `spec` (semantics; e.g., `next_mode`)
- `when` guard
- optional `loop`
- `tool` pipeline (ordered list)
- `next` arcs

There is **no canonical need** for `case`, `retry`, or `sink` as special step-level constructs.
Instead:
- retry/pagination/polling = tool-level `eval`
- sink = just a storage tool task in the pipeline that returns references

### 4.2 `spec.next_mode` (routing fan-out)
`step.spec.next_mode` controls `next[]` arc firing:
- `exclusive` (default): first matching arc (ordered)
- `inclusive`: all matching arcs (fan-out)

---

## 5) Tool execution and tool-level flow control (`eval`)

### 5.1 Tool `outcome`
Each tool invocation produces exactly one final `outcome` envelope:
- `outcome.status`: `success|error`
- `outcome.result`: success output
- `outcome.error`: error object
- `outcome.meta`: duration, attempt, trace ids

### 5.2 Tool runtime policy (`tool.spec`)
All runtime knobs are under `tool.spec`:
- timeouts, pooling, internal retry policy
- sandbox/resource hints
- kind-specific knobs

### 5.3 Tool-level `eval` (pipeline control)
`eval` is an ordered list of rules mapping `outcome` to a directive:

- `continue`: advance to next task
- `retry`: rerun current task (bounded attempts, backoff)
- `jump`: change program counter to another task label (pagination)
- `break`: end step successfully early
- `fail`: end step with failure

Default behavior if `eval` omitted:
- success → continue
- error → fail

`eval` also supports scoped writes:
- `set_iter` (iteration-local; preferred in loops)
- `set_vars` (step-local)
- `set_ctx` (execution-scoped patch)
- `set_shared` (explicit shared write; optional reducers/atomics)

---

## 6) Loop semantics (canonical)

### 6.1 Loop is executed by the worker
If `step.loop` is present, the worker executes the step pipeline once per element of the loop collection.

- In `sequential` mode: one iteration at a time
- In `parallel` mode: multiple iterations concurrently (bounded by `loop.spec.max_in_flight`)

The worker MUST emit loop lifecycle events:
- `loop.started`
- `loop.iteration.started`
- `loop.iteration.done`
- `loop.done`

### 6.2 Parallel safety
In `parallel` mode:
- `set_iter` is always safe (iteration isolated)
- Writes to shared `vars` require explicit intent (`set_shared`) OR must be deterministically mapped to iteration scope (implementation choice must be documented)

---

## 7) Routing (`next[]`) and token creation

### 7.1 Server routing responsibility
Upon receiving a terminal step event (`step.done`, `step.failed`, or `loop.done`), the server:
1) loads step definition
2) evaluates `next[].when` guards
3) applies `step.spec.next_mode`
4) enqueues zero or more new tokens/step-run commands

### 7.2 Token payload (`next[].args`)
`next[].args` is the canonical cross-step payload (Petri-net arc inscription).
It is evaluated at routing time and becomes `args` for the downstream step.

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
- `step.scheduled`
- `next.evaluated`
- `workflow.finished`
- `playbook.processed`

**Worker:**
- `step.started`
- `task.started`
- `task.processed` (includes `outcome`)
- `step.done` / `step.failed`
- `loop.*` (if applicable)

### 8.3 Reference-first event payloads
Events SHOULD NOT carry large result bodies. Store bulk results externally and emit references.

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

Quantum workloads are naturally modeled as:
- loop-driven parameter sweeps (`loop` with `parallel` bounded by capacity)
- tool tasks for submit/poll/fetch (`eval` for retry/jump)
- provenance via event log and immutable `workload`
- result references stored via `ctx` patches

---

## 11) Implementation alignment (repository layout)

Assumptions used by this documentation:
- **Worker (`worker.py`)**: pure background worker pool with no HTTP endpoints
- **Server (`server.py`)**: orchestration + API endpoints
- **CLI (`clictl.py`)**: manages worker pools and server lifecycle

---

## 12) Migration notes (from older docs)
The following constructs are **non-canonical** for this baseline:
- step-level `retry:` blocks
- step-level `case:` used to execute pipelines
- step-level `sink:` shortcut blocks
- playbook-root `vars:`

They can be mapped to canonical form via:
- tool-level `eval` (`retry/jump/break/fail`)
- explicit storage tool tasks in `step.tool`
- `ctx` patches for cross-step state

