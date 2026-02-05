# NoETL Canonical DSL + Runtime Specification (Implementation Prompt)

**Purpose:** This document is the single source of truth for implementing the next iteration of NoETL DSL + runtime execution.  
It is written as an **implementation prompt** suitable for coding agents (Copilot / GPT / Claude).

## Non‑negotiable decisions (final)

- **No `pipe:`** construct. A `step.tool` list is always an ordered pipeline.
- **No step-level `case: when: then:` for normal execution flow.**
  - Canonical step = **`when + tool(pipeline) + next`**.
  - `case` may exist later as an advanced feature, but is **not required** for this canonical baseline.
- **Tool-level `eval: - expr:`** is the *only* mechanism for retry/jump/break/fail/continue inside a pipeline.
- **All execution semantics + policy live under `spec`** (step/tool/loop/next scopes).
- **Loop uses `spec` too** and introduces **iteration-scoped `iter`** to avoid overwrites, especially in parallel mode.
- In **parallel loops**, writes MUST be **iteration-scoped by default**; shared writes require explicit intent (reducers/atomics optional).
- **Control plane vs data plane split:**
  - **Server** routes tokens, evaluates `step.when` and `next[].when`, and persists event log.
  - **Worker** executes step pipelines, evaluates tool `eval`, and emits events.
- **Results are reference-first:** event log should not carry large payloads by default.

---

## 1. Runtime model (Petri net + state machine)

### 1.1 Token
A **token** represents “permission + payload” to attempt a step.

Token envelope (minimum):
- `execution_id`
- `catalog_id` (or `path + version`)
- `step` (target step name)
- `args` (arc inscription payload)
- optional: `parent_execution_id`, `event_id`, `parent_event_id`, `trace_id`

Tokens are created by:
- initial execution request (start token)
- firing of `next[]` arcs

### 1.2 Step = Petri transition
A step consumes one input token and produces zero or more output tokens.

Canonical mapping:
- `step.when` → transition enable guard
- `step.tool` → transition firing work (ordered pipeline)
- `step.next[]` → outgoing arcs (tokens emitted to downstream steps)

### 1.3 Determinism requirements
- Each `step_run_id` must be executed by **a single worker owner (lease)**.
- `tool.eval` is evaluated **top‑down, first match wins** (exclusive).
- `next[]` evaluation is deterministic via ordering + `step.spec.next_mode`.

---

## 2. Canonical DSL

### 2.1 Step canonical form

```yaml
- step: <name>
  desc: <optional>

  spec:
    next_mode: exclusive | inclusive   # default: exclusive
    # optional future:
    # timeout: <seconds>
    # lease: { heartbeat, ttl, mode }

  # Transition enable guard (evaluated by server on input token)
  when: "{{ <expr> }}"                 # default true if omitted

  # Optional loop wrapper (wraps the step body)
  loop:
    spec:
      mode: sequential | parallel      # default sequential
      # optional:
      # max_in_flight: <int>
    in: "{{ <collection expr> }}"
    iterator: <name>                  # binds iter.<iterator>

  # Step body: ordered pipeline (NO pipe construct)
  tool:
    - <task_label_1>:
        kind: <tool_kind>
        spec: { ... }                 # tool runtime policy
        ...tool inputs...
        eval: [ ... ]                 # tool outcome -> directive list
    - <task_label_2>: { ... }

  # Outgoing arcs (evaluated by server on terminal events)
  next:
    - step: <next_step>
      spec: { ... }                   # optional edge semantics
      when: "{{ <expr> }}"            # default true if omitted
      args: { ... }                   # token payload
```

---

## 3. Scopes and variables

### 3.1 `workload`
Immutable merged inputs for the execution (defaults + request payload).

### 3.2 `args`
Token payload delivered to a step (`next[].args` inscription).

### 3.3 `ctx` (execution scope)
Mutable **playbook execution instance** context shared across steps.

- `ctx` is the place for long-lived state (session state, counters, references to stored results, correlation ids, etc.).
- Updates to `ctx` MUST be recorded as event-sourced **patch events** (do not snapshot huge objects in every event).
- `ctx` is read/write via `set_ctx` from tools/eval directives (see §6).

### 3.4 `vars` (step scope)
Mutable state local to a **single step run**.

- Safe in sequential loop mode.
- In a loop iteration, prefer writing to `iter` instead of `vars`.
- In **parallel loop mode**, `vars` is considered **shared**; writes to it MUST require explicit intent (see `set_shared`), otherwise they SHOULD be rejected or treated as iteration-scoped (implementation choice must be deterministic).

### 3.5 `iter` (iteration scope)
Exists only during a loop iteration. **Isolated per iteration**.

### 3.5 `iter` (iteration scope)
Exists only during a loop iteration. **Isolated per iteration**.
- `iter.<iterator>` binds current element (e.g., `iter.endpoint`)
- `iter.index` iteration index
- `iter.*` is used for pagination state (`page`, `has_more`, etc.)

