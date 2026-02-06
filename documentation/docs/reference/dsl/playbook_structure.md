---
sidebar_position: 3
title: Playbook Structure (Canonical)
description: Canonical NoETL playbook structure and section semantics for DSL v2 (Canonical v10)
---

# NoETL Playbook Structure Guide (Canonical v10)

This guide defines the **canonical** NoETL playbook document structure and how it maps to the runtime model.

Canonical runtime principles (v10):
- Step = **admission** (`step.spec.policy.admit`) + **tool pipeline** (`step.tool`) + **router** (`step.next` with Petri-net **arcs**)
- Retry/pagination/polling/branching inside a step are expressed via **task policy**: `task.spec.policy.rules`
- Result handling is **reference-first** (no special `sink` tool kind; “sink” is a pattern)
- Runtime scopes: `workload` (immutable), `ctx` (execution-scoped), `iter` (iteration-scoped), `args` (token payload), plus pipeline locals (`_prev`, `_task`, `_attempt`, `outcome`)

> **Non-canonical removals:** There is **no** playbook-root `vars`, **no** `step.when`, **no** tool-level `eval/expr`, and **no** `step.spec.next_mode`. Use `spec.policy` and `next.spec` instead.

---

## 1) Overview

A NoETL playbook is a YAML document that defines a workflow as a set of steps and transitions.

**Root sections are limited to:**
- `apiVersion`
- `kind`
- `metadata`
- `keychain` (optional but recommended)
- `executor` (optional)
- `workload`
- `workflow`
- `workbook` (optional)

**Root restrictions (canonical):**
- `vars` MUST NOT appear at playbook root level.
- If credentials are referenced by name (for example `auth: pg_k8s`), they SHOULD be declared under root `keychain`.
- Any runtime knobs MUST be expressed under `spec` at their respective scope.

---

## 2) Basic structure (canonical v10)

```yaml
apiVersion: noetl.io/v2
kind: Playbook

metadata:
  name: example_playbook
  path: workflows/example_playbook
  version: "2.0"
  description: Example playbook using canonical v10 structure

keychain:
  - name: pg_k8s
    kind: postgres_credential

executor:
  kind: distributed
  spec:
    pool: default

workload:
  api_url: "https://api.example.com"
  page_size: 50

workflow:
  - step: start
    desc: Entry transition (pure routing)
    next:
      spec: { mode: exclusive }
      arcs:
        - step: fetch_transform_store

  - step: fetch_transform_store
    desc: Fetch → transform → store
    tool:
      - fetch_page:
          kind: http
          method: GET
          url: "{{ workload.api_url }}/data"
          params:
            page: 1
            pageSize: "{{ workload.page_size }}"
          spec:
            timeout: { connect: 5, read: 15 }
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
            result = {"items": data}

      - store:
          kind: postgres
          auth: pg_k8s
          command: "INSERT INTO ..."
          spec:
            policy:
              rules:
                - when: "{{ outcome.status == 'error' and outcome.pg.code in ['40001','40P01'] }}"
                  then: { do: retry, attempts: 5, backoff: exponential, delay: 2 }
                - when: "{{ outcome.status == 'error' }}"
                  then: { do: fail }
                - else:
                    then: { do: continue }

    next:
      spec: { mode: exclusive }
      arcs:
        - step: end
          when: "{{ event.name == 'step.done' }}"

  - step: end
    desc: Terminal transition
    tool:
      - done:
          kind: noop
```

---

## 3) Metadata

The `metadata` section describes the playbook itself.

Typical fields:
- `name` (required)
- `path` (required)
- `version` (recommended)
- `description` (recommended)
- `tags`, `labels` (optional)

Example:

```yaml
metadata:
  name: amadeus_ai_api
  path: api_integration/amadeus_ai_api
  version: "2.0"
  description: Complete Amadeus AI travel API integration
  tags: [api, travel, llm]
```

---

## 4) Executor (optional)

`executor` configures **where and how** the playbook is executed (local vs distributed, worker pool selection, queue backend, etc.).

The section MUST follow the pattern:

```yaml
executor:
  kind: distributed | local | hybrid
  spec: { ... }
```

Executor knobs may be inherited by lower scopes via `spec` merge precedence (see §6.4).

---

## 5) Workload (immutable input)

`workload` provides default inputs and configuration for the playbook.

At runtime, the server merges:
1) playbook `workload` defaults
2) execution request payload overrides

This merged workload is immutable and available as `workload.*` in templates.

---

## 6) Workflow (steps and routing)

`workflow` is a list of steps. Steps form a directed graph using `next.arcs[]`.

