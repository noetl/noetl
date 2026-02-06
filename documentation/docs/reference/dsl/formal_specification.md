---
sidebar_position: 8
title: Formal Specification (Canonical)
description: Normative specification for NoETL DSL v2 (Petri-net canonical execution model)
---

# NoETL Playbook DSL — Formal Specification (Canonical v10)

> **Normative scope:** This document defines the **normative** semantics of the NoETL Playbook DSL and its **event‑sourced execution model** using the **Petri‑net canonical form**:
>
> - **Step** = admission gate (`step.spec.policy.admit`) + ordered pipeline (`step.tool`) + router (`step.next` with Petri‑net **arcs**)
> - **Task‑level policy** (`task.spec.policy.rules`) maps `outcome → do` (`retry|jump|continue|break|fail`) inside the pipeline
> - Runtime knobs/policies are expressed via **`spec`** at relevant scopes (executor/step/loop/task/next)
>
> **Versioning:** DSL is versioned via `apiVersion`. This spec targets `apiVersion: noetl.io/v2`.

---

## 1. Conformance and terminology (normative)

The key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are to be interpreted as normative requirements.

### 1.1 Entities (normative)

- **Playbook**: a YAML document describing workload defaults and a workflow of steps.
- **Workflow**: an ordered list of **Step** objects, routed via `next` arcs.
- **Step**: a Petri‑net transition that consumes a token when enabled and produces tokens via `next` arcs.
- **Task**: a labeled tool invocation within an ordered step pipeline.
- **Tool**: an executable adapter (HTTP, Postgres, DuckDB, Python, playbook, secrets lookup, etc.).
- **Token**: a routing envelope targeting a step, carrying `args` (arc inscription payload).
- **Workload**: immutable merged input (playbook defaults + execution request overrides).
- **Context**: the runtime evaluation environment containing namespaces: `workload`, `ctx`, `iter`, `args`, and pipeline locals.
- **ctx**: execution‑scoped mutable state shared across steps, persisted as event‑sourced patches.
- **iter**: iteration‑scoped mutable state local to one loop iteration.
- **policy.rules**: ordered rules mapping `outcome` → control directive.

### 1.2 Architecture roles (normative)

- **Server (control plane)**: provides API surface, token routing/scheduling, and authoritative event log persistence.
- **Worker (data plane)**: background execution pool (no HTTP endpoints); executes step pipelines; reports events to server.
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

**Root restriction (normative):** A playbook MUST NOT include `vars` at root level.

### 2.2 Step model (canonical)

A step is a mapping containing:

- `step`: **required** string identifier
- `desc`: optional string
- `spec`: optional mapping (step semantics/policy)
- `loop`: optional loop block
- `tool`: optional ordered list of tasks (pipeline)
- `next`: optional router defining outgoing arcs

A step **MUST** have at least one of: `tool` or `next`.
(If `tool` is absent, the step is a pure routing transition.)

**Canonical restriction:** The step MUST NOT include a top‑level `when` field. Step admission is specified only via `step.spec.policy.admit`.

### 2.3 Loop model (normative)

Loop modifies step execution by iterating the step pipeline over a collection:

```yaml
loop:
  spec:
    mode: sequential | parallel     # default sequential
    # max_in_flight: <int>          # optional for parallel
    policy:
      exec: distributed | local     # optional placement intent
  in: "{{ <collection expr> }}"
  iterator: <name>
```

### 2.4 Task model (normative)

A task is an entry in the step pipeline:

```yaml
- <task_label>:
    kind: <kind>
    spec: { ... }          # runtime knobs + policy
    ...inputs...
```

Tool `kind` values are implementation‑defined. Public kinds typically include:
- `http`, `postgres`, `duckdb`, `python`, `secrets`, `playbook`, `workbook`, `noop`

(Implementations MAY add additional kinds, including `quantum`.)

---

## 3. Template evaluation model (normative)

### 3.1 Template language
All expressions are **Jinja2** templates embedded as YAML strings.

### 3.2 Namespaces (normative)

The evaluation context is a dictionary with conventional namespaces:

- `workload`: immutable merged workload
- `ctx`: execution‑scoped mutable context (shared across steps)
- `iter`: iteration‑scoped variables (only inside loops)
- `args`: token payload / arc inscription input
- `execution_id`: unique execution identifier
- pipeline locals: `_prev`, `_task`, `_attempt`
- `outcome`: tool outcome envelope (only within task policy evaluation)
- `event`: boundary event payload (only within routing evaluation)

### 3.3 Read precedence recommendation (informative)
For reads: `args` → `ctx` → `iter` → `workload`.
For writes: per‑iteration → `iter`; cross‑step → `ctx`.

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
7. Determine initial token(s) and enqueue token(s) targeting the first runnable step(s) (implementation defined; a common convention is `step: start`).

### 4.2 Step admission (server)

The server is the authoritative scheduler of which step(s) run next.

For each token targeting a step, the server MUST:
- evaluate `step.spec.policy.admit.rules` (if present)
- if admitted, create a `step_run_id` and dispatch an execution command to a worker pool
- record scheduling decisions in the event log

Admission rule shape (normative):
```yaml
spec:
  policy:
    admit:
      rules:
        - when: "{{ <bool expr> }}"
          then: { allow: true|false }
        - else:
            then: { allow: true|false }
```

If `admit` is omitted, admission defaults to **allow**.

### 4.3 Step execution (worker)

The worker MUST:
- claim the `step_run_id` lease (single owner)
- execute the step pipeline (`step.tool`) deterministically
- if `loop` exists, execute the pipeline per iteration with isolated `iter` scope
- emit task events and terminal step events back to the server

