---
sidebar_position: 20
title: DSL Analysis and Evaluation (Canonical v10)
description: Comprehensive analysis of NoETL DSL under Canonical v10 semantics (policies, tasks pipelines, Petri-net routing, loops, result references)
---

# NoETL DSL Analysis and Evaluation — Canonical v10

This document updates the prior DSL analysis to match **Canonical v10** semantics:

- **No `case` blocks** (deprecated in Canonical v10).
- **No special `sink`** concept (storage is just normal tool tasks that write data and return references).
- **No `retry` block** as a DSL construct (retry is implemented via **task policy** decisions over attempts).
- Step execution is an ordered **task pipeline** (a task is a named tool invocation).
- Routing is expressed as Petri-net **arcs** under `step.next`, evaluated by the **server/control-plane**.
- Large results are **reference-first** (ResultRef / ManifestRef), with optional extracted fields.

This is an **analysis/whitepaper-style** document (not the formal grammar).

---

## 1) DSL Control Flow Model (Canonical v10)

### 1.1 Core execution semantics

In Canonical v10, a workflow is an event-sourced Petri-net-like machine:

1. **Server** holds authoritative state (event log + projections).
2. **Step admission** is evaluated by `step.spec.policy.admit.rules` on the server.
3. **Workers** execute the step's **task pipeline** (tools) in an isolated runtime.
4. Each task produces a single final **outcome** (after its internal knobs, and across attempts if policy requests retry).
5. The server evaluates **routing arcs** (`step.next`) to schedule subsequent steps.

**Canonical step structure (conceptual)**
```yaml
- step: fetch_transform_store
  spec:
    policy:
      admit:
        rules: [ ... ]         # server-side admission (optional)
  loop:                         # optional (server-managed)
    spec: { mode: parallel }
    in: "{{ workload.endpoints }}"
    iterator: endpoint
  tool:                         # ordered task pipeline (worker)
    - fetch_page:   { kind: http, ... }
    - transform:    { kind: python, ... }
    - store:        { kind: postgres, ... }
  next:                         # Petri-net arcs (server routing)
    spec: { mode: exclusive }
    arcs:
      - step: next_step
        when: "{{ event.name == 'step.done' }}"
        args: { ... }
```

### 1.2 Event-driven but policy-centric (no `case`)

Older DSL versions used `case/when/then` to react to step and tool events.

Canonical v10 replaces that with **policy rules**:
- Step admission policy: `step.spec.policy.admit.rules`
- Task outcome policy: `task.spec.policy.rules`
- Next routing policy: `step.next.spec.mode` + `step.next.arcs[]` conditions

This avoids mixing “run work” (tools) with “route tokens” (arcs).

---

## 2) Task Pipelines (tools as ordered tasks)

### 2.1 Task pipeline is the default control structure

A step’s `tool:` value is an ordered sequence of tasks:
- each task is a **named tool invocation**
- the output of the previous task is accessible via `_prev` (canonical threading)
- tasks can update `iter` (iteration-local) or `ctx` (execution-local) through policy actions

### 2.2 Error handling and retry belong to `task.spec.policy`

Canonical v10 models retry as repeated **attempts** of the same task run:

- worker executes attempt #1
- if the outcome matches a policy rule with `do: retry`, worker schedules attempt #2
- repeat until success or attempts exhausted
- final task emits `task.done` or `task.failed`

Example policy rules (conceptual):
```yaml
- fetch_page:
    kind: http
    spec:
      policy:
        rules:
          - when: "{{ outcome.status == 'error' and outcome.http.status in [429,500,502,503,504] }}"
            then: { do: retry, attempts: 10, backoff: exponential, delay: 2.0 }
          - when: "{{ outcome.status == 'error' and outcome.http.status in [401,403] }}"
            then: { do: fail }
          - else:
              then: { do: continue }
```

### 2.3 Storage is “just tools”

There is no special sink mechanism. To persist results you add storage tasks:
- `postgres` tool task (write rows / return ref)
- `gcs` tool task (write object / return ref)
- `nats_object` tool task (write object / return ref)
- etc.

A storage task typically returns a **ResultRef**.

---

## 3) Loop Semantics (server-managed, worker-executed)

### 3.1 Loop as multi-instance execution (fan-out)

`loop` is a step-level clause that the **server** expands into multiple step-runs (iterations).

- `mode: sequential` → one iteration at a time
- `mode: parallel` → many iterations concurrently (bounded by `max_in_flight`)
- An iteration receives its own **iteration scope** (`iter.*`), including `iter.<iterator>`

Workers execute the iteration body (the step’s task pipeline) in isolation.

### 3.2 Nested loops + streaming pipelines

Canonical v10 supports the common pattern:
- outer loops: fan out (cities, hotels) — can be parallel
- inner “pagination stream”: sequential within one iteration — must stay in one worker logical thread

This is modeled by a **task-level loop** pattern using policy + `jump/break`, or by an explicit `while/until` future clause (see §9).

---

## 4) Routing Semantics (Petri-net arcs)

### 4.1 Arcs are the routing mechanism

