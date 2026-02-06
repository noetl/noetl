# Implement NoETL Canonical DSL (Agent Instructions) — v6 (Validated)

This document is a **direct implementation brief** for AI agents (Copilot/Claude/etc.) to implement the **NoETL canonical DSL** end-to-end, aligned with the latest decisions (Canonical v10):

- `when` is the **only** conditional keyword.
- All knobs live under `spec` (at any level).
- Policies live under `spec.policy` and are **typed by scope**.
- Task outcome handling uses **`task.spec.policy` (object)** with **required `rules:`** (ONE shape).
- Routing uses **Petri-net arcs**: `step.next` is an object with `next.spec` + `next.arcs[]`.
- **No** special “sink” tool kind — storage is “just tools” returning references.
- `loop` is a step modifier (not a tool kind). Streaming/pagination uses task `jump`/`break` within a single iteration lease.
- **No `step.when` field**. Step admission is expressed via **`step.spec.policy.admit.rules`**.

---

## 0) Architecture assumptions (MUST)

- **Worker (`worker.py`)**: pure background worker pool. **No HTTP endpoints.**
- **Server (`server.py`)**: orchestration/control plane + **API endpoints** + event log persistence.
- **CLI (`clictl.py`)**: manages worker pools and server lifecycle.

**Hard boundary:**
- Server **admits steps**, **routes tokens**, **schedules steps/iterations**, and **persists the event log**.
- Worker **executes step pipelines** and **applies task policies** (retry/jump/break/fail/continue) and reports events.

A worker policy MUST NOT start steps. Only server routing (`next.arcs`) starts steps.

---

## 1) Canonical DSL rules (MUST)

### 1.1 Only one conditional keyword
- The only conditional keyword is: **`when`**.
- Reject: `expr`, legacy `eval` blocks, ad-hoc condition keys, and any top-level `step.when` field.

### 1.2 Everything configurable belongs in `spec`
Any options/knobs/policies MUST be under `spec` at some scope:
- `executor.spec`
- `step.spec`
- `loop.spec`
- `task.spec`
- `next.spec`
- `arc.spec` (reserved; future)

### 1.3 Policies are under `spec.policy`
`spec.policy` exists at multiple scopes and is **typed by scope**:

- `step.spec.policy.admit` → admission gate (server-side)
- `task.spec.policy.rules` → outcome handling (worker-side; only place with `do:` control directives)
- `next.spec` → routing mode (server-side)
- `loop.spec` → scheduling mode/caps (server-side)
- Other `spec.policy` fields are placeholders / hints unless explicitly defined.

### 1.4 Task policy has ONE shape (no alternatives)
`task.spec.policy` MUST be an object with a required `rules:` list.

```yaml
spec:
  policy:
    rules:
      - when: "{{ ... }}"
        then: { do: retry, attempts: 5, backoff: exponential, delay: 1.0 }
      - else:
          then: { do: continue }
```

No list form is allowed. No backward compatibility.

---

## 2) Root playbook structure (MUST)

Canonical root sections (top-level keys):

- `metadata`
- `keychain` (optional but recommended; credential declarations)
- `executor` (optional; runtime/backend knobs)
- `workload` (immutable defaults merged with execution request)
- `workflow` (array of steps)
- `workbook` (optional reusable blocks)

Reject root `vars`.

### 2.1 `keychain` (root) — credential declarations

`keychain` is a **playbook authoring concern**: it declares which credentials/secrets/tokens the playbook requires and how they are resolved.

- Resolution happens before workflow execution (during execution request evaluation).
- Resolved values are exposed as `{{ keychain.<name>... }}`.
- `keychain` values are **read-only** during execution (refresh/rotation is implemented as tools + policies, not by mutating `keychain`).

Example:
```yaml
keychain:
  - name: openai_token
    kind: secret_manager
  - name: pg_k8s
    kind: postgres_credential
```

### 2.2 `executor` (root, optional) — runtime/backend knobs

`executor` is a **runtime concern**: it selects execution profile and provides defaults that apply across steps/tasks **unless overridden** by inner `spec`.

Typical fields (examples; not exhaustive):
- `executor.profile`: e.g. `local` | `distributed`
- `executor.version`: runtime/ABI string (helps multi-runtime deployments)
- `executor.spec`: default knobs applied to all steps/tasks via spec layering
  - default timeouts
  - default result store policy
  - sandbox/resource hints
  - tracing/telemetry defaults

`executor` MUST be optional. A playbook with only `metadata/keychain/workload/workflow/workbook` is valid.

Example:
```yaml
executor:
  profile: distributed
  version: noetl-runtime/2
  spec:
    result:
      store: { kind: nats_object, bucket: "noetl-results" }
    http:
      timeout: { connect: 10, read: 60 }
```


## 2.A Conformance note (examples)

Playbooks MAY include `executor` or omit it entirely.
If present, `executor` should look like:

```yaml
executor:
  profile: distributed
  version: noetl-runtime/2
```

Credentials MUST be declared via root `keychain:` (not under `executor`).

## 3) Normalization (MUST)