### 3.6 Pipeline locals
- `_prev` → previous task output (pipeline-local)
- `_task` → current task label
- `_attempt` → attempt counter for current task

### 3.7 Visibility rules
- `iter.*` is visible only within the iteration.
- `ctx.*` is visible across steps and to `next[].when`.
- `vars.*` is visible throughout the step run and to `next[].when`.
- Cross-step state should be passed via `next[].args`, written to `ctx`, or referenced via storage refs.

---

## 4. Tool outcome envelope (`outcome`)

Every tool produces exactly one final outcome:

- `outcome.status`: `"success"` | `"error"`
- `outcome.result`: output object (success)
- `outcome.error`: error object (error)
- `outcome.meta`: attempt, duration, trace, timestamps

Optional kind helpers:
- HTTP: `outcome.http.status`, `outcome.http.headers`
- Postgres: `outcome.pg.code`, `outcome.pg.message`
- Python: `outcome.py.exception` (optional)

---

## 5. Tool runtime policy (`tool.spec`)

All tool execution knobs live under `tool.spec`.
Examples:
- timeouts (connect/read)
- pooling, concurrency caps
- internal retry policy (optional)
- resource hints / sandbox settings

**Order of application:**
1. Tool executes using `tool.spec` (including optional internal retry)
2. Tool emits one final `outcome`
3. Pipeline evaluates `tool.eval` on that `outcome`

---

## 6. Tool-level flow control (`tool.eval`)

### 6.1 Syntax

```yaml
eval:
  - expr: "{{ <boolean expression> }}"
    do: continue | retry | jump | break | fail
    attempts: <int>                # retry
    backoff: fixed | linear | exponential
    delay: <seconds|expr>          # retry
    to: <task_label>               # jump
    set_iter: { ... }              # writes to iter scope
    set_vars: { ... }              # writes to step-local vars scope
    set_ctx: { ... }               # writes to execution-wide ctx scope
    set_shared: { ... }            # explicit shared write (reducers/atomics; optional feature)
    set_prev: <value>              # override _prev
  - else:
      do: continue
```

### 6.2 Directive semantics
- `continue`: `pc := pc + 1`
- `retry`: rerun same task with attempt++ (bounded by `attempts`)
- `jump`: `pc := index(to)`
- `break`: end step body successfully (emit `step.done`)
- `fail`: end step with failure (emit `step.failed`)

### 6.3 Default behavior if `eval` omitted
If `tool.eval` is missing (or no match + no else):
- success → `continue`
- error → `fail`

This is the safe Rust-like default.

### 6.4 Determinism
- Evaluate eval entries **top-down**
- **First match wins**
- YAML order defines precedence

---

## 7. Pipeline execution (worker)

Worker runs `step.tool` as an instruction list with:
- `pc` (program counter)
- `_prev`
- `attempts[label]`

Loop:
1. Execute task at `pc`
2. Build `outcome`
3. Emit tool events
4. Evaluate `tool.eval` → directive
5. Apply directive (continue/retry/jump/break/fail)
6. Terminate on break/fail/end-of-list

End-of-list (pc past end) → `step.done`.

---

## 8. Loop execution (`loop.spec`)

### 8.1 Sequential (default)
- Run one iteration at a time.
- Direct writes to `vars` are allowed.

### 8.2 Parallel
- Run iterations concurrently up to `loop.spec.max_in_flight`.
- Each iteration has isolated `iter`.
- In parallel mode, **iteration-scoped writes are safe** (`set_iter`).
- Writes to step-shared `vars` MUST require explicit intent (e.g., `set_shared` reducers/atomics) or be deterministically mapped to iteration scope.

### 8.3 Loop terminal event
After all iterations complete, worker emits `loop.done`.

---

## 9. Step enable guard (`step.when`) (server)

Server evaluates `step.when` when scheduling/routing tokens.

Available inputs:
- `token.args`
- `workload`
- execution metadata
- optionally server-known results/refs

Default if omitted: `true`.

---

## 10. Transitions (`next[]`) (server)

### 10.1 Ownership
Server evaluates `next[]` after receiving terminal step events (`step.done`, `step.failed`, `loop.done`).

### 10.2 Selection (`step.spec.next_mode`)
- `exclusive` (default): first matching `next[]` fires (ordered)
- `inclusive`: all matching `next[]` fire (fan-out)

### 10.3 Arc inscription (`next[].args`)
When a next arc fires, server computes `args` and creates a token for the target step.

---

## 11. Event sourcing requirements

### 11.1 Minimum event set (names are illustrative)
- `playbook.execution_requested`
- `workflow.started`
- `step.started`
- `task.started`
- `task.processed` (includes `outcome`, task label, attempt)
- `step.done` / `step.failed`
- `loop.started` / `loop.iteration.started` / `loop.iteration.done` / `loop.done`
- `workflow.finished`

