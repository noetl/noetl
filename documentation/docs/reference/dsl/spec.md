---
sidebar_position: 2
title: DSL Specification (Canonical)
description: Canonical specification for NoETL DSL v2 syntax, semantics, runtime scopes, and Petri-net workflow model
---

# NoETL Playbook DSL — Specification (Canonical v10)

**Document type:** Canonical DSL Specification  
**API Version:** `noetl.io/v2`  
**Status:** Normative for new playbooks

This document **replaces** older v2 drafts that contained `vars`, `case`, `retry`, `sink`, `step.when`, `eval`, or `expr` constructs. Those are **non-canonical** in v10.

Canonical v10 principles:
- **Step = Petri-net transition**: admission gate + ordered pipeline + routing router
- **Only conditional keyword is `when`**
- All knobs live under **`spec`** at the appropriate scope
- All execution control lives under **policies**: `spec.policy.*`
- Retry/pagination/branching inside a step are driven by **task policy rules** (`do: retry|jump|continue|break|fail`)
- Result storage is **reference-first**; “sink” is a **pattern**, not a tool kind

---

## 1) Conformance terminology

The key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are normative requirements.

---

## 2) Architecture roles (informative, aligned)

- **Worker (`worker.py`)**: pure background worker pool (no HTTP endpoints)
- **Server (`server.py`)**: orchestration/control plane + API endpoints + event log persistence
- **CLI (`clictl.py`)**: manages worker pools and server lifecycle

---

## 3) Root document model (normative)

A playbook is a YAML mapping with exactly these root sections (plus `apiVersion`, `kind`):

| Key | Type | Required | Meaning |
|---|---:|:---:|---|
| `apiVersion` | string | Yes | MUST be `noetl.io/v2` |
| `kind` | string | Yes | MUST be `Playbook` |
| `metadata` | mapping | Yes | name/path/version/description |
| `keychain` | list | No | credential declarations (resolved before execution) |
| `executor` | mapping | No | placement/runtime defaults |
| `workload` | mapping | No | immutable defaults merged with request payload |
| `workflow` | list | Yes | steps (transitions) |
| `workbook` | mapping | No | optional catalog of reusable task templates |

**Root restrictions (normative):**
- Playbooks MUST NOT include root `vars`.
- If `keychain` is present, implementations MUST resolve it before workflow execution and expose it to templates as `keychain.<name>...`.
- `keychain` values MUST be treated as read-only during execution (refresh/rotation is implemented via tools + policies, not by mutating `keychain`).
- Any additional root keys MUST be rejected by canonical validators unless explicitly enabled as extensions.

### 3.1 `keychain` (root) — credential declarations (normative)

`keychain` declares which credentials/secrets/tokens a playbook needs and how they are resolved (by `name` + `kind`). Tool tasks SHOULD reference credentials by name (for example `auth: pg_k8s`).

Example:
```yaml
keychain:
  - name: openai_token
    kind: secret_manager
  - name: pg_k8s
    kind: postgres_credential
```

---

## 4) Template evaluation (normative)

1. All expressions MUST be valid **Jinja2 templates** embedded as YAML strings.
2. Implementations MUST evaluate templates with a runtime context containing (at minimum):
   - `workload` (immutable merged workload)
   - `keychain` (resolved credentials; read-only)
   - `ctx` (execution-scoped context)
   - `args` (token payload; arc inscription)
   - `execution_id` (execution identifier)
   - `iter` (iteration scope; only when loop exists)
    - pipeline locals: `_prev`, `_task`, `_attempt`, and `outcome` (policy evaluation only)
    - `event` (routing evaluation only)

---

## 5) Runtime scopes (normative)

### 5.1 `workload` (immutable)
- Produced once at execution start: deep merge (request payload overrides playbook defaults).
- MUST NOT be mutated.

### 5.2 `ctx` (execution-scoped mutable)
- Shared across steps within one execution instance.
- Writes are expressed via `set_ctx` patches in policies.
- Patches MUST be persisted as events (event-sourced).

### 5.3 `iter` (iteration-scoped mutable)
- Exists only inside loop iterations.
- Always isolated per iteration (safe for parallel mode).
- Used for pagination counters, cursors, streaming state, per-item status, etc.

### 5.4 Pipeline locals
- `_prev`: previous task output (canonical: previous task’s `outcome.result`)
- `_task`: current task label
- `_attempt`: attempt counter for current task
- `outcome`: tool outcome envelope (available inside task policy evaluation)

