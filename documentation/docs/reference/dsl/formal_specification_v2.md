---
sidebar_position: 8
title: Formal Specification (Canonical)
description: Normative specification for NoETL DSL v2 (Petri-net canonical execution model)
---

# NoETL Playbook DSL — Formal Specification (Canonical)

> **Scope (normative):** This document defines the **normative** semantics of the NoETL Playbook DSL and its **event‑sourced execution model** using the **Petri-net canonical form**:
>
> - Step = `when` (enable guard) + `tool` (ordered pipeline) + `next` (arcs)
> - Tool-level `eval` (with `expr`) controls retry/jump/break/fail/continue inside the pipeline
> - Runtime semantics/policy is expressed via `spec` at relevant scopes (playbook/step/loop/tool/next)
>
> **Versioning:** DSL is versioned via `apiVersion`. This spec targets `apiVersion: noetl.io/v2`.

---

## 1. Conformance and terminology

The key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are to be interpreted as normative requirements.

### 1.1 Entities (normative)

- **Playbook**: a YAML document describing immutable workload defaults and a workflow of steps.
- **Workflow**: an ordered list of **Step** objects (graph routing defined via `next`).
- **Step**: a Petri-net transition which consumes a token when enabled and produces tokens via `next` arcs.
- **Tool**: an executable adapter (HTTP, Postgres, DuckDB, Python, nested playbook, secrets lookup, etc.).
- **Token**: a routing envelope that targets a step, carrying `args` (arc inscription payload).
- **Workload**: immutable merged input (playbook defaults + execution request overrides).
- **Context**: runtime evaluation environment containing namespaces: `workload`, `ctx`, `vars`, `iter`, `args`, and pipeline locals.
- **ctx**: **execution-scoped** mutable state shared across steps, persisted as event-sourced patches.
- **vars**: **step-run-scoped** mutable state local to the current step execution.
- **iter**: **iteration-scoped** mutable state local to one loop iteration.
- **eval**: tool-level ordered rules mapping `outcome` → control directive.

### 1.2 Architecture roles (normative)

- **Server (control plane)**: provides API surface, token routing/scheduling, and authoritative event log persistence.
- **Worker (data plane)**: background execution pool (no HTTP endpoints); executes tool invocations and step pipelines; reports events to server.
- **CLI**: manages server/worker lifecycle and worker pools.

---

## 2. Document model (normative)

### 2.1 YAML document

A playbook is a YAML mapping with (at minimum):

- `apiVersion`: string (MUST be `noetl.io/v2` for this spec)
- `kind`: string (MUST be `Playbook`)
- `metadata`: mapping (MUST include `name` and `path`)
- `executor`: mapping (OPTIONAL)
- `workload`: mapping (OPTIONAL; defaults)
- `workflow`: list of steps (REQUIRED)
- `workbook`: mapping (OPTIONAL)

**Root restriction (normative):** A playbook MUST NOT include `vars` at root level. Execution-scope state is `ctx` (runtime) and is not a root field.

### 2.2 Step model (canonical)

A step is a mapping containing:

- `step`: **required** string identifier
- `desc`: optional string
- `spec`: optional mapping (semantics/policy, e.g., `next_mode`)
- `when`: optional templated string expression (enable guard; default `true`)
- `args`: optional mapping (step input shaping; implementation-defined)
- `loop`: optional loop block
- `tool`: optional ordered list of tool tasks (pipeline)
- `next`: optional list of transitions (arcs)

A step **MUST** have at least one of: `tool` or `next`.
(If `tool` is absent, the step is a pure routing transition.)

### 2.3 Loop model

Loop modifies step execution by iterating the step pipeline over a collection:

```yaml
loop:
  spec:
    mode: sequential | parallel     # default sequential
    # max_in_flight: <int>          # optional for parallel
  in: "{{ <collection expr> }}"
  iterator: <name>
```

### 2.4 Tool task model

A tool task is an entry in the step pipeline:

```yaml
- <task_label>:
    kind: <kind>
    spec: { ... }     # runtime knobs/policy (timeouts, pooling, internal retry, etc.)
    ...inputs...
    eval: [ ... ]     # optional control rules (outcome -> directive)
```

Tool `kind` values are implementation-defined. The public reference includes:
- `http`, `postgres`, `duckdb`, `python`, `secrets`, `playbook`, `workbook`

(Implementations MAY add additional kinds, including `quantum`.)

---

## 3. Template evaluation model (normative)

### 3.1 Template language
All expressions are **Jinja2** templates embedded as YAML strings.

### 3.2 Namespaces (normative)

The evaluation context is a dictionary with conventional namespaces:

