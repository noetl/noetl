---
sidebar_position: 8
title: Formal Specification (Extended)
description: Extended formal specification with detailed semantics
---

# NoETL Playbook DSL — Formal Specification (Extended)

> Scope: This document defines the **formal (normative) semantics** of the NoETL Playbook DSL and its **event-sourced execution model**, including **loop**, **retry**, **sink**, **case**, **next**, variable persistence (**vars**), and the **control‑plane vs data‑plane** responsibility split.
>
> Versioning: the DSL is versioned via `apiVersion`. The current version is `apiVersion: noetl.io/v2`. All playbooks MUST use v2 syntax.

---

## 1. Conformance and terminology

The key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are to be interpreted as normative requirements.

**Entities (normative):**

- **Playbook**: a YAML document describing workload inputs and a workflow of steps.
- **Workflow**: an ordered list of **Step** objects.
- **Step**: a single unit of orchestration that may invoke a **Tool**, iterate with **Loop**, apply **Retry**, execute **Sink**, route via **Next**, and react to events via **Case**.
- **Tool**: an executable adapter (HTTP, Postgres, DuckDB, Python, nested playbook, workbook task reference, secrets lookup, etc.).
- **Workload**: the initial parameter set, derived from request payload merged with playbook defaults.
- **Context**: the runtime evaluation environment passed through execution (includes workload, vars, step results, loop iterator variables, retry state, etc.).
- **Vars**: execution-scoped variables persisted for the duration of an execution.

**Architecture roles (normative):**

- **Server (control plane)**: provides the API surface, orchestration coordination, and authoritative event log persistence.
- **Worker (data plane)**: background execution pool, no HTTP endpoints; executes tool invocations and reports events back to the server.
- **CLI**: manages server/worker lifecycle and worker pools.

---

## 2. Document model

### 2.1 YAML document

A playbook is a YAML mapping with (at minimum):

- `apiVersion`: string
- `kind`: string (`Playbook`)
- `name`: string
- `path`: string
- `workload`: mapping (optional)
- `workflow`: list of steps
- `workbook`: mapping of named tasks (optional)

### 2.2 Step model

A step is a mapping containing:

- `step`: **required** string identifier
- `desc`: optional string
- `args`: optional mapping (templated)
- `tool`: optional tool block
- `loop`: optional loop block
- `retry`: optional retry policy/policies
- `vars`: optional vars extraction mapping
- `case`: optional list of event rules
- `sink`: optional sink shortcut
- `next`: optional next shortcut

A step **MUST** have at least one of: `tool`, `next`, `case`.

### 2.3 Tool model

A tool is a mapping containing:

- `kind`: string
- tool-specific configuration keys

Tool `kind` values are implementation-defined, but the public reference includes:

- `workbook`, `python`, `http`, `postgres`, `duckdb`, `secrets`, `playbook`

(Implementations MAY add additional kinds, e.g. `quantum`.)

---

## 3. Template evaluation model

### 3.1 Template language

All template expressions are **Jinja2** templates embedded as YAML strings.

### 3.2 Namespaces

The evaluation context is a single dictionary with conventional namespaces:

- `workload`: merged workload
- `vars`: persisted execution variables
- `execution_id`: unique execution identifier
- per-step results by step name
- `event`, `response`, `result`, `this` depending on evaluation location
- loop iterator variable (named by `loop.iterator`)
- reserved retry variable `_retry`

### 3.3 `response` vs `result` (normative)

Because NoETL evaluates templates in different contexts, the following is normative:

- In **`case.when` event conditions**, templates use `event` and `response`.
- In **`case.then` action blocks** (e.g., `sink`, `set`), templates use `result` (unwrapped) and `this` (full envelope).
- In **retry condition evaluation**, the retry evaluator exposes raw fields such as `status_code` and `error`.

---

## 4. Execution model (control plane vs worker)

### 4.1 Execution request

When a playbook execution request is received by the server API, the system:

