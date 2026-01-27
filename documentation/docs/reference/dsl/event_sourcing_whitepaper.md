---
sidebar_position: 7
title: Event Sourcing Whitepaper
description: Technical whitepaper on NoETL's event-sourced architecture
---

# NoETL DSL & Event Sourcing

## Technical Whitepaper

### Abstract
NoETL is an event-sourced orchestration system for **tools** (HTTP, databases, Python, secrets, and future compute backends such as quantum providers). Users define automation in a declarative **Playbook** DSL (YAML + Jinja2 templating). Execution is driven by a control plane (server) and performed by a data plane (worker pool). Every lifecycle transition is recorded as an immutable **event log** to support reproducibility, auditing, replay, and optimization.

This whitepaper describes the core runtime model, how the DSL maps to the execution lifecycle, and how event sourcing enables reliability features such as retries, loops, sinks, and conditional routing. It also outlines how the same model supports hybrid **quantum/classical orchestration**.

---

## 1. System Model

### 1.1 Components
- **Server (control plane)**
  - Exposes API endpoints (e.g., submit execution request, read execution status, stream events).
  - Orchestrates workflow progression and dispatches work to workers.
  - Owns the canonical event log storage and execution state derivation.

- **Worker (data plane)**
  - Pure background worker pool (no HTTP endpoints).
  - Executes tools (HTTP/DB/Python/Secrets/…).
  - Emits execution events to the server API for persistence.

- **CLI (noetlctl)**
  - Manages server lifecycle and worker pools.
  - Registers playbooks into the catalog and triggers executions.

### 1.2 Why event sourcing
Event sourcing makes “what happened” the primary truth:
- Every state change is an **append-only event**.
- The current execution state is a **projection** derived from events.
- Retries, pauses, replays, and audits are natural outcomes of the event log.

This model is particularly important for:
- **Data governance** (lineage of inputs → outputs)
- **MLOps** (tracking model/data versions)
- **Quantum orchestration** (capturing shots, calibration metadata, seeds, and provider job ids)

---

## 2. DSL Overview

### 2.1 Canonical entities
- **Playbook**: versioned automation unit.
- **Workbook**: named tool/task definitions reusable by workflow steps.
- **Workflow**: ordered/conditional set of steps; execution graph.
- **Step**: control node; may execute a tool/task and route next.
- **Tool**: an executable adapter (http, postgres, duckdb, python, secrets, …).
- **Loop**: repeated execution of a step or subgraph over a collection.
- **Case**: conditional router attached to a step; evaluates predicates.
- **Next**: shortcut routing rules at step level.
- **Sink**: persistence rule for results (e.g., insert into postgres).
- **Context**: hierarchical runtime data (workload + step results + loop variables).
- **Workload**: input parameters for a run; merged with request payload.
- **Variable**: named value in context (workload fields, step outputs, loop iterators).

### 2.2 Minimal structure
```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: example
  path: examples/example

workload:
  jobId: "{{ job.uuid }}"
  items: []

workbook:
  - name: do_work
    tool:
      kind: http
      url: "https://example.com"
      method: GET

workflow:
  - step: start
    tool:
      kind: python
      code: "result = {'status': 'initialized'}"
    next:
      - step: do_work

  - step: do_work
    tool:
      kind: workbook
      name: do_work
    next:
      - step: end

  - step: end
    tool:
      kind: python
      code: "result = {'status': 'completed'}"
```

### 2.3 Jinja2 templating
Any scalar or compound value may be templated:
- Strings: `"{{ workload.jobId }}"`
- Objects/lists can contain templated values.
- Predicates in `when`/`case` should be templated expressions returning booleans.

---

## 3. Execution Lifecycle

### 3.1 High-level lifecycle
1. **Execution request** arrives to server API.
2. Server loads playbook by `playbook_id` or `(path, version)`.
3. Server evaluates `workload` and merges with request payload.
4. Server builds **initial context**.
5. Server locates initial step `start`.
6. Server dispatches work to workers (tool execution) and/or evaluates routing.
7. All transitions are emitted as events; server projects state.
8. Workflow finishes or pauses.

