# Core Concepts (Canonical v2)

NoETL is a lightweight, event-driven orchestration engine built on an **event-sourced** execution model. You author playbooks in YAML, the **server (control plane)** schedules step runs, and **workers (data plane)** execute pipelines and report events for persistence and replay.

This document is aligned with the **canonical v2** model:

- Root playbook sections: **metadata, executor, workload, workflow, workbook**
- Step = **when (guard) + tool (ordered pipeline) + next (arcs)**
- Retry/pagination/polling use **tool-level `eval: expr`**, not step-level `retry:` / `case:`
- Results are **reference-first**; “sink” is a **pattern**, not a tool kind
- Runtime scopes: `workload` (immutable), `ctx` (execution), `vars` (step run), `iter` (iteration)

---

## 1) Architecture Roles

### Server (control plane)
- Exposes APIs used by UI/CLI and receives worker events.
- Resolves and validates playbooks.
- Merges playbook workload defaults with execution request payload → immutable `workload` for the execution.
- Routes execution using **tokens**, evaluating `step.when` and `next[].when`.
- Persists the append-only **event log** and builds projections for querying.

### Worker pools (data plane)
- Pure background worker pool (**no HTTP endpoints**).
- Lease step-run commands from the queue.
- Execute `step.tool` pipelines deterministically on a single worker per step run.
- Apply tool-level `eval` rules (retry/jump/break/fail/continue).
- Emit task/step/loop events back to the server.

### CLI
- Manages server lifecycle and worker pools.
- Triggers executions and inspects logs/events.

---

## 2) Playbook Sections (Root)

A playbook document contains only these root sections:

- **metadata** – identifies the playbook (`name`, `path`, optional `version`, `description`, labels)
- **executor** *(optional)* – selects runtime mode/pool (`kind` + `spec`)
- **workload** – immutable default inputs merged with execution payload overrides
- **workflow** – list of steps (graph via `next[]`)
- **workbook** *(optional)* – catalog of named reusable tasks/templates (optional baseline)

> **Important:** `vars` MUST NOT exist at playbook root. Runtime mutation happens via `ctx/vars/iter`.

All values may use **Jinja2 templating** to reference `workload`, `args`, `ctx`, `vars`, `iter`, and pipeline locals.

---

## 3) Step Behavior (Canonical)

### 3.1 Steps are transitions (Petri-net)
Steps live in `workflow` and are uniquely named by `step:`.

A step is defined by:
- `when`: enable guard (server-side; defaults to `true`)
- `tool`: ordered pipeline of tool tasks (worker-side; may be empty for pure routing)
- `next`: outgoing arcs (server-side routing)

### 3.2 `tool` is always an ordered pipeline
Canonical pipeline form:

```yaml
- step: fetch_transform_store
  tool:
    - fetch:
        kind: http
        url: "{{ workload.api_url }}/data"
    - transform:
        kind: python
        args: { data: "{{ _prev }}" }
        code: "result = transform(data)"
    - store:
        kind: postgres
        query: "INSERT INTO ..."
  next:
    - step: end
```

There is **no `pipe:` block**. The ordered list *is* the pipeline.

### 3.3 Tool kinds
Tool kinds are extensible, but common built-ins include:
- `http`, `postgres`, `duckdb`, `python`, `secrets`, `playbook`, `noop`

A `playbook` tool kind schedules another playbook execution (implementation-defined contract).

### 3.4 Iteration (`loop`)
A step may define `loop` to run the pipeline once per element.

```yaml
loop:
  spec:
    mode: sequential | parallel
  in: "{{ workload.items }}"
  iterator: item
```

Each iteration has isolated `iter.*` scope.

---

## 4) Tool-Level Flow Control (`eval`)

Retry, pagination, and conditional pipeline control are expressed per tool task using `eval`.

```yaml
- fetch:
    kind: http
    url: "..."
    eval:
      - expr: "{{ outcome.status == 'error' and outcome.error.retryable }}"
        do: retry
        attempts: 5
        backoff: exponential
        delay: 1.0
      - expr: "{{ outcome.status == 'error' }}"
        do: fail
      - else:
          do: continue
```

Actions:
- `continue`, `retry`, `jump`, `break`, `fail`

Defaults if `eval` is omitted:
- success → `continue`
- error → `fail`

---

## 5) Routing (`next[]`) and Fan-out (`spec.next_mode`)

A step’s `next[]` list defines outgoing transitions (arcs). Each arc may have a guard and payload:

```yaml
next:
  - step: success
    when: "{{ vars.ok == true }}"
    args: { id: "{{ ctx.last_id }}" }
  - step: failure
    when: "{{ vars.ok != true }}"
```

`spec.next_mode` controls selection:
- `exclusive` (default): first matching arc fires (ordered)
- `inclusive`: all matching arcs fire (fan-out)

`next[]` is evaluated by the **server** after terminal step events (`step.done`, `step.failed`, `loop.done`).

---

## 6) Results (Reference-First)

NoETL avoids stuffing large payloads into events.

- Large tool outputs should be stored externally (db/object/kv).
- Events and contexts carry **ResultRef** objects: `{ store, key, checksum, size, schema_hint, ... }`.

A “sink” is just a **pattern**:
- any tool task that persists data and returns a reference.

---

## 7) Typical Flow

1. **Author** — Write a playbook: define `metadata`, defaults in `workload`, optional `workbook`, and the step graph in `workflow`.
2. **Execute** — Run via CLI or API, optionally overriding parts of `workload` with request payload.
3. **Observe** — Workers execute pipelines and emit events; the server persists the event log and exposes execution state/projections.

