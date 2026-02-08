# Core Concepts (Canonical v10)

NoETL is a lightweight, event-driven orchestration engine built on an **event-sourced** execution model. You author playbooks in YAML, the **server (control plane)** schedules step runs, and **workers (data plane)** execute pipelines and report events for persistence and replay.

This document is aligned with the **Canonical v10** DSL model:

- Root playbook sections: **metadata, keychain (optional), executor (optional), workload, workflow, workbook (optional)**
- Step = **admission policy + tool pipeline + next router (Petri-net arcs)**
- Retry/pagination/polling are expressed via **task policy rules** (`task.spec.policy.rules`) inside the pipeline
- Results are **reference-first**; “sink” is a **pattern**, not a tool kind
- `when` is the only conditional keyword (policies + arcs)
- No legacy `eval`/`expr`, no `case`, no `vars`, no `step.when`
- Runtime scopes: `workload` (immutable), `keychain` (resolved, read-only), `ctx` (execution), `iter` (iteration), `args` (token payload), plus pipeline locals (`_prev`, `_task`, `_attempt`, `outcome`)

---

## 1) Architecture Roles

### Server (control plane)
- Exposes APIs used by UI/CLI and receives worker events.
- Resolves and validates playbooks.
- Resolves root `keychain` before execution (implementation-defined providers).
- Merges playbook workload defaults with execution request payload → immutable `workload` for the execution.
- Evaluates **step admission** via `step.spec.policy.admit.rules` (server-side gate).
- Routes execution using **Petri-net arcs** via `step.next.spec` + `step.next.arcs[].when`.
- Persists the append-only **event log** and builds projections for querying.

### Worker pools (data plane)
- Pure background worker pool (**no HTTP endpoints**).
- Lease step-run commands from the queue.
- Execute `step.tool` pipelines deterministically on a single worker per step run.
- Apply **task policy rules** (`task.spec.policy.rules`) for `retry/jump/break/fail/continue`.
- Emit task/step/loop events back to the server.

### CLI
- Manages server lifecycle and worker pools.
- Triggers executions and inspects logs/events.

---

## 2) Playbook Sections (Root)

A playbook document contains only these root sections:

- **metadata** – identifies the playbook (`name`, `path`, optional `version`, `description`, labels)
- **keychain** *(optional but recommended)* – credential declarations resolved before execution (read-only in templates as `keychain.<name>...`)
- **executor** *(optional)* – selects runtime mode/pool (`kind` + `spec`)
- **workload** – immutable default inputs merged with execution payload overrides
- **workflow** – list of steps (graph via `step.next` arcs)
- **workbook** *(optional)* – catalog of named reusable tasks/templates (optional baseline)

> **Important:** root `vars` MUST NOT exist. Runtime mutation happens via `ctx` and (inside loops) `iter`.

All values may use **Jinja2 templating** to reference `workload`, `keychain`, `args`, `ctx`, `iter`, and pipeline locals.

---

## 3) Step Behavior (Canonical)

### 3.1 Steps are transitions (Petri-net)
Steps live in `workflow` and are uniquely named by `step:`.

A canonical step is:
- **Admission policy** (server): `step.spec.policy.admit.rules`
- **Ordered pipeline** (worker): `step.tool` (labeled task list)
- **Router** (server): `step.next` (`next.spec` + `next.arcs[]`)

### 3.2 `tool` is always an ordered pipeline
Canonical pipeline form:

```yaml
- step: fetch_transform_store
  tool:
    - fetch:
        kind: http
        method: GET
        url: "{{ workload.api_url }}/data"
        spec:
          policy:
            rules:
              - when: "{{ outcome.status == 'error' and outcome.http.status in [429,500,502,503,504] }}"
                then: { do: retry, attempts: 5, backoff: exponential, delay: 2 }
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then: { do: continue }

    - transform:
        kind: python
        args: { data: "{{ _prev }}" }
        code: |
          result = transform(data)

    - store:
        kind: postgres
        auth: pg_k8s
        command: "INSERT INTO ..."
  next:
    spec: { mode: exclusive }
    arcs:
      - step: end
        when: "{{ event.name == 'step.done' }}"
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

## 4) Task Outcome Policy (`task.spec.policy.rules`)

Retry, pagination, and conditional pipeline control are expressed per tool task using **policy rules**.

```yaml
- fetch:
    kind: http
    url: "..."
    spec:
      policy:
        rules:
          - when: "{{ outcome.status == 'error' and outcome.error.retryable }}"
            then: { do: retry, attempts: 5, backoff: exponential, delay: 1.0 }
          - when: "{{ outcome.status == 'error' }}"
            then: { do: fail }
          - else:
              then: { do: continue }
```

Actions:
- `continue`, `retry`, `jump`, `break`, `fail`

Defaults if `spec.policy` is omitted:
- success → `continue`
- error → `fail`

---

## 5) Routing (`step.next`) and fan-out (`next.spec.mode`)

A step’s `next` router defines outgoing transitions (arcs). Each arc may have a guard and payload:

```yaml
next:
  spec: { mode: exclusive }
  arcs:
    - step: success
      when: "{{ event.name == 'step.done' and ctx.ok == true }}"
      args: { id: "{{ ctx.last_id }}" }
    - step: failure
      when: "{{ event.name == 'step.done' and ctx.ok != true }}"
```

`next.spec.mode` controls selection:
- `exclusive` (default): first matching arc fires (ordered)
- `inclusive`: all matching arcs fire (fan-out)

`next.arcs[]` are evaluated by the **server** after terminal step events (`step.done`, `step.failed`, `loop.done`).

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