### 4.4 Completion (server)

The workflow completes when there are no runnable tokens remaining.
The server emits `WorkflowFinished` and `PlaybookProcessed`.

---

## 5. Tool execution and `outcome` (normative)

Every tool invocation MUST produce one final outcome envelope:

- `outcome.status`: `"ok"` | `"error"`
- `outcome.result`: tool output (success; may be a reference)
- `outcome.error`: error object (error; MUST include `kind` and SHOULD include `retryable`)
- `outcome.meta`: attempt, duration, trace ids, timestamps

Kind helpers MAY be included:
- HTTP: `outcome.http.status`, `outcome.http.headers`
- Postgres: `outcome.pg.code`, `outcome.pg.sqlstate`
- Python: `outcome.py.exception_type`

---

## 6. Task policy (`task.spec.policy.rules`) (normative)

### 6.1 Purpose
Task policy maps a tool outcome to a deterministic pipeline directive.

### 6.2 Structure (normative)

Policy MUST be an object containing `rules:`:

```yaml
spec:
  policy:
    rules:
      - when: "{{ <bool expr over outcome/locals> }}"
        then:
          do: continue | retry | jump | break | fail
          attempts: <int>                 # for retry
          backoff: none | linear | exponential
          delay: <seconds|expr>
          to: <task_label>                # for jump
          set_iter: { ... }               # iteration-scoped write (preferred in loops)
          set_ctx: { ... }                # execution-scoped patch
      - else:
          then:
            do: continue
```

### 6.3 Evaluation algorithm (normative)

Given a task completion:
1. Evaluate `rules` entries in order.
2. First matching `when` wins.
3. If no entry matches and `else` exists, apply `else`.
4. If policy omitted:
   - on success → `continue`
   - on error → `fail`
5. If policy exists but no match and no else:
   - default → `continue`

### 6.4 Directive semantics (normative)
- `continue`: advance to next pipeline task
- `retry`: rerun current task until `attempts` exhausted (backoff/delay applied)
- `jump`: set pipeline program counter to `to`
- `break`: end pipeline successfully (iteration done / step.done)
- `fail`: end pipeline with failure (iteration failed / step.failed)

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
- `set_ctx` writes MUST be restricted or rejected unless the implementation defines reducers/atomics

### 7.3 Termination
When all iterations complete, worker emits `loop.done`.

---

## 8. Next routing (Petri‑net arcs) (normative)

### 8.1 Router model
`next` is a router object with arcs.

```yaml
next:
  spec:
    mode: exclusive | inclusive     # default exclusive
  arcs:
    - step: next_step
      when: "{{ <expr> }}"          # default true if omitted
      args: { ... }                # token payload (arc inscription)
```

### 8.2 Selection (`next.spec.mode`)
- `exclusive` (default): first matching arc fires (ordered)
- `inclusive`: all matching arcs fire

### 8.3 Evaluation placement
The server MUST evaluate `next.arcs[]` upon receiving a terminal step event (`step.done`, `step.failed`, `loop.done`) and persist the selected transitions.

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

**Note:** There is no special “Sink” tool kind. A sink is just a storage task that returns a reference.

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
- evaluate step admission via `step.spec.policy.admit`
- evaluate routing via `next.arcs[].when` and `next.spec.mode`
- coordinate fan-out/fan-in and pause/resume semantics (if implemented)

### 11.2 Worker MUST
- execute tool calls and step pipelines
- apply task policy deterministically
- emit detailed task/step/loop events to server
- require no inbound HTTP endpoints

---

## 12. Quantum orchestration profile (informative)

This canonical model maps naturally to quantum orchestration:
- job submission as tools (`kind: quantum`)
- polling as a pipeline loop via `policy: jump/retry`
- parameter sweeps via `loop`
- reproducibility via event sourcing + immutable workload inputs
- results stored externally and referenced via `ctx`

---

## 13. Validation rules (normative summary)

An implementation MUST reject a playbook if:
- step names are not unique within `workflow`
- a `next.arc.step` references a non-existent step
- a `loop` block is present without both `in` and `iterator`
- a tool `kind` is not recognized (unless extension handling is enabled)
- `vars` exists at playbook root level
- a step has top-level `when`
- a task policy is not an object containing `rules`

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
                    ["loop" ":" loop]
                    ["tool" ":" tool_pipeline]
                    ["next" ":" next_router]

loop            ::= "in" ":" (STRING|list) "iterator" ":" IDENT ["spec" ":" map]

tool_pipeline   ::= "-" task { "-" task }
task            ::= IDENT ":" tool
tool            ::= "kind" ":" IDENT ["spec" ":" map] { pair }

next_router     ::= "spec" ":" map "arcs" ":" next_arcs
next_arcs       ::= "-" next_arc { "-" next_arc }
next_arc        ::= "step" ":" IDENT ["when" ":" STRING] ["args" ":" map] ["spec" ":" map]
policy_rules    ::= "-" policy_rule { "-" policy_rule }
policy_rule     ::= ("when" ":" STRING "then" ":" map) | ("else" ":" map)
```

---

## Appendix B — Recommended document set
- `docs/dsl/dsl_specification.md` — user-facing canonical DSL spec
- `docs/dsl/formal_specification.md` — this formal spec (normative)
- `docs/runtime/events.md` — event envelope and event taxonomy
- `docs/runtime/control-plane-vs-workers.md` — boundary and scaling model
- `docs/profiles/quantum.md` — quantum orchestration patterns