Canonical v10 routing is expressed via `step.next`:

- `step.next.spec.mode` controls fan-out:
  - `exclusive` (default): first matching arc wins
  - `inclusive`: all matching arcs fire (fan-out)
- `step.next.arcs[]` defines arcs with `when` guards and optional `args` payloads

Example:
```yaml
next:
  spec: { mode: exclusive }
  arcs:
    - step: validate_results
      when: "{{ event.name == 'loop.done' }}"
    - step: cleanup
      when: "{{ event.name == 'step.failed' }}"
```

### 4.2 Token semantics

- A **token** arrives at a step-run (place).
- Admission policy may suppress/skip execution.
- If admitted, the server schedules execution to worker(s).
- On completion, the server evaluates arcs to move tokens forward.

---

## 5) Result Semantics (reference-first)

### 5.1 Reference-first is mandatory for large payloads

Tool outcomes MUST store large bodies externally and attach only:
- ResultRef + extracted fields + small preview (optional)

This is essential for:
- pagination workloads (many pages)
- sensor/IoT streams
- quantum measurement datasets

### 5.2 Manifests for aggregation

Instead of merging large arrays into a single in-memory object, Canonical v10 uses manifests:
- a manifest lists part ResultRefs
- downstream steps can stream-resolve parts

---

## 6) Turing-Completeness Analysis (still YES)

A workflow language is effectively Turing-complete if it supports:
1. conditional branching
2. unbounded iteration
3. unbounded storage

Canonical v10 provides:

- **conditional branching**: `when` guards in policies and arcs
- **unbounded iteration**:
  - unbounded loop via backward routing arcs (server scheduling)
  - retry/polling loops via task policy (`do: retry`) and cursor/page updates
- **unbounded storage**:
  - external storage backends (Postgres/GCS/NATS Object Store)
  - reference passing via ResultRef

Additionally, `python` tools can perform arbitrary computation, making the system computationally complete for practical purposes.

---

## 7) BPMN 2.0 Coverage (updated)

| BPMN 2.0 Feature | Canonical v10 Status | How it maps |
|---|---|---|
| Sequence | ✅ Full | single arc in `next.arcs` |
| Parallel fork (AND-split) | ✅ Full | `next.spec.mode: inclusive` |
| Exclusive gateway (XOR) | ✅ Full | `next.spec.mode: exclusive` |
| Inclusive gateway (OR) | ✅ Full (explicit) | `next.spec.mode: inclusive` with guarded arcs |
| Parallel join (AND-join) | ⚠️ Pattern-based | join via step admission policy checking predecessor completion |
| Loops (multi-instance) | ✅ Full | `loop` |
| Error boundary | ✅ Full | arc guarded on `event.name == 'step.failed'` or policy fail outcome |
| Subprocess/call activity | ✅ Full | task kind calling another playbook / referenced workflow |
| Timer events | ❌ Missing (native) | future enhancement (see §9) |
| Human tasks | ❌ Missing (native) | future enhancement |
| Compensation | ❌ Missing | future enhancement |

**Key improvement over earlier DSL**: inclusive vs exclusive branching is now explicit via `next.spec.mode`.

---

## 8) Petri Net Coverage (updated mapping)

Canonical v10 is naturally Petri-net-like.

| Petri net element | NoETL Canonical v10 mapping |
|---|---|
| Place | step-run state (token position) |
| Transition | arc firing decision + scheduling |
| Token | execution token + scoped context |
| Arc | `step.next.arcs[]` |
| Colored tokens | `ctx`, `iter`, `workload` (data carried with token) |
| Transition guard | `when` expressions on arcs and policies |
| Multi-instance transition | `loop` expansion into multiple step-runs |

**Observation**: task pipelines are internal transitions inside a step-run; arcs move tokens between steps.

---

## 9) Design Recommendations (Canonical v10 forward path)

### 9.1 Add native `while` / `until` for streaming loops (future)
Canonical v10 already supports streaming pagination via policy jump/break patterns. A native clause would reduce errors:

- `while: "{{ iter.has_more }}"` (pre-check)
- `until: "{{ iter.has_more == false }}"` (post-check)

These should be available in the task pipeline scope (iteration-local), not as a global workflow construct.

### 9.2 Timer / await constructs (future)
Add:
- `sleep: "5s"` task (or policy delay action)
- `await:` step that blocks until an external event/callback

### 9.3 First-class join patterns (future)
Introduce an optional join helper to reduce manual admission policies:
- `join: { mode: all|any|n_of_m, steps: [...] }`

### 9.4 Stronger typing (future)
Type hints for extracted fields and ResultRef schema hints to improve tooling and validation.

---

## 10) Summary (Canonical v10)

- Canonical v10 is **cleaner and less ambiguous** than earlier versions:
  - tools run as an ordered task pipeline
  - policies handle outcomes and retries
  - arcs handle routing (exclusive/inclusive)
  - results are reference-first
- The model remains **Turing-complete** and maps well to workflow nets / Petri nets.
- Key missing BPMN primitives remain: timers, human tasks, compensation — good future additions.
