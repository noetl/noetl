---
sidebar_position: 3
title: Playbook Structure (Canonical)
description: Canonical NoETL playbook structure and section semantics for DSL v2
---

# NoETL Playbook Structure Guide (Canonical v2)

This guide describes the **canonical** NoETL playbook document structure and how it maps to the runtime model.

Canonical runtime principles:
- Step = `when` (enable guard) + `tool` (ordered pipeline) + `next` (arcs)
- Retry/pagination/polling are expressed via **tool-level `eval: expr`**
- Result handling is **reference-first** (no special `sink` tool kind; “sink” is a pattern)
- Runtime scopes: `workload` (immutable), `ctx` (execution), `vars` (step), `iter` (iteration)

---

## 1) Overview

A NoETL playbook is a YAML document that defines a workflow as a set of steps and transitions.

**Root sections are limited to:**
- `apiVersion`
- `kind`
- `metadata`
- `executor` (optional)
- `workload`
- `workflow`
- `workbook` (optional)

> **Important:** `vars` MUST NOT appear at playbook root level. Step state is `vars` (step run) and execution state is `ctx` (runtime), not document root keys.

---

## 2) Basic structure

```yaml
apiVersion: noetl.io/v2
kind: Playbook

metadata:
  name: example_playbook
  path: workflows/example_playbook
  version: "2.0"
  description: Example playbook using canonical v2 structure

executor:
  kind: distributed
  spec:
    pool: default

workload:
  api_url: "https://api.example.com"
  page_size: 50

workflow:
  - step: start
    next:
      - step: fetch_transform_store

  - step: fetch_transform_store
    when: "{{ true }}"
    tool:
      - fetch_page:
          kind: http
          method: GET
          url: "{{ workload.api_url }}/data"
          params:
            page: 1
            pageSize: "{{ workload.page_size }}"
          eval:
            - expr: "{{ outcome.status == 'error' and outcome.http.status in [429,500,502,503,504] }}"
              do: retry
              attempts: 5
              backoff: exponential
              delay: 2
            - expr: "{{ outcome.status == 'error' }}"
              do: fail
            - else:
                do: continue
      - transform:
          kind: python
          args: { data: "{{ _prev }}" }
          code: |
            # produce transformed result
            result = {"items": data}
      - store:
          kind: postgres
          auth: pg_k8s
          command: "INSERT INTO ..."
    next:
      - step: end

  - step: end
    tool:
      - done:
          kind: noop

workbook:
  tasks: {}
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

This section is intentionally implementation-defined, but it MUST follow the pattern:

```yaml
executor:
  kind: distributed | local | hybrid
  spec: { ... }
```

---

## 5) Workload (immutable input)

`workload` provides default inputs and configuration for the playbook.

At runtime, the server merges:
1) playbook `workload` defaults
2) execution request payload overrides

This merged workload is immutable and available as `workload.*` in templates.

---

## 6) Workflow (steps and transitions)

`workflow` is a list of steps. Steps form a directed graph using `next[]`.

### 6.1 Step types (canonical)
In canonical v2 there are no special step “types” like `start`, `end`, `condition`.
Instead, behavior is expressed with:
- `when` on the step (enable guard)
- `next[].when` on outgoing arcs (routing guards)
- `tool.eval` inside pipeline (retry/jump/break/fail)

### 6.2 Step enable guard (`when`)
`when` is an expression evaluated by the **server** when routing a token to a step.
If omitted, it defaults to `true`.

```yaml
- step: do_work
  when: "{{ args.enabled == true }}"
  tool: ...
```

### 6.3 Tool pipeline (`tool`)
A step may contain a `tool` list which is an **ordered pipeline** of labeled tasks.

- The worker executes tasks top-to-bottom.
- `_prev` threads the previous task output to the next task.
- Each tool task may define `eval` to control control-flow.

### 6.4 Routing (`next[]`)
`next` is a list of outgoing transitions. Each transition may have:
- `when` guard (default `true`)
- `args` token payload to pass to the next step
- `spec` for edge semantics (optional)

Example (exclusive by default):

```yaml
- step: decide
  spec:
    next_mode: exclusive
  tool:
    - check:
        kind: python
        code: "result = {'ok': True}"
  next:
    - step: success
      when: "{{ _prev.ok == true }}"
    - step: failure
      when: "{{ _prev.ok != true }}"
```

### 6.5 Loop (pagination, fan-out, batch)
A step may define `loop` to repeat the pipeline over a collection.

```yaml
- step: per_endpoint
  loop:
    spec: { mode: sequential }
    in: "{{ workload.endpoints }}"
    iterator: endpoint
  tool:
    - fetch:
        kind: http
        url: "{{ workload.api_url }}{{ iter.endpoint.path }}"
```

In `parallel` loop mode:
- each iteration has isolated `iter.*`
- shared `vars` writes require explicit intent (`set_shared`) or deterministic mapping (see DSL spec)

---

## 7) Runtime variables vs document fields

These are **runtime scopes** available during evaluation (NOT playbook root keys):

- `ctx.*` — execution-scoped mutable context (event-sourced patches)
- `vars.*` — step-run-scoped mutable state
- `iter.*` — loop iteration scoped state
- `args.*` — token payload from `next[].args`

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

## 9) Common patterns

### 9.1 Retry (tool-level eval)
```yaml
- fetch:
    kind: http
    url: "{{ workload.api_url }}/data"
    eval:
      - expr: "{{ outcome.status == 'error' and outcome.http.status in [429,500,502,503,504] }}"
        do: retry
        attempts: 10
        backoff: exponential
        delay: 2
      - expr: "{{ outcome.status == 'error' }}"
        do: fail
      - else:
          do: continue
```

### 9.2 Pagination (jump + iter state)
```yaml
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
```

### 9.3 “Sink” (pattern, not a tool kind)
A sink is simply a storage-writing task in the pipeline that returns a reference (ResultRef).

---

## Links
- DSL Specification (canonical): `/docs/reference/dsl/spec`
- Formal Specification (canonical): `/docs/reference/dsl/formal_specification`
- Execution Model (canonical): `/docs/runtime/execution_model`
- Retry Handling (canonical): `/docs/runtime/retry_mechanism`
- Result Storage (canonical): `/docs/runtime/result_storage`