1. Creates an execution record (logical) and persists `PlaybookExecutionRequested` to the event log.
2. Loads the referenced playbook (by `playbook_id` or `path+version`).
3. Validates the playbook structure and dependency references.
4. Emits `PlaybookRequestEvaluated`.
5. Merges request payload with `workload` defaults → produces **MergedWorkload**.
6. Builds initial execution context from MergedWorkload.
7. Locates the `start` step and begins workflow evaluation.

### 4.2 Step dispatch

The server is the authoritative scheduler of **which step runs next**. The server MAY delegate some local decisions to the worker (see §7), but it MUST persist the authoritative decision and resulting transition as events.

A step dispatch yields:

- A **worker command** (execute tool, execute sink, evaluate retry loop) OR
- A **server-side transition** (pure routing or pause).

### 4.3 Completion

The workflow completes when there is no `next` transition from the current active step(s), or a step routes to an `end` step (convention). On completion, the server emits `WorkflowFinished` and `PlaybookProcessed`.

---

## 5. Loop semantics

### 5.1 Loop is step-level

`loop` is a **step-level attribute** that modifies step execution; it is not a tool kind.

### 5.2 Loop block

Loop block:

```yaml
loop:
  in: "{{ workload.items }}"   # expression or array
  iterator: current_item        # variable name bound per iteration
  mode: sequential | parallel   # optional (default sequential)
```

Semantics:

- The loop collection is computed by evaluating `loop.in`.
- For each element of the collection, a new **iteration scope** is created.
- The iterator variable name (`loop.iterator`) is bound to the current element in that scope.

### 5.3 State and resumability

Loop state MAY be persisted so that partial progress can resume after interruptions. Implementations may use a distributed KV (e.g., NATS KV snapshots) for iterator snapshots.

### 5.4 Loop + case/sink

When looping, **events** occur per iteration. `case` conditions may fire on `step.exit` or `call.done` and can trigger per-iteration sinks.

---

## 6. Retry semantics

NoETL defines a **unified retry** mechanism used both for **error retries** and **success-driven repetition** (pagination/polling/streaming). Retry is evaluated as an ordered list of policies; the first matching policy wins.

### 6.1 Retry structure

Recommended form:

```yaml
retry:
  - when: "{{ error.status in [429, 500, 502, 503] }}"
    then:
      max_attempts: 5
      initial_delay: 1.0
      backoff_multiplier: 2.0

  - when: "{{ response.data.has_more }}"
    then:
      max_attempts: 100
      next_call:
        params:
          page: "{{ (response.data.page | int) + 1 }}"
      collect:
        strategy: append
        path: data.items
        into: pages
      sink:                # optional per-iteration side effect
        tool: { kind: postgres, auth: pg_creds, table: raw_events }
        args: { page: "{{ page.data }}", iter: "{{ _retry.index }}" }
```

### 6.2 Retry evaluation algorithm (normative)

Given a step invocation:

1. Execute tool call.
2. Produce `response` (on success) or `error` (on failure).
3. Evaluate retry policies in order:
   - For each policy, evaluate `when`.
   - The first policy whose `when` is truthy is selected.
4. If no policy matches → the step finishes.
5. If a policy matches:
   - Apply `then.max_attempts` and backoff settings.
   - If `then.next_call` is present, compute the next invocation input.
   - If `then.collect` is present, aggregate results into `then.collect.into`.
   - If `then.sink` is present, execute sink per iteration.
6. Repeat until `max_attempts` reached or policy no longer matches.

### 6.3 Reserved retry variables

Implementations MUST provide `_retry.index` (1-based current iteration) and `_retry.count` (total executed).

---

## 7. Case, Next, Sink semantics

### 7.1 Case

`case` is an ordered list of rules:

```yaml
case:
  - when: "{{ event.name == 'call.done' and response.status_code == 200 }}"
    then:
      sink: ...
      set:  ...
      next:
        - step: success_handler

  - when: "{{ event.name == 'call.error' }}"
    then:
      next:
        - step: error_handler
```