- `workload`: immutable merged workload
- `ctx`: execution-scoped mutable context (shared across steps)
- `vars`: step-run-scoped variables
- `iter`: iteration-scoped variables (only inside loops)
- `args`: token payload / arc inscription input
- `execution_id`: unique execution identifier
- pipeline locals: `_prev`, `_task`, `_attempt`
- `outcome`: tool outcome envelope (only within `eval.expr`)

### 3.3 Precedence recommendation (informative)
For reads: `args` → `ctx` → `workload`.
For writes: per-iteration → `iter`; per-step → `vars`; cross-step → `ctx`.

---

## 4. Execution model (control plane vs worker) (normative)

### 4.1 Execution request (server)

When an execution request is received, the server MUST:

1. Persist `PlaybookExecutionRequested`.
2. Resolve the playbook (by `playbook_id` or `path+version`).
3. Validate the playbook structure and references.
4. Persist `PlaybookRequestEvaluated`.
5. Merge request payload with playbook `workload` defaults → **MergedWorkload**.
6. Initialize runtime state: `ctx = {}` (empty unless provided by request profile).
7. Locate the initial step (convention: `start`) and enqueue a token targeting that step.

### 4.2 Step scheduling (server)

The server is the authoritative scheduler of which step(s) run next.

For each token, the server MUST:
- evaluate `step.when` (default `true`)
- if enabled, create a `step_run_id` and dispatch an execution command to a worker pool
- record scheduling and routing decisions in the event log

### 4.3 Step execution (worker)

The worker MUST:
- claim the `step_run_id` lease (single owner)
- execute the step pipeline (`step.tool`) deterministically
- emit tool/task events and terminal step events back to the server

### 4.4 Completion (server)

The workflow completes when there are no runnable tokens remaining (or end convention).
The server emits `WorkflowFinished` and `PlaybookProcessed`.

---

## 5. Tool execution and `outcome` (normative)

Every tool invocation MUST produce one final outcome envelope:

- `outcome.status`: `"success"` | `"error"`
- `outcome.result`: tool output (success)
- `outcome.error`: error object (error)
- `outcome.meta`: attempt, duration, trace ids, timestamps

Kind helpers MAY be included:
- HTTP: `outcome.http.status`, `outcome.http.headers`
- Postgres: `outcome.pg.code`, `outcome.pg.message`
- Python: `outcome.py.exception`

---

## 6. Tool-level `eval` (normative)

### 6.1 Purpose
`eval` maps a tool outcome to a deterministic pipeline directive.

### 6.2 Structure

```yaml
eval:
  - expr: "{{ <bool expr over outcome/locals> }}"
    do: continue | retry | jump | break | fail
    attempts: <int>                 # for retry
    backoff: fixed | linear | exponential
    delay: <seconds|expr>
    to: <task_label>                # for jump
    set_iter: { ... }               # iteration-scoped write (preferred in loops)
    set_vars: { ... }               # step-run-scoped write
    set_ctx: { ... }                # execution-scoped patch
    set_shared: { ... }             # explicit shared write (reducers/atomics; optional feature)
    set_prev: <value>               # override pipeline _prev
  - else:
      do: continue
```

### 6.3 Evaluation algorithm (normative)

Given a tool completion:
1. Evaluate `eval` entries in order.
2. First matching `expr` wins.
3. If no entry matches and `else` exists, apply `else`.
4. If `eval` omitted (or no match and no else):
   - on success → `continue`
   - on error → `fail`

### 6.4 Directive semantics (normative)
- `continue`: advance to next pipeline task
- `retry`: rerun current task until `attempts` exhausted (backoff/delay applied)
- `jump`: set pipeline program counter to `to`
- `break`: end pipeline successfully (emit `step.done`)
- `fail`: end pipeline with failure (emit `step.failed`)

---

## 7. Loop semantics (normative)

### 7.1 Iteration scope
For each element in `loop.in`, a new iteration scope is created:
- binds `iter.<iterator>` to current element
- provides `iter.index`
- isolates `iter.*` updates per iteration

### 7.2 Parallel safety
If `loop.spec.mode: parallel`:
- `set_iter` writes are always safe
- writes to shared `vars` require explicit intent (e.g., `set_shared`) OR must be deterministically mapped to iteration scope (implementation MUST pick one behavior and document it)

### 7.3 Termination
When all iterations complete, worker emits `loop.done`.

---

## 8. Next / routing semantics (normative)

### 8.1 Next transitions
`next` is a list of arcs. Each arc may have a guard and token payload.

```yaml
next:
  - step: next_step
    when: "{{ <expr> }}"          # default true if omitted
    args: { ... }                # token payload (arc inscription)
```

### 8.2 Selection (`step.spec.next_mode`)
- `exclusive` (default): first matching arc fires (ordered)
- `inclusive`: all matching arcs fire

### 8.3 Evaluation placement
The server MUST evaluate `next[]` upon receiving a terminal step event (`step.done`, `step.failed`, `loop.done`) and persist the selected transitions.