### 3.2 Event types (domain-level)
The domain event family (naming is normative; mappings to implementation events may differ):
- `PlaybookExecutionRequested`
- `PlaybookRequestEvaluated` (valid/invalid)
- `WorkflowStarted`
- `StepStarted`
- `ToolStarted`
- `ToolFinished`
- `LoopStarted`
- `LoopIterationStarted`
- `LoopIterationFinished`
- `CaseStarted`
- `CaseEvaluated`
- `RetryStarted`
- `RetryProcessed`
- `SinkStarted`
- `SinkProcessed`
- `NextEvaluated`
- `WorkflowFinished`
- `PlaybookPaused`
- `PlaybookProcessed` (terminal: success/error/cancelled)

### 3.3 Implementation-level events (observed in tool executors)
Tool executors typically emit:
- `task_start` (node_type: http|postgres|duckdb|python|secrets)
- `task_complete`
- `task_error`

The server can either:
- store these as-is, or
- normalize them to the domain events above (recommended).

---

## 4. Context and Data Flow

### 4.1 Context layers
Context is hierarchical and should be treated as a structured object:
- `workload`: merged inputs
- `job`: runtime metadata (ids)
- `step.<step_name>`: step-local fields
- `results.<step_or_task_name>`: outputs of tool execution
- `loop.<loop_name>`: loop control + iteration results

### 4.2 Step parameters (`args`)
`args` binds values into the step's tool for rendering.
- All values are rendered with the current context.
- Bound values become part of the input contract of the tool.

Example (from a weather loop pattern):
```yaml
- step: city_loop
  loop:
    in: "{{ workload.cities }}"
    iterator: city
    mode: sequential
  tool:
    kind: http
    url: "{{ workload.base_url }}/weather"
    params:
      city: "{{ city }}"
  next:
    - step: evaluate_weather
```

### 4.3 Output and result addressing
- Tool results are recorded in events and are addressable in templates.
- Convention: outputs may be accessible by task name, step name, or explicit alias.

---

## 5. Workflow Routing: `case`, `next`, and server vs worker decisions

### 5.1 `next` (step-level routing shortcut)

In v2, `next` provides unconditional default routing. For conditional routing, use `case`:

```yaml
# Conditional routing uses case
case:
  - when: "{{ some_condition }}"
    then:
      next:
        - step: a
        - step: b
next:
  - step: c  # Default fallback
```

Rules:
- `case` rules are evaluated in order.
- `when` is a Jinja2 expression returning boolean.
- `then` contains actions including `next` with step references.
- `next` at step level is the fallback when no `case` matches.

**Note:** The v1 pattern `next: [{ when: ..., then: ... }]` is NOT supported in v2.

### 5.2 `case` (generalized router)
`case` is the generalized form of `next`. It can be evaluated:
- **on the server** (control-plane routing), or
- **on the worker** (data-plane routing) when the decision depends on immediate tool outcomes, or to reduce round trips.

Recommended approach:
- The worker evaluates `case` only to choose among *local continuations* (e.g., do a sink now vs return control).
- The server remains authoritative for global workflow progression and persistent state.

### 5.3 What runs where
**Server (control plane) is authoritative for:**
- validating playbook + dependencies
- building the initial context
- selecting which step(s) to run next
- deciding concurrency policy across steps (if supported)
- pausing/resuming executions
- enforcing quotas and tenancy

**Worker (data plane) is responsible for:**
- executing tool adapters
- performing short-lived “local” decisions (optional) like immediate branching/sink for a single step
- reporting every transition and result to the server

---

## 6. Loops

### 6.1 Loop model
A `loop` repeats execution over a collection.

Canonical clause:
```yaml
loop:
  in: "{{ workload.items }}"
  iterator: item
  mode: sequential   # (optional) sequential | parallel
  limit: 1000        # (optional) safety cap
```

Semantics:
- Render `in` → collection.
- For each element, bind it into context under `iterator` name.
- Execute the loop body (typically “next steps”) per iteration.
- Collect iteration outputs into a well-defined aggregation object (e.g., `<loop_step_name>_results`).

### 6.2 Loop boundary (`end_loop`)
An explicit loop-end step makes the boundary and aggregation deterministic:
```yaml
- step: end_city_loop
  end_loop: city_loop
  result:
    alerts: "{{ city_loop_results | map(attribute='fetch_and_evaluate') | list }}"
```

Rules:
- The loop-end step closes the loop and may compute a final derived result.
- The derived result is published into context for downstream steps.

### 6.3 Loop events
For each loop:
- `LoopStarted(loop_id)`
- For each iteration:
  - `LoopIterationStarted(iteration_id, iterator_value)`
  - tool/step events
  - `LoopIterationFinished(iteration_id, status, outputs)`