### 3.1 Normalize `step.tool` to canonical labeled list
Input forms you MAY accept:
1) single task object
2) list of task objects
3) list of named task maps (recommended)

Runtime MUST normalize to:

```yaml
tool:
  - label1: { kind: ... }
  - label2: { kind: ... }
```

If label missing, generate stable labels by YAML order:
- `task_1`, `task_2`, …

Labels are used for:
- `jump` targets (`then.to`)
- event correlation
- `_task` runtime variable

### 3.2 Normalize `step.next` to canonical router object
Canonical `next` form:

```yaml
next:
  spec:
    mode: exclusive          # exclusive | inclusive (default exclusive)
    policy: {}               # reserved placeholders
  arcs:
    - step: some_step
      when: "{{ ... }}"
      args: { ... }
```

Do not implement `step.spec.next_mode`. Routing mode belongs to `next.spec.mode`.

---

## 4) Spec layering / precedence (MUST)

### 4.1 Merge order
Compute effective task spec as:

```
effective_task_spec = merge(
  kind_defaults,
  executor.spec,
  step.spec,
  loop.spec,     # if present
  task.spec
)
```

Merge semantics:
- Scalars: inner wins
- Maps: deep merge; inner wins on conflicts
- Lists: replace

### 4.2 Policy inheritance
- Task control directives exist only at **task.spec.policy.rules**.
- Non-task scopes may have `spec.policy` but MUST NOT include `do: retry/jump/break/fail/continue`.

---

## 5) Execution semantics (MUST)

### 5.1 Server-side: step admission + routing (Petri-net)

#### Step admission (server-side)
Admission rules live at: `step.spec.policy.admit.rules`.

Shape:
```yaml
spec:
  policy:
    admit:
      rules:
        - when: "{{ ... }}"
          then: { allow: true }
        - else:
            then: { allow: false }
```

Semantics:
- Evaluated on the server before scheduling a step run.
- Inputs: `ctx`, `workload`, token `args`, and (if available) triggering boundary `event`.
- If admission resolves to false: step is not scheduled (token does not enter transition).
- If `admit` missing: default is allow.

#### Routing (server-side) via `step.next.arcs[]`
`next` is evaluated on the server when it receives a terminal boundary event from worker:
- `step.done`, `step.failed`, `loop.done` (and future boundary types)

Arc evaluation:
- Evaluate each `arc.when` (guard). Default true if omitted.
- If multiple arcs match, obey `next.spec.mode`:
  - `exclusive` (default): first matching arc wins (stable YAML order)
  - `inclusive`: all matching arcs fire (fan-out)

Arc payload:
- `arc.args` becomes token `args` for the target step (arc inscription).
- Merge rule: `args` from arc overwrites existing token args on conflicts (document it and keep deterministic).

**Hard rule:** the worker never enqueues steps. Only the server does, after evaluating arcs.

---

## 5.2 Worker-side: pipeline execution + task policy

### Pipeline lifecycle
Within a step run (or within a loop iteration run), the worker executes tasks sequentially, unless the server is running multiple iterations concurrently.

Each task:
1. Executes its tool `kind` producing a single final `outcome` envelope.
2. Evaluates `task.spec.policy.rules` to decide the directive (`do:`).
3. Applies directive to pipeline program counter.

### Outcome envelope (MUST)
Every tool kind must produce a stable outcome shape:

```json
{
  "status": "ok" | "error",
  "result": "<small result or reference>",
  "error": { "kind": "string", "retryable": true, "message": "string", "details": {} },
  "meta": { "attempt": 1, "duration_ms": 123, "ts": "..." }
}
```

Kind-specific stable fields (examples):
- HTTP: `outcome.http.status`, `outcome.http.headers`, `outcome.http.request_id`
- Postgres: `outcome.pg.code`, `outcome.pg.sqlstate`
- Python: `outcome.py.exception_type`

### Policy rule evaluation (MUST)
- Evaluate `rules` top-to-bottom.
- First matching `when` wins.
- `else` matches if nothing else matches.
- If policy omitted: ok→continue, error→fail.
- If policy exists but no match and no else: default continue.

`then` MUST include:
- `do: retry | jump | continue | break | fail`

Optional `then` fields:
- `attempts`, `backoff`, `delay` (retry)
- `to` (jump target label)
- `set_iter`, `set_ctx` (scoped patches)

---

## 6) Task control directives (MUST)

### `do: continue`
- Proceed to next task in the pipeline.
- `_prev` becomes the current task’s `outcome.result` (canonical).

### `do: skip`
- Do not execute the tool body (treat as a no-op for this task).
- Consider the task successful and proceed to the next task.
- `_prev` is unchanged unless you also apply `set_iter`/`set_ctx`.

### `do: retry`
- Re-run the same task.
- Attempt counter scoped to `(execution_id, step_run_id, iteration_id?, task_label)`.
- When attempts exhausted: directive becomes `fail` (canonical).
- Implement `delay` + `backoff`:
  - `none`: fixed delay
  - `linear`: delay * n
  - `exponential`: delay * 2^(n-1)