---

## 9. Results and payload storage (normative)

### 9.1 Reference-first rule
Implementations MUST avoid storing huge payload bodies in the event log by default.
Large results SHOULD be stored externally (Postgres tables, object store, NATS object store, etc.) and events SHOULD carry references.

Recommended reference object shape:
```json
{ "store": "postgres.table", "key": "pagination_test_results", "range": "id:100-150", "size": 123456, "checksum": "..." }
```

### 9.2 Updating execution context (`ctx`)
Cross-step state SHOULD be stored as references in `ctx` using `set_ctx` patches (recorded as events).

---

## 10. Event sourcing model (normative)

### 10.1 Event envelope (minimum)
Every observable state transition MUST be recorded as an event with:
- `event_id`
- `execution_id`
- `timestamp`
- `source`: `server` | `worker`
- `name`: event name
- `entity`: `playbook` | `workflow` | `step` | `task` | `loop` | `next`
- `entity_id`: identifier of the entity instance
- `status`: `in_progress` | `success` | `error` | `paused`
- `data`: JSON payload (metadata, references, errors)

### 10.2 Canonical event taxonomy (recommended)
**Control-plane (server):**
- `PlaybookExecutionRequested`
- `PlaybookRequestEvaluated`
- `WorkflowStarted`
- `TokenEnqueued` / `TokenClaimed`
- `StepScheduled`
- `NextEvaluated`
- `WorkflowFinished`
- `PlaybookProcessed`

**Data-plane (worker):**
- `TaskStarted`
- `TaskProcessed` (includes `outcome`)
- `StepDone` / `StepFailed`
- `LoopStarted` / `LoopIterationStarted` / `LoopIterationCompleted` / `LoopDone`

### 10.3 Replay requirement
An implementation MUST be able to reconstruct:
- current runnable tokens / step runs
- `ctx` (from patches + snapshots)
- loop position (from events)
from the event stream plus any optional snapshots.

---

## 11. Control-plane vs data-plane boundaries (normative)

### 11.1 Server MUST
- accept execution requests and validate playbooks
- schedule steps by routing tokens
- persist the append-only event log
- evaluate `step.when` and `next[].when`
- coordinate fan-out/fan-in and pause/resume semantics (if implemented)

### 11.2 Worker MUST
- execute tool calls and step pipelines
- apply tool-level `eval` deterministically
- emit detailed task/step/loop events to server
- require no inbound HTTP endpoints

---

## 12. Quantum orchestration profile (informative)

This canonical model maps naturally to quantum orchestration:
- job submission as tools (`kind: quantum`)
- polling as a pipeline loop via `eval: jump/retry`
- parameter sweeps via `loop`
- reproducibility via event sourcing + immutable workload inputs
- results stored externally and referenced via `ctx`

---

## 13. Validation rules (normative summary)

An implementation MUST reject a playbook if:
- step names are not unique within `workflow`
- the `start` step is missing (convention; if your runtime uses a different entrypoint, document it)
- a `next.step` references a non-existent step
- a `loop` block is present without both `in` and `iterator`
- a tool `kind` is not recognized (unless extension handling is enabled)
- `vars` exists at playbook root level

---

## Appendix A — Structural grammar (informative)

```
playbook        ::= map
root_keys       ::= apiVersion kind metadata [executor] [workload] workflow [workbook]

workflow        ::= "workflow" ":" step_list
step_list       ::= "-" step { "-" step }

step            ::= "step" ":" IDENT
                    ["desc" ":" STRING]
                    ["spec" ":" map]
                    ["when" ":" STRING]
                    ["args" ":" map]
                    ["loop" ":" loop]
                    ["tool" ":" tool_pipeline]
                    ["next" ":" next_list]

loop            ::= "in" ":" (STRING|list) "iterator" ":" IDENT ["spec" ":" map]

tool_pipeline   ::= "-" task { "-" task }
task            ::= IDENT ":" tool
tool            ::= "kind" ":" IDENT ["spec" ":" map] ["eval" ":" eval_list] { pair }

next_list       ::= "-" next_arc { "-" next_arc }
next_arc        ::= "step" ":" IDENT ["when" ":" STRING] ["args" ":" map] ["spec" ":" map]
eval_list       ::= "-" eval_rule { "-" eval_rule }
eval_rule       ::= ("expr" ":" STRING "do" ":" IDENT { pair }) | ("else" ":" map)
```

---

## Appendix B — Recommended document set
- `docs/dsl/dsl_specification.md` — user-facing canonical DSL spec
- `docs/dsl/formal_specification.md` — this formal spec (normative)
- `docs/runtime/events.md` — event envelope and event taxonomy
- `docs/runtime/control-plane-vs-workers.md` — boundary and scaling model
- `docs/profiles/quantum.md` — quantum orchestration patterns