- `LoopFinished(loop_id, summary)`

---

## 7. Retry

### 7.1 Retry clause
Retries can apply to a tool execution and/or a step:
```yaml
retry:
  max_attempts: 5
  backoff:
    type: exponential
    base_seconds: 1
    max_seconds: 60
  when:
    - "{{ last_error is not none }}"
    - "{{ result.status_code in [429, 500, 502, 503, 504] }}"
```

Semantics:
- A retry is a controlled re-execution of the same tool call with the same (or adjusted) inputs.
- Each attempt must be evented; attempts are linked by `retry_id` and `attempt` counter.

### 7.2 Retry events
- `RetryStarted(retry_id, attempt)`
- `RetryProcessed(retry_id, attempt, outcome)`
- Tool events for each attempt

### 7.3 Determinism and replay
To support replay, a retry attempt must record:
- rendered inputs (post-template)
- environment references (secrets by reference, not raw)
- correlation ids (execution_id, step_run_id, tool_run_id)

---

## 8. Sink

### 8.1 Purpose
A **sink** persists results, enabling event streams to become materialized datasets.

### 8.2 Sink placement
- Step-level sink: persist the result of the step’s tool.
- Case-level sink: persist only for certain branches.

Example:
```yaml
sink:
  tool:
    kind: postgres
    table: noetl.event_sink
    mode: insert
  args:
    execution_id: "{{ workload.jobId }}"
    step: "{{ step.name }}"
    payload: "{{ result }}"
```

### 8.3 Sink events
- `SinkStarted`
- `SinkProcessed(status, row_count, error?)`

---

## 9. Event Schema

### 9.1 Envelope
Every event should have a stable envelope:
- `event_id` (uuid)
- `event_type` (string)
- `timestamp` (UTC)
- `execution_id`
- `playbook_id` or `(path, version)`
- `workflow_run_id`
- `step_run_id` (optional)
- `tool_run_id` (optional)
- `loop_id` / `iteration_id` (optional)
- `parent_event_id` (optional)
- `status` (in_progress|success|error|paused)
- `duration_sec` (optional)
- `input` (rendered input snapshot)
- `output` (result snapshot)
- `error` (structured)
- `metadata` (free-form)

### 9.2 Correlation
Event sourcing depends on consistent correlation:
- `execution_id` ties everything together.
- `step_run_id` groups events for a step.
- `tool_run_id` groups tool attempts.
- `parent_event_id` supports nested trees.

---

## 10. Quantum orchestration fit

### 10.1 Why NoETL maps well to quantum
Quantum execution is naturally asynchronous and eventful:
- job submission → queued → running → completed
- provider errors and transient states
- hybrid loops (parameter sweeps, variational algorithms)

NoETL’s model (tools + event log + workflow routing) aligns with this.

### 10.2 Quantum tool adapter (conceptual)
Add a `quantum` tool kind with a strict contract:
- Inputs: provider, backend, circuit (QASM/IR), shots, params, seed, tags
- Outputs: job_id, measurement counts, metadata (calibration snapshot id, backend properties)

### 10.3 Typical patterns
- **Parameter sweep loop**: loop over parameter grid; run circuit; aggregate metrics.
- **VQE/VQA**: loop until convergence; route with `case` based on loss delta.
- **Fallback routing**: `case` to re-route to simulator when QPU queue is too long.

### 10.4 Quantum provenance requirements
For reproducibility, store (or reference):
- provider job id
- backend name + version
- calibration timestamp / snapshot id
- transpiler settings
- random seeds
- shots

---

## 11. Security and Secrets
- Secrets should be referenced by handle/path (e.g., secret manager path), not embedded.
- Workers resolve secrets at runtime and only emit references in events.
- Event log should support redaction rules.

---

## 12. Observability and optimization
With event sourcing you can compute:
- step/tool durations, error rates
- retry counts, backoff efficiency
- loop iteration throughput
- cost models (cloud API calls, DB IO, QPU time)

This enables automated optimization:
- choose better concurrency settings
- select compute targets (CPU/GPU/QPU)
- reroute to cheaper/faster backends

---

## 13. Recommended Roadmap (implementation hardening)
1. Normalize implementation events (`task_*`) into domain events.
2. Formalize correlation ids (execution_id, step_run_id, tool_run_id, loop_id).
3. Define an explicit `case` clause grammar and evaluation rules.
4. Add a first-class retry clause with backoff.
5. Add first-class sink definitions with typed destinations.
6. Add a `quantum` tool adapter spec.