### 11.2 Payload rule
Do not store huge bodies in events. Store references.

---

## 12. Result storage (reference-first)

- Store large tool results externally (Postgres table, object store, NATS object store, etc.).
- Events store metadata + reference objects:
  `{ store, key, checksum, size, schema_hint }`
- A “sink” is a pattern: any tool task that writes data to external storage and returns a reference (there is no sink tool kind)..

---

## 12.1 Execution context (`ctx`) vs workload

- `workload` is **immutable** execution input (defaults + request payload).
- `ctx` is **mutable** execution state shared across steps.
- Recommended precedence for reads: `args` (step input) → `ctx` (execution state) → `workload` (defaults).
- Recommended write targets:
  - per-iteration state → `iter`
  - per-step transient state → `vars`
  - cross-step state / shared refs → `ctx`

---

## 13. Canonical pagination pattern

Within a loop iteration:
1) fetch page → set `iter.has_more`, `iter.page`, `iter.items`
2) save page (sink)
3) paginate task:
   - if `iter.has_more` → `jump` to fetch and increment `iter.page`
   - else → `break` (iteration done)

---

## 14. Example: loop + pagination + sink

```yaml
- step: fetch_all_endpoints
  spec:
    next_mode: exclusive

  when: "{{ true }}"

  loop:
    spec: { mode: sequential }
    in: "{{ workload.endpoints }}"
    iterator: endpoint

  tool:
    - init:
        kind: noop
        eval:
          - else:
              do: continue
              set_iter: { page: 1, has_more: true }

    - fetch_page:
        kind: http
        spec:
          timeout: { connect: 5, read: 15 }
        method: GET
        url: "{{ workload.api_url }}{{ iter.endpoint.path }}"
        params:
          page: "{{ iter.page }}"
          pageSize: "{{ iter.endpoint.page_size }}"
        eval:
          - expr: "{{ outcome.status == 'error' and outcome.http.status in [429,500,502,503,504] }}"
            do: retry
            attempts: 10[...]
          - expr: "{{ outcome.status == 'error' }}"
            do: fail
          - else:
              do: continue
              set_iter:
                has_more: "{{ outcome.result.data.paging.hasMore | default(false) }}"
                page: "{{ outcome.result.data.paging.page | default(iter.page) }}"
                items: "{{ outcome.result.data.data | default([]) }}"

    - save_page:
        kind: postgres
        spec: { timeout: 30 }
        auth: pg_k8s
        command: |
          INSERT INTO pagination_test_results (...)
        eval:
          - expr: "{{ outcome.status == 'error' and outcome.pg.code in ['40001','40P01'] }}"
            do: retry
            attempts: 5
            backoff: exponential
            delay: 2.0
          - expr: "{{ outcome.status == 'error' }}"
            do: fail
          - else:
              do: continue

    - paginate:
        kind: noop
        eval:
          - expr: "{{ iter.has_more == true }}"
            do: jump
            to: fetch_page
            set_iter:
              page: "{{ (iter.page | int) + 1 }}"
          - else:
              do: break

  next:
    - step: validate_results
      when: "{{ event.name == 'loop.done' }}"
    - step: cleanup
      when: "{{ event.name == 'step.failed' }}"
```

---

## 15. Implementation checklist (do this)

### 15.1 Parser / schema
- Remove `pipe` support.
- Parse `step.tool` as ordered list of labeled tasks.
- Support `spec` at step/tool/loop/next.
- Implement `tool.eval` with `expr` + `else`.

### 15.2 Worker runtime
- Implement `PipelineRunner` with `pc`, `_prev`, attempts.
- Execute tool using `tool.spec` policies.
- Produce `outcome` envelope.
- Evaluate `tool.eval` (top-down first match) → directive.
- Apply directive (continue/retry/jump/break/fail).
- Implement loop wrapper with isolated `iter` per iteration.
- Enforce parallel scoping: `set_iter` is always safe; shared writes require explicit intent (`set_shared`) or deterministic mapping.

### 15.3 Server runtime
- Evaluate `step.when` for token eligibility.
- On terminal events, evaluate `next[]` with `step.spec.next_mode`.
- Emit next tokens with computed `args`.
- Persist all events in event log.

---

## 16. Defaults (must be enforced)
- `step.when`: true if omitted
- `step.spec.next_mode`: exclusive if omitted
- `loop.spec.mode`: sequential if omitted
- `tool.eval` omitted: success→continue, error→fail
- `tool.eval` present but no match/no else: same default

---

## 17. Acceptance criteria (done = done)
Implementation is conformant if:
1) `pipe` is not required or supported in fixtures.
2) Tool eval controls retry/jump/break deterministically.
3) Loop iterations isolate `iter` state; parallel mode cannot overwrite shared vars by default.
4) Server routes tokens using `next[]` and `step.spec.next_mode`.
5) Event log stores outcomes + refs, not huge bodies.