**Semantics:**

- Each rule is evaluated in order against the current `event` and evaluation context.
- The first matching rule executes its `then` actions.
- `then` may include `sink`, `set`, `retry`, and `next`.

### 7.2 Next shortcut

`next` at step level provides unconditional routing when no `case` rule matches.

`next` MAY be:

- a string step name
- a list of step references with optional `args`

**V2 Restriction:** In v2, `next` MUST NOT contain `when` or `then` clauses. Conditional routing MUST use `case`.

### 7.3 Sink shortcut

`sink` at step level is syntactic sugar for a common case action: “on success, persist result”.

Sink executes a tool (often database insert/upsert) with arguments computed from step results.

---

## 8. Vars persistence semantics

### 8.1 Vars block

The `vars` block on a step extracts values from the **current step result after completion**.

Example:

```yaml
- step: fetch_user
  tool:
    kind: postgres
    query: "SELECT user_id, email FROM users LIMIT 1"
  vars:
    user_id: "{{ result[0].user_id }}"
    user_email: "{{ result[0].email }}"
```

### 8.2 Persistence and access

- Vars are **execution-scoped** and persisted in a transient store (e.g., `noetl.transient`).
- The **server** is responsible for writing vars (post-step processing).
- The **worker** MUST access vars through server API endpoints, not direct database connections.

---

## 9. Event sourcing model

### 9.1 Event envelope (normative)

Every observable state transition MUST be recorded as an event with (at minimum):

- `event_id`: unique identifier
- `execution_id`: execution scope identifier
- `timestamp`: RFC3339 timestamp
- `source`: `server` | `worker`
- `name`: event name
- `entity`: `playbook` | `workflow` | `step` | `tool` | `loop` | `retry` | `sink`
- `entity_id`: identifier for the entity instance (e.g., step name, tool call id)
- `status`: `in_progress` | `success` | `error` | `paused`
- `data`: JSON payload (inputs/outputs/errors/metadata)

### 9.2 Canonical event names

This spec defines a canonical taxonomy (implementations may add additional names):

**Control-plane events (server-authored):**

- `PlaybookExecutionRequested`
- `PlaybookRequestEvaluated`
- `WorkflowStarted`
- `StepStarted`
- `NextEvaluated`
- `WorkflowFinished`
- `PlaybookPaused`
- `PlaybookProcessed`

**Data-plane events (worker-authored):**

- `ToolStarted`
- `ToolCompleted` / `ToolErrored`
- `LoopStarted` / `LoopIterationStarted` / `LoopIterationCompleted`
- `RetryStarted` / `RetryProcessed`
- `SinkStarted` / `SinkProcessed`
- `CaseStarted` / `CaseEvaluated`

**Event aliases used in playbook conditions:**

For compatibility with existing DSL conditions, implementations SHOULD also emit (or map) internal names such as:

- `call.done`, `call.error`
- `step.exit` (and optionally `step.enter`)

### 9.3 Idempotency

Event persistence MUST be idempotent with respect to `(execution_id, event_id)`.

### 9.4 Replay

An implementation MUST be able to reconstruct the execution state (at least: current step(s), vars, retry/loop position, and completed results) from the event stream plus transient state snapshots.

---

## 10. Control-plane vs data-plane decision boundaries

### 10.1 Server responsibilities (normative)

The server MUST:

- Accept execution requests and validate playbooks
- Maintain authoritative workflow progression
- Persist the event log (append-only)
- Persist vars (`vars` block processing)
- Decide transitions that require global coordination (fan-out/fan-in, pause/resume, concurrency limits across pools)
- Provide REST endpoints for vars and execution introspection

### 10.2 Worker responsibilities (normative)

The worker MUST:

- Execute tool calls and return normalized envelopes
- Apply retry policies for a tool invocation, including pagination/polling loops
- Execute per-iteration sinks when configured inside retry/loop
- Emit detailed execution events back to the server