---

## 6) Workflow and steps (normative)

### 6.1 Workflow
`workflow` is a list of steps. Steps form a directed graph via `next` routers and Petri-net **arcs**.

### 6.2 Step (Petri-net transition)
A step has:
- optional **admission policy**: `step.spec.policy.admit`
- optional **loop modifier**: `step.loop`
- optional **ordered pipeline**: `step.tool` (list of labeled tasks)
- optional **router**: `step.next` (arcs)

A step MUST have at least one of:
- `tool`
- `next`

**Canonical restriction:** step MUST NOT contain top-level `when`. Admission is under `step.spec.policy.admit`.

### 6.3 Canonical step schema
```yaml
- step: <name>                       # required
  desc: <string?>                    # optional
  spec:                              # optional
    policy:
      admit:                         # optional server-side admission
        rules: [ ... ]
  loop: <loop?>                      # optional
  tool: <pipeline?>                  # optional
  next: <next_router?>               # optional
```

---

## 7) Step admission policy (server-side) (normative)

Admission is evaluated on the server **before** the step is scheduled.

Shape:
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

Rules are evaluated top-to-bottom; first match wins; `else` is fallback.
If `admit` is omitted, admission defaults to `allow: true`.

Inputs available in admission `when`:
- `workload`, `ctx`, `args`, `execution_id`
- (if available) triggering `event` (boundary event data)

---

## 8) Loop clause (normative)

### 8.1 Syntax
```yaml
loop:
  in: "{{ <collection expr> }}"
  iterator: <identifier>
  spec:
    mode: sequential|parallel         # default sequential
    max_in_flight: <int?>             # for parallel
    policy:
      exec: local|distributed         # optional placement intent
```

### 8.2 Semantics
- `in` MUST evaluate to a list/array.
- For each element `e`, an iteration scope MUST be created:
  - `iter.<iterator>` = e
  - `iter.index` = iteration index
- `sequential` MUST preserve iteration order.
- `parallel` MAY complete out-of-order but MUST preserve stable iteration ids.

### 8.3 Parallel safety
In `parallel` loop mode:
- `set_iter` is always safe.
- `set_ctx` MUST be restricted or rejected until reducers/atomics are implemented (implementation choice must be documented).

---

## 9) Tool pipeline and tasks (normative)

### 9.1 Pipeline shape
A step pipeline is an **ordered list of labeled tasks**:

```yaml
tool:
  - fetch:
      kind: http
      ...
  - transform:
      kind: python
      ...
  - store:
      kind: postgres
      ...
```

### 9.2 Normalization (required)
Implementations MAY accept shorthand task shapes, but MUST normalize to the labeled list form internally.
Labels MUST be unique within the pipeline.

### 9.3 Tool kinds (extensible)
Common kinds include:
- `http`, `postgres`, `duckdb`, `python`, `secrets`, `playbook`, `workbook`, `noop`, `script`
Implementations MAY add additional kinds (including quantum connectors).

---

## 10) Spec layering and precedence (normative)

`spec` can appear at multiple levels. Effective configuration MUST be computed by deep-merge with precedence:

`kind defaults` → `executor.spec` → `step.spec` → `loop.spec` → `task.spec`

Merge rules:
- scalars: inner wins
- maps: deep merge; inner wins conflicts
- lists: replace

This applies to runtime knobs and to policy subtrees (typed by scope).

---

## 11) Tool outcome envelope (normative)

Every tool invocation MUST produce exactly one final `outcome` envelope:

- `outcome.status`: `"ok"` or `"error"`
- `outcome.result`: success output (small or reference)
- `outcome.error`: error object (MUST include `kind`; SHOULD include `retryable`)
- `outcome.meta`: duration, attempt, timestamps, trace ids

Kind helpers MAY exist:
- HTTP: `outcome.http.status`, `outcome.http.headers`
- Postgres: `outcome.pg.code`, `outcome.pg.sqlstate`
- Python: `outcome.py.exception_type`

---

## 12) Task policy (worker-side pipeline control) (normative)

### 12.1 One canonical shape
`task.spec.policy` MUST be an object with required `rules:`:

```yaml
spec:
  policy:
    rules:
      - when: "{{ <bool expr over outcome/locals> }}"
        then:
          do: continue|retry|jump|break|fail
          attempts: <int?>               # retry
          backoff: none|linear|exponential
          delay: <seconds|template?>
          to: <task_label?>              # jump
          set_iter: <mapping?>           # patch iter
          set_ctx: <mapping?>            # patch ctx
      - else:
          then:
            do: continue
```