### `do: jump`
- Set next task pointer to label `then.to` (must exist).
- Jump remains within current step run / iteration scope.
- Used for pagination, storage routing, polling loops.

### `do: break`
- Ends current pipeline successfully.
- If inside loop iteration: completes that iteration.
- If no loop: completes the step run.

### `do: fail`
- Ends current pipeline with failure.
- If inside loop iteration: marks iteration failed.
- Step failure semantics (fail-fast vs best-effort) are a step policy placeholder; default is fail-fast (one iteration failure fails the step) unless you explicitly implement best-effort.

---

## 7) Data scopes (MUST)

### 7.1 `workload` (immutable)
- Merge once at execution start.
- Never mutate.

### 7.2 `ctx` (execution-scoped mutable context)
- `set_ctx` writes patches.
- Persist patches as events.
- In parallel loops, enforce safety until reducers/atomics exist:
  - write-once per key OR append-only OR reject conflicts (pick and enforce).

### 7.3 `iter` (iteration-scoped mutable scratchpad)
- Always safe (isolated per iteration).
- Use `set_iter` for pagination counters, status routing, etc.

### 7.4 Nested loops
Implement parent chain addressing:
- `iter` = current iteration
- `iter.parent` = outer iteration
- `iter.parent.parent` for deeper nesting

---

## 8) Loop implementation (MUST)

- Loop is a step modifier at `step.loop`.
- Server schedules iterations; workers execute pipelines per iteration.

Canonical loop shape:
```yaml
loop:
  in: "{{ workload.items }}"
  iterator: item
  spec:
    mode: sequential | parallel
    max_in_flight: 10
    policy:
      exec: distributed | local
```

Distributed vs local:
- If `exec: distributed`, server MAY schedule iterations across worker pools.
- Regardless, each iteration’s pipeline is a single logical thread (single worker lease).

---

## 9) Streaming pagination inside a loop (MUST)

Implement ordered streaming pipelines per iterator item:

- fetch page → transform → store → paginate decision → jump back to fetch

Mechanism:
- `jump` to `fetch_page` with `set_iter.page += 1`
- `break` when done
- route storage based on response code via `jump` to different storage tasks

This must coexist with outer parallel/distributed loops (cities/hotels in parallel, rooms paged sequentially per hotel).

---

## 10) Result storage (reference-first) (MUST)

- No “sink” kind.
- Storage is just tools returning references.
- Enforce payload size limits: large results MUST be stored externally and replaced with references.

Reference object recommendation:
`{ store, key, checksum, size, schema_hint }`

---

## 11) Events (MUST minimal set)

Server persists:
- `playbook.execution.requested`
- `playbook.request.evaluated`
- `workflow.started`
- `step.scheduled`
- `next.evaluated`
- `workflow.finished`
- `playbook.processed`

Worker emits:
- `step.started`
- `task.started`
- `task.done` (includes outcome or references)
- `step.done` / `step.failed`
- `loop.iteration.*` and `loop.done` (when loop present)

All events must include stable ids:
`execution_id`, `step_run_id`, `task_run_id`, `iteration_id`, `task_label`, `attempt`.

---

## 12) Linter/validator rules (MUST)

Reject:
- `expr`
- any `step.when` field
- task policy not an object with `rules`
- any rule missing `then.do`
- jump to unknown task label
- duplicate task labels
- invalid `next` structure (must be router object with `spec` + `arcs`)
- root `vars`

Warn:
- step has neither tool nor next
- `set_ctx` from parallel iterations (unless explicitly permitted)
- missing `else` in task rules (optional but recommended)

---

## 13) Acceptance tests (write these first)

1) Policy validation: reject non-object policy; reject missing `then.do`
2) Retry: transient HTTP 500 retries N times then fails
3) Jump routing: 404 → store_404, 200 → store_200
4) Streaming pagination: `has_more` jumps back; ends with `break`
5) Parallel loop: `max_in_flight` enforced; `iter` isolated
6) Nested loops: outer parallel; inner pagination sequential per item (`iter.parent` works)
7) Next routing: `next.spec.mode` exclusive vs inclusive
8) Result references: events stay under payload limit; large results stored externally

---

## 14) Implementation checklist

### Server (control plane)
- Parse/validate playbook; normalize task labels and next router
- Merge workload + request payload
- Evaluate `step.spec.policy.admit.rules` for tokens
- Schedule loop iterations (parallel + optional distributed)
- Receive worker events; persist to event log
- Evaluate `next.arcs[].when` under `next.spec.mode`
- Enqueue next step tokens with `arc.args`

### Worker (data plane)
- Claim step/iteration run lease
- Execute tasks in order
- Produce canonical `outcome` envelope (with kind-specific fields)
- Apply `task.spec.policy.rules` to drive retry/jump/break/fail/continue
- Maintain `_prev`, `_task`, `_attempt`; maintain `iter` (and `iter.parent`)
- Emit task/step/loop events to server

### Shared
- Spec merge engine (deep merge with precedence)
- Jinja2 templating for all `when` expressions and templated fields
- Validator/linter enforcing canonical constraints

---