---


# Document 2 — Formal Specification (Draft)

## 1. Conformance terminology
- **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, **MAY** are to be interpreted as in RFC 2119.

## 2. Playbook document
A playbook document MUST be valid YAML.

### 2.1 Top-level
A playbook MUST contain:
- `apiVersion` (string)
- `kind` = `Playbook`
- `name` (string)
- `path` (string)

A playbook SHOULD contain:
- `workload` (mapping)
- `workflow` (sequence)
- `workbook` (sequence)

### 2.2 Workload
- `workload` is a mapping of user-defined keys to YAML values.
- The engine MUST render templated values in workload before execution starts.
- The execution request payload MUST be merged into workload (merge policy MUST be defined; default = request overrides playbook workload keys).

### 2.3 Workbook
- `workbook` is a sequence of task definitions.
- Each task MUST have:
  - `name` (string)
  - `type` (enum)

Task `type` MAY be one of:
- `http`
- `postgres`
- `duckdb`
- `python`
- `secrets`
- `workbook` (alias/reference)
- `loop` (if loop is modeled as a task type)

### 2.4 Workflow
- `workflow` is a sequence of steps.
- Each step MUST have a unique `step` name.
- A step named `start` MUST exist.

A step MAY contain:
- `desc` (string)
- `type` (string)
- `name` (string) — workbook task reference
- `tool` (mapping) — inline tool invocation (if supported)
- `with` (mapping)
- `loop` (mapping)
- `end_loop` (string)
- `case` (sequence)
- `next` (sequence)
- `sink` (mapping)
- `retry` (mapping)
- `result` (mapping)

## 3. Template evaluation
- The engine MUST use a Jinja2-compatible renderer.
- Template context MUST include workload and current scope variables.
- Failure to render a template MUST be surfaced as an error event.

## 4. Step evaluation semantics

### 4.1 Pure routing step
A step with `next`/`case` and without `tool`/`name` MAY be evaluated as a router.

### 4.2 Workbook step
If a step has `type: workbook` and `name: <task_name>`, the engine MUST:
1. Resolve `<task_name>` from `workbook`.
2. Render its inputs using the current context and `with` bindings.
3. Dispatch tool execution to a worker.

### 4.3 `next` rules
A `next` item is one of:
- Conditional:
  - `when` + `then`
- Default:
  - `else`
- Direct:
  - `step` (+ optional `with`)

Evaluation:
- Conditional rules MUST be evaluated in order.
- The first matching rule MUST be applied.
- If no conditional matches and an `else` exists, it MUST be applied.

### 4.4 `case` rules
`case` generalizes `next`. It MAY inspect:
- current context
- current step output
- last error

`case` evaluation MUST emit:
- `CaseStarted`
- `CaseEvaluated`

## 5. Loop semantics

### 5.1 Loop clause
A loop clause MUST contain:
- `in` (templated expression returning a sequence)
- `iterator` (identifier)

It MAY contain:
- `mode` (sequential|parallel)
- `limit` (integer)

### 5.2 Loop execution
For each element in the rendered collection:
- bind element to `iterator` in a child scope
- execute the loop body
- collect per-iteration results

Loop execution MUST emit loop lifecycle events.

## 6. Retry semantics
A retry clause MAY contain:
- `max_attempts` (int)
- `backoff` (mapping)
- `when` (list of predicates)

Retry MUST emit retry lifecycle events and MUST be correlated to the underlying tool events.

## 7. Sink semantics
A sink MUST declare:
- destination tool kind
- destination parameters (table/path/etc)
- persistence mode (insert/upsert/append)

Sink MUST emit sink lifecycle events.

## 8. Event sourcing requirements
- Every execution MUST be representable as an ordered stream of events.
- The server MUST persist events in append-only order.
- The server MUST be able to derive current execution state from events.
- Each event MUST include correlation ids.

## 9. Error handling
- Any failure in template rendering, tool execution, sink writing, or routing MUST emit an error event.
- A terminal error MUST result in `PlaybookProcessed(status=error)`.

## 10. Quantum tool adapter (reserved)
A `quantum` tool kind is RESERVED for future use.
A conforming implementation SHOULD capture provenance fields required for reproducibility.