### 12.2 Evaluation semantics
- Evaluate rules top-to-bottom.
- First matching `when` wins.
- `else` applies if no `when` matched.
- If `policy` omitted:
  - ok → `continue`
  - error → `fail`
- If `policy` present but no match and no else:
  - default → `continue`

### 12.3 `do` directives (normative)
- `continue`: proceed to next task; `_prev := outcome.result`
- `retry`: rerun current task up to `attempts`
- `jump`: set pipeline program counter to `then.to`
- `break`: end pipeline successfully (iteration done / step.done)
- `fail`: end pipeline with failure (iteration failed / step.failed)

---

## 13) Next routing (server-side Petri-net arcs) (normative)

### 13.1 Router schema
```yaml
next:
  spec:
    mode: exclusive|inclusive         # default exclusive
    policy: {}                        # reserved placeholders
  arcs:
    - step: <target_step>
      when: "{{ <bool expr> }}"       # default true if omitted
      args: <mapping?>                # token payload / arc inscription
      spec: <mapping?>                # reserved placeholders
```

### 13.2 Matching semantics
- All arcs with `when == true` are considered matches.
- If multiple matches:
  - `exclusive` (default): first match wins (stable YAML order)
  - `inclusive`: all matches fire (fan-out)

### 13.3 Evaluation time
The server MUST evaluate arcs upon receiving a terminal step boundary event:
- `step.done`
- `step.failed`
- `loop.done` (when step has a loop)

Inputs available in arc `when`:
- `event` (boundary event)
- `workload`, `ctx`, `args` (token), and (optionally) summarized step outcome references

---

## 14) Results and storage (reference-first) (normative)

- Large results SHOULD be stored externally (Postgres tables, object store, NATS object store, etc.).
- Events SHOULD store metadata + reference objects rather than large payload bodies.

Recommended reference shape:
```json
{ "store": "postgres.table", "key": "results_ok", "range": "id:100-150", "size": 123456, "checksum": "..." }
```

**No special sink:** “Sink” is just a tool task that writes data and returns a reference.

---

## 15) Events (canonical taxonomy) (normative minimum)

### 15.1 Event envelope (minimum)
A conforming event MUST include:
- `event_id`, `execution_id`, `timestamp`
- `source`: `server|worker`
- `name`
- `entity_type`: `playbook|workflow|step|task|loop|next`
- `entity_id`
- `status`: `in_progress|success|error|skipped`
- `payload` (metadata/outcomes/references)

### 15.2 Minimum recommended event set
**Server:**
- `playbook.execution.requested`
- `playbook.request.evaluated`
- `workflow.started`
- `step.scheduled`
- `next.evaluated`
- `workflow.finished`
- `playbook.processed`

**Worker:**
- `step.started`
- `task.started`
- `task.done` (includes outcome or references)
- `step.done` / `step.failed`
- `loop.iteration.*` and `loop.done` (if loop present)

---

## 16) Deprecated constructs (rejected by canonical validators)

The following MUST be rejected unless explicitly enabled as legacy extensions:

- root `vars`
- step `when` (top-level)
- `case` / `retry` / `sink` step blocks
- tool `eval` blocks or `expr` keyword
- `step.spec.next_mode` (use `next.spec.mode`)

---

## Appendix A) Minimal canonical example

```yaml
apiVersion: noetl.io/v2
kind: Playbook

metadata:
  name: minimal
  path: examples/minimal
  version: "2.0"

workload:
  api_url: "https://api.example.com"

workflow:
  - step: start
    next:
      spec: { mode: exclusive }
      arcs:
        - step: fetch

  - step: fetch
    tool:
      - call:
          kind: http
          method: GET
          url: "{{ workload.api_url }}/ping"
          spec:
            policy:
              rules:
                - when: "{{ outcome.status == 'error' and outcome.http.status in [429,500,502,503,504] }}"
                  then: { do: retry, attempts: 5, backoff: exponential, delay: 2 }
                - when: "{{ outcome.status == 'error' }}"
                  then: { do: fail }
                - else:
                    then: { do: break }
    next:
      spec: { mode: exclusive }
      arcs:
        - step: end
          when: "{{ event.name == 'step.done' }}"

  - step: end
    tool:
      - done:
          kind: noop
```

---