### 6.1 Step = transition (Petri-net)
In canonical v10 there are no special step “types” like `start`, `end`, `condition`.
Instead, behavior is expressed with:
- **Admission**: `step.spec.policy.admit.rules` (server-side)
- **Execution**: `step.tool` ordered pipeline (worker-side)
- **Routing**: `step.next.spec.mode` + `step.next.arcs[].when` (server-side)

### 6.2 Step admission (`step.spec.policy.admit`)
Admission is evaluated by the **server** before scheduling a step run.

```yaml
- step: do_work
  spec:
    policy:
      admit:
        rules:
          - when: "{{ args.enabled == true }}"
            then: { allow: true }
          - else:
              then: { allow: false }
  tool: ...
```

If admission policy is omitted, the step defaults to **allow**.

### 6.3 Tool pipeline (`step.tool`)
A step may contain a `tool` list which is an **ordered pipeline** of labeled tasks.

- The worker executes tasks top-to-bottom.
- `_prev` threads previous task output to the next task (canonical: `_prev = outcome.result`).
- Each task may define `task.spec.policy.rules` to control execution flow inside the pipeline:
  - `retry`, `jump`, `continue`, `break`, `fail`

### 6.4 Spec precedence (canonical)
`spec` MAY be defined at multiple levels. Inner scopes override outer scopes on overlap.

Recommended precedence for effective task configuration:

`kind defaults` → `executor.spec` → `step.spec` → `loop.spec` → `task.spec`

### 6.5 Routing (`step.next` router with arcs)
`next` is a router object that owns routing mode and the arc list.

```yaml
next:
  spec:
    mode: exclusive | inclusive   # default exclusive
  arcs:
    - step: success
      when: "{{ event.name == 'step.done' }}"
      args: { ... }               # token payload
    - step: failure
      when: "{{ event.name == 'step.failed' }}"
```

If multiple arcs match:
- `exclusive`: first matching arc fires (stable YAML order)
- `inclusive`: all matching arcs fire (fan-out)

### 6.6 Loop (fan-out and iteration)
A step may define `loop` to repeat its pipeline over a collection.

```yaml
- step: per_endpoint
  loop:
    spec:
      mode: parallel
      max_in_flight: 10
    in: "{{ workload.endpoints }}"
    iterator: endpoint
  tool:
    - fetch:
        kind: http
        url: "{{ workload.api_url }}{{ iter.endpoint.path }}"
```

In `parallel` loop mode:
- each iteration has isolated `iter.*`
- cross-step writes via `set_ctx` must be restricted until reducers/atomics exist

---

## 7) Runtime scopes vs document fields

These are **runtime scopes** available during evaluation (NOT playbook root keys):

- `workload.*` — immutable merged input
- `ctx.*` — execution-scoped mutable context (event-sourced patches)
- `iter.*` — loop iteration scoped state (isolated per iteration)
- `args.*` — token payload from `next.arcs[].args`
- Pipeline locals:
  - `_prev` — previous task output
  - `_task` — current task label
  - `_attempt` — current attempt number
  - `outcome` — tool outcome envelope (within task policy evaluation)
  - `event` — boundary event envelope (within routing evaluation)

---

## 8) Workbook (optional)

`workbook` is optional and reserved for a catalog of named reusable tasks/templates.
It is not required for the canonical baseline and may be introduced gradually.

Example placeholder:

```yaml
workbook:
  tasks:
    fetch_assessments:
      kind: http
      method: GET
      url: "{{ workload.api_url }}/api/v1/assessments"
```

---

## 9) Common patterns (canonical)

### 9.1 Retry (task policy)
```yaml
- fetch:
    kind: http
    url: "{{ workload.api_url }}/data"
    spec:
      policy:
        rules:
          - when: "{{ outcome.status == 'error' and outcome.http.status in [429,500,502,503,504] }}"
            then: { do: retry, attempts: 10, backoff: exponential, delay: 2 }
          - when: "{{ outcome.status == 'error' }}"
            then: { do: fail }
          - else:
              then: { do: continue }
```

### 9.2 Pagination (jump + iter state)
```yaml
- paginate:
    kind: noop
    spec:
      policy:
        rules:
          - when: "{{ iter.has_more == true }}"
            then:
              do: jump
              to: fetch_page
              set_iter:
                page: "{{ (iter.page | int) + 1 }}"
          - else:
              then: { do: break }
```

### 9.3 “Sink” (pattern, not a tool kind)
A sink is a storage-writing task in the pipeline that returns a reference (ResultRef).

---

## Links
- DSL Specification (canonical): [spec](./spec)
- Formal Specification (canonical): [formal_specification](./formal_specification)
- Execution Model (canonical): [execution_model](./execution_model)
- Retry Handling (canonical): [retry_mechanism_v2](../retry_mechanism_v2)
- Result Storage (canonical): [result_storage_canonical_v10](../result_storage_canonical_v10)
- Pagination (canonical): [pagination](./pagination)