The worker MUST NOT require inbound HTTP endpoints.

### 10.3 Case evaluation placement (recommended)

- **Worker-side case** is recommended for decisions that depend only on the local tool response and step-local context (e.g., routing to error handler based on HTTP status).
- **Server-side case** is recommended when routing requires global orchestration concerns (e.g., distributing work across pools, pausing workflows, or coordinating fan-in joins).

Implementations MAY choose a hybrid approach, but MUST ensure the **server** persists the authoritative outcome as events.

---

## 11. Quantum orchestration profile (informative)

NoETL is suitable for quantum workflow orchestration because the DSL primitives map naturally to:

- **Submission** of quantum jobs (tool call)
- **Polling** for job completion (success-side retry)
- **Parameter sweeps** (loop over parameter sets)
- **Result persistence** (sink to Postgres/ClickHouse/S3)
- **Reproducibility** (event sourcing + immutable execution inputs)

### Example (conceptual)

```yaml
- step: submit_qpu_job
  tool:
    kind: quantum
    provider: ibm
    circuit: "{{ workload.circuit }}"
    shots: "{{ workload.shots | default(1024) }}"
  vars:
    job_id: "{{ result.job_id }}"
  next: poll_qpu_job

- step: poll_qpu_job
  tool:
    kind: quantum
    op: status
    job_id: "{{ vars.job_id }}"
  retry:
    - when: "{{ response.state in ['QUEUED','RUNNING'] }}"
      then:
        max_attempts: 120
        initial_delay: 2
        backoff_multiplier: 1.1
  case:
    - when: "{{ event.name == 'call.done' and response.state == 'DONE' }}"
      then:
        next:
          - step: fetch_results

- step: fetch_results
  tool:
    kind: quantum
    op: results
    job_id: "{{ vars.job_id }}"
  case:
    - when: "{{ event.name == 'step.exit' }}"
      then:
        sink:
          tool: { kind: postgres, auth: "{{ workload.pg_auth }}", table: qpu_results }
          args: { job_id: "{{ vars.job_id }}", counts: "{{ result.counts }}" }
  next: end
```

---

## 12. Validation rules (normative summary)

An implementation MUST reject (or mark invalid) a playbook if:

- Step names are not unique within `workflow`.
- `start` step is missing.
- A `next` reference points to a non-existent step.
- A `loop` block is present without both `in` and `iterator`.
- Tool `kind` is not recognized (unless extension handling is enabled).

---

## Appendix A — Structural grammar (EBNF-like, informative)

This grammar is a structural aid; YAML typing rules still apply.

```
playbook        ::= map
map             ::= { pair } ; YAML mapping
pair            ::= key ":" value

playbook_map    ::= apiVersion kind name path [workload] [workbook] workflow
workflow        ::= "workflow" ":" step_list
step_list       ::= "-" step { "-" step }

step            ::= "step" ":" IDENT
                    ["desc" ":" STRING]
                    ["args" ":" map]
                    ["tool" ":" tool]
                    ["loop" ":" loop]
                    ["retry" ":" retry]
                    ["vars" ":" map]
                    ["case" ":" case_list]
                    ["sink" ":" sink]
                    ["next" ":" next]

tool            ::= "kind" ":" IDENT { pair }
loop            ::= "in" ":" (STRING|list) "iterator" ":" IDENT ["mode" ":" ("sequential"|"parallel")]
retry           ::= list_of_policies | legacy_retry
case_list       ::= list_of_case_rules
next            ::= IDENT | list_of_transitions
```

---

## Appendix B — Recommended document set

- `docs/dsl/overview.md` — conceptual model and examples (user-facing)
- `docs/dsl/spec.md` — this formal specification (normative)
- `docs/runtime/events.md` — event envelope and event taxonomy
- `docs/runtime/control-plane-vs-workers.md` — boundary and scaling model
- `docs/profiles/quantum.md` — quantum orchestration patterns and tool extensions

