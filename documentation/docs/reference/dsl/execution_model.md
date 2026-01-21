---
sidebar_position: 6
title: Execution Model
description: Event-sourced execution model with control plane and data plane architecture
---

# NoETL DSL & Event-Sourced Execution Model (Control Plane / Data Plane)

## Abstract
NoETL is a declarative orchestration system for APIs, databases, scripts, and agentic workflows, built around **event sourcing**: every meaningful state transition is emitted as an immutable event and persisted for replay, observability, and AI/optimization. The same model extends naturally to **quantum computation orchestration** (parameter sweeps, job submission, polling, result capture, provenance).

This document specifies:
- The **NoETL DSL** (Playbook → Workflow → Step → Tool)
- The **control plane vs data plane** split (server orchestration vs worker execution)
- The **event model** and state reconstruction rules
- Semantics of **loop**, **retry**, **sink**, **case**, and **next**
- Quantum-oriented execution patterns

---

## 1) Architecture overview
NoETL follows an event-driven, distributed worker model where all execution emits structured events for observability. ([noetl.dev](https://noetl.dev/?utm_source=chatgpt.com))

### 1.1 Components
- **Server (control plane)**
  - API endpoints (start execution, receive events, query variables/results)
  - Validates playbooks and dependencies
  - Maintains execution state by **replaying events**
  - Issues work **commands** to the queue
  - Decides routing (`next`, `case`) and fan-out/fan-in (`loop`)

- **Worker pool (data plane)**
  - Claims commands from the queue
  - Executes tools (http/python/postgres/duckdb/workbook/etc.)
  - Performs local side effects (e.g., `sink`)
  - Reports results back to server as events

- **Queue / pubsub** (commonly NATS)
  - Distributes commands to workers
  - Can store loop snapshots / state

- **Event Log**
  - Append-only event store used for replay
  - Exportable to observability stores (e.g., ClickHouse)

### 1.2 High-level sequence
```
Client → Server API: PlaybookExecutionRequested
Server → Event Log: request received
Server: validate + resolve playbook + build workload/context
Server → Queue: command.issued (start step)
Worker → Queue: command.claimed
Worker: execute tool (+ retry/pagination) + optional sink
Worker → Server API: step.enter/call.done/step.exit (+ sink.*)
Server → Event Log: persist events
Server: evaluate routing (case/next), loop progress, retry re-issue
Server → Queue: next command(s) or workflow completion
```

---

## 2) Domain model (entities)

### 2.1 Playbook
A **Playbook** is the top-level document that defines workload inputs, a workbook library, and a workflow (step graph). The DSL is a YAML/JSON document validated against a schema; steps coordinate execution using `tool`, `loop`, `vars`, `case`, and `next`. ([noetl.dev](https://noetl.dev/docs/reference/dsl/spec))

### 2.2 Workflow
A **Workflow** is the ordered (or graph-like) set of steps. A conventional entry point is step named `start`, and a conventional terminal step is `end`. ([noetl.dev](https://noetl.dev/docs/reference/dsl/spec))

### 2.3 Step
A **Step** is a coordinator that may:
- Execute a **Tool** (`tool:`)
- Repeat execution over a collection (`loop:`)
- Persist derived values (`vars:`)
- Route conditionally (`case:`)
- Route by default (`next:`)

This “step widget” structure is the core unit of orchestration. ([noetl.dev](https://noetl.dev/docs/reference/dsl/spec))

### 2.4 Tool
A **Tool** is the execution primitive. Common tool kinds include `workbook`, `python`, `http`, `postgres`, `duckdb`, `playbook`, `secrets`, etc. ([noetl.dev](https://noetl.dev/docs/reference/dsl/spec))

### 2.5 Loop
`loop:` is a **step-level attribute (not a tool kind)** that modifies how the step executes. It iterates over `in:` using an `iterator:` variable, with a selectable execution mode. Loop state is managed via NATS KV snapshots. ([noetl.dev](https://noetl.dev/docs/features/iterator))

### 2.6 Case
`case:` provides **event-driven conditional routing**. It evaluates conditions (`when:`) against runtime state (event, response/error, variables, workload, etc.) and applies actions in `then:` (e.g., `next`, `sink`, `set`). ([noetl.dev](https://noetl.dev/docs/reference/dsl/spec))

### 2.7 Next
`next:` is the **default routing** when no `case` rule intercepts. It can be a single step or list of steps (and may carry `args` per edge). ([noetl.dev](https://noetl.dev/docs/reference/dsl/spec))

### 2.8 Context
“Context” is the runtime evaluation environment for templates and tools:
- `workload.*` (global inputs)
- `vars.*` (persisted transient variables)
- prior step results (namespaced by step)
- loop iterator variables (e.g., `city`, `current_item`)

### 2.9 Workload
Workload is the playbook’s “input surface.” At execution start:
1) the playbook’s workload block is evaluated
2) it is merged with the **execution request payload**
3) the merged object becomes `workload` in template context

### 2.10 Variable
Variables are derived and persisted values (often from `vars:` blocks) stored in a transient store and referenced as `{{ vars.name }}` in later steps. The design includes a dedicated transient table and REST API access patterns. ([noetl.dev](https://noetl.dev/docs/reference/dsl/spec))

### 2.11 Workbook
A workbook is a library of reusable tasks that can be invoked via a `workbook` tool kind. ([noetl.dev](https://noetl.dev/docs/reference/dsl/spec))

---

## 3) DSL specification (practical schema)

### 3.1 Playbook structure
Typical top-level blocks:
- `apiVersion`, `kind`
- `metadata` (name/path/version/description)
- `workload` (inputs; merged with run payload)
- `keychain` (auth material references)
- `workbook` (reusable named tasks)
- `workflow` (steps)

### 3.2 Step structure
A step can contain:
- `tool:` (required except conventional `start`/`end`) ([noetl.dev](https://noetl.dev/docs/reference/dsl/spec))
- `loop:`: `{ in, iterator, mode }` ([noetl.dev](https://noetl.dev/docs/features/iterator))
- `vars:`: variable extraction/persistence ([noetl.dev](https://noetl.dev/docs/reference/dsl/variables_feature_design))
- `retry:`: unified retry/pagination/polling with optional per-iteration sink ([noetl.dev](https://noetl.dev/docs/reference/dsl/unified_retry))
- `case:`: conditional actions triggered by events ([noetl.dev](https://noetl.dev/docs/reference/dsl/spec))
- `next:`: default routing ([noetl.dev](https://noetl.dev/docs/reference/dsl/spec))

---

## 4) Event sourcing model

### 4.1 Why event sourcing here
NoETL treats execution as a stream of immutable facts:
- **Rebuildable state**: execution state is derived by replay
- **Deterministic debugging**: “what happened?” becomes a query
- **Audit/provenance**: critical for regulated workloads and quantum experiments
- **Observability**: events can be exported to ClickHouse/OpenTelemetry

### 4.2 Event log schema
A typical event store record includes:
- `event_id` (unique)
- `execution_id`
- `event_type` / `event_name`
- `status` (STARTED/COMPLETED/FAILED)
- `step_name` (optional)
- `payload` (JSON)
- timestamps, duration, error message

In ClickHouse, `observability.noetl_events` is designed to index by EventId/ExecutionId/EventType/Status, and includes step and duration/error fields. ([noetl.dev](https://noetl.dev/docs/reference/clickhouse_observability?utm_source=chatgpt.com))

### 4.3 Canonical event taxonomy (recommended)
Your list maps cleanly into a stable naming scheme:

**Execution lifecycle**
- `playbook.execution.requested` (PlaybookExecutionRequested)
- `playbook.request.evaluated` (PlaybookRequestEvaluated)
- `workflow.started` / `workflow.finished`
- `playbook.paused` / `playbook.processed`

**Step & tool**
- `step.started` / `step.finished`
- `tool.started` / `tool.finished`

**Loop**
- `loop.started` / `loop.iteration.started` / `loop.iteration.finished` / `loop.finished`

**Case & routing**
- `case.started` / `case.evaluated`
- `next.evaluated`

**Retry**
- `retry.started` / `retry.processed`

**Sink**
- `sink.started` / `sink.processed`

### 4.4 What’s *derived* vs *stored*
- Stored: events only (facts)
- Derived: current step, pending commands, loop progress, retry attempt counters

---

## 5) Control plane vs data plane responsibilities

### 5.1 Server (control plane)
The server is responsible for:
1) **Accept execution request** and append `playbook.execution.requested`
2) **Validate** playbook, referenced workbook tasks, secrets, and tools
3) **Build initial workload/context** (workload merge + template evaluation)
4) **Choose entry step** (convention: `start`) and issue initial command(s)
5) **Persist all incoming worker events** to the event log
6) **Rebuild execution state** by replay
7) **Decide orchestration**:
   - Evaluate `case` rules that cause routing
   - Follow `next` edges
   - Expand `loop` (fan-out), detect completion (fan-in)
   - Re-issue commands for `retry` (or delegate policy to worker for tool-level pagination)

### 5.2 Worker (data plane)
Workers are responsible for:
1) **Claim command** (idempotent claim)
2) **Render templates** with provided context/vars
3) **Execute tool** (http/python/postgres/duckdb/workbook/etc.)
4) **Apply unified retry** for tool-level retries, pagination, and polling
5) **Execute sink/side effects** when instructed (often per iteration)
6) **Report** step/tool/sink outcomes back to server as events

> Key rule: the worker *executes*; the server *decides the graph*.

---

## 6) Loop semantics

### 6.1 DSL
Loop is declared at step level:
```yaml
- step: process_items
  tool: { kind: python, ... }
  loop:
    in: "{{ workload.items }}"
    iterator: current_item
    mode: sequential   # or parallel
```
([noetl.dev](https://noetl.dev/docs/features/iterator))

### 6.2 Execution semantics
- Server evaluates `loop.in` into a collection.
- Server creates a loop-instance state object (stored in NATS KV snapshots). ([noetl.dev](https://noetl.dev/docs/features/iterator))
- For each element, server issues a command with:
  - iterator variable bound (e.g., `current_item`)
  - loop index/counters
  - step/tool config

**Sequential mode**
- Issue next item only after current iteration completes

**Parallel mode**
- Issue N commands concurrently
- Fan-in occurs when all iterations report completion

### 6.3 Loop + sink
A canonical pattern is to sink per iteration using a `case` rule triggered on step completion:
```yaml
case:
  - when: "{{ event.name == 'step.exit' and response is defined }}"
    then:
      sink:
        tool:
          kind: postgres
          auth: "{{ workload.pg_auth }}"
          table: processed_records
```
([noetl.dev](https://noetl.dev/docs/features/iterator))

### 6.4 Nested loops
NoETL encourages nested iteration by composing steps (outer loop step writes vars, inner loop step loops over vars): ([noetl.dev](https://noetl.dev/docs/features/iterator))

---

## 7) Unified retry semantics
The unified retry system expresses **error retry** + **success retry** (pagination/polling) declaratively and works across tools. It also supports per-iteration sinks and collection strategies. ([noetl.dev](https://noetl.dev/docs/reference/dsl/unified_retry))

### 7.1 Pagination / polling pattern
- `when:` decides whether to continue
- `next_call:` mutates request inputs (params/url/args)
- `collect:` defines merge strategy (append/replace) and optional target var
- Optional: `per_iteration.sink` for writing each page/iteration immediately ([noetl.dev](https://noetl.dev/docs/reference/dsl/unified_retry))

### 7.2 Loop integration
Retry composes with `loop` for “loop over endpoints, paginate each endpoint.” ([noetl.dev](https://noetl.dev/docs/reference/dsl/unified_retry))

---

## 8) Variables (`vars:`) semantics

### 8.1 DSL behavior
The `vars` block extracts values from the **current step result** after execution and persists them:
- Accessible later via `{{ vars.name }}`
- Stored in a transient table with metadata
- Readable via REST API endpoints (`GET /api/vars/{execution_id}` etc.) ([noetl.dev](https://noetl.dev/docs/reference/dsl/variables_feature_design))

### 8.2 Template namespaces (practical)
- `workload.*` — merged execution inputs
- `vars.*` — persisted derived values
- `result` — current step result in the `vars:` block ([noetl.dev](https://noetl.dev/docs/reference/dsl/variables_feature_design))

---

## 9) `case`, `next`, and `sink` semantics

### 9.1 `next:` as default routing
`next` is the baseline edge list—where execution goes when no higher-priority rule intercepts. ([noetl.dev](https://noetl.dev/docs/reference/dsl/spec))

### 9.2 `case:` as event-driven routing + side effects
`case` enables conditional logic tied to execution events (e.g., step exit, tool error). A `case` rule contains:
- `when:` a Jinja2 condition evaluated against runtime state ([noetl.dev](https://noetl.dev/docs/reference/dsl/spec))
- `then:` actions:
  - `next:` route to step(s)
  - `sink:` persist data
  - `set:` set ephemeral values

### 9.3 `sink:` as a shortcut
In practice, `sink` is often “case-on-step-exit” with a well-known pattern (see Loop + sink example). ([noetl.dev](https://noetl.dev/docs/features/iterator))

### 9.4 Where evaluation happens
- **Server-side decisions** (routing/graph changes): `case.then.next`, default `next`, loop scheduling, workflow completion
- **Worker-side side effects**: `sink` execution, tool execution, retry/pagination/polling

---

## 10) Quantum computation orchestration: how NoETL fits

Quantum workloads look like distributed API-driven workflows with strict provenance. NoETL’s model fits naturally:

### 10.1 Tool mapping
- `http` → vendor/job APIs (submit, status, fetch results)
- `python` → circuit generation, compilation, post-processing
- `postgres/duckdb` → metadata, metrics, experiment tables
- `secrets` → QPU credentials / tokens
- `workbook` → reusable “submit_job”, “poll_job”, “decode_results” tasks

### 10.2 Core patterns
**A) Parameter sweep (fan-out loop)**
- `loop.in` over parameter grid (angles, noise models, backends)
- `mode: parallel` for throughput, bounded by worker pool

**B) Async job polling (unified retry)**
- submit returns `job_id` → store in `vars`
- `retry` polls status until complete, with bounded attempts

**C) Provenance (event log + vars)**
Record in events and/or vars:
- circuit hash, compiler version, backend, shot count, seed
- timestamps (submit/start/finish), error class, retry counters

**D) Result sinks**
- per-iteration sink to store each experiment result immediately
- store large payloads out-of-band (object store), sink pointers + metadata

### 10.3 Quantum-specific conformance recommendations
- **Idempotency**: submission step must be safe to retry (e.g., deterministic client token) or guarded by `vars.job_id` existence.
- **Determinism**: embed versioned toolchain metadata in events.
- **Resource-aware pools**: tag worker pools by backend type (simulator vs QPU) and route commands accordingly.

---

## 11) Implementation notes (aligning names with the codebase)
To keep the mental model crisp:
- **Server** is the **control plane** module: orchestration + API endpoints.
- **Worker** is the **data plane** module: background worker pool, no HTTP API.
- **CLI** manages lifecycle of server + worker pools.

---

## 12) Appendix: quick examples

### A) Loop + sink (per item)
```yaml
- step: process_and_save
  tool:
    kind: python
    args:
      record: "{{ current_record }}"
    code: |
      result = {"processed_id": record["id"], "status": "complete"}
  loop:
    in: "{{ workload.records }}"
    iterator: current_record
    mode: parallel
  case:
    - when: "{{ event.name == 'step.exit' and response is defined }}"
      then:
        sink:
          tool:
            kind: postgres
            auth: "{{ workload.pg_auth }}"
            table: processed_records
  next:
    - step: end
```
([noetl.dev](https://noetl.dev/docs/features/iterator))

### B) Pagination + per-page sink
```yaml
retry:
  - when: "{{ response.data.nextCursor is not none }}"
    then:
      max_attempts: 100
      next_call:
        params:
          cursor: "{{ response.data.nextCursor }}"
      collect:
        strategy: append
        path: data.results
      per_iteration:
        sink:
          tool:
            kind: postgres
            auth: pg_k8s
            table: raw_data
            mode: insert
```
([noetl.dev](https://noetl.dev/docs/reference/dsl/unified_retry))

