# NoETL Canonical Step Spec (v10)

> **Canonical v10 update (latest decisions):**
> - **One conditional keyword:** `when`
> - **All behavior knobs live under `spec`**, including policies as `spec.policy`
> - **No `step.when` field** — step admission is defined via `step.spec.policy.admit.rules`
> - **Routing uses Petri-net arcs**: `step.next` is a router object with `next.spec` + `next.arcs[]`
> - **Legacy `eval` is rejected** → replaced by `task.spec.policy` (object with required `rules:`)
> - **No special “sink” kind** — storage is just tools that return references
> - **Loop is a step modifier (not a tool kind)** — iteration-local streaming/pagination uses `jump`/`break` inside tasks

---

## 1. Scope model (server vs worker)

### Control plane (server)
Server is responsible for:
- playbook/workflow orchestration (Petri-net token routing)
- **step admission** via `step.spec.policy.admit`
- **transitions** via `step.next.arcs[].when`
- event log persistence
- scheduling loops / distributing iterations (optional)
- enforcing payload/reference policy (event size limits)

### Data plane (worker)
Worker is responsible for:
- executing tool tasks (http, postgres, python, noop, etc.)
- applying **task outcome policy** (`task.spec.policy.rules`) for retry/jump/streaming/pagination
- emitting task/step/loop-iteration events back to server

**Hard rule:** a worker task policy MUST NOT start steps. Only the server’s `next.arcs` starts steps.

---

## 2. Root playbook structure (reminder)

Root-level sections are:

- `metadata`
- `keychain` (credential declarations; optional but recommended)
- `executor` (optional runtime/backend knobs)
- `workload` (immutable inputs)
- `workflow` (array of steps)
- `workbook` (optional reusable refs / templates)

**No root `vars`.** Use `ctx` (execution scope) and `iter` (iteration scope) via policy mutations.

### 2.1 `keychain` (root) — credential declarations

`keychain` is a **playbook authoring concern**: it declares which credentials/secrets/tokens the playbook requires and how they are resolved (by name and kind). It is intentionally **root-scoped** so a playbook can omit `executor` entirely and still be self-describing.

- Resolution happens before workflow execution (during playbook evaluation / execution request evaluation).
- The resolved material is exposed to templates as `{{ keychain.<name>... }}`.
- `keychain` values are **read-only** during execution (mutation happens via refresh tools/policies, not by writing to `keychain`).

Example:
```yaml
keychain:
  - name: openai_token
    kind: secret_manager
  - name: pg_k8s
    kind: postgres_credential
```

## 3. `spec` layering (MUST)

`spec` may exist at any scope:
- `executor.spec`
- `step.spec`
- `loop.spec`
- `task.spec`
- `next.spec`
- `arc.spec` (future)

### 3.1 Merge/precedence
Effective spec for an inner object is computed by overlay, with **inner overriding outer** on key conflicts:

```
effective_task_spec = merge(
  kind_defaults,
  executor.spec,
  step.spec,
  loop.spec,
  task.spec
)
```

**Merge rules**
- Scalars: inner wins
- Maps: deep-merge, inner wins on conflicts
- Lists: replace (unless later you define a typed merge strategy)

### 3.2 Policy inheritance
Policies live under `spec.policy`. Policy meaning is defined by scope:
- Task policy controls retry/jump/break/continue/fail
- Step/loop/next policies are **non-control** (timeouts, lifecycle, scheduling hints)

---

## 4. `when` — the universal conditional (MUST)

`when` is the only conditional keyword in the DSL.

| Scope | Field | Evaluated by | When | Inputs |
|---|---|---|---|---|
| Step admission | `step.spec.policy.admit.rules[].when` | Server | before scheduling step | `ctx`, `workload`, token `event` |
| Task outcome policy | `task.spec.policy.rules[].when` | Worker | after task completes | `outcome`, `iter`, `ctx`, `_prev`, `_task` |
| Transition routing | `step.next.arcs[].when` | Server | on boundary events | `event`, `ctx`, `workload` |
| Authoring sugar | `choose/while/until.when` | Compiler | rewrite-time | expands into canonical |

**Rejected:** `expr`, legacy `eval`.

---

## 5. `spec.policy` is typed by scope (MUST)

Policies live under `spec.policy`, but their semantics are defined by **where** they appear.

### 5.1 executor.spec.policy (global defaults)
Allowed examples / placeholders:
- `defaults.timeouts`
- `defaults.resources`
- `results.reference_first`
- `limits.max_payload_bytes`
- future: placement/cost model/quantum backends

### 5.2 step.spec.policy (step admission + lifecycle)
#### 5.2.1 Admission policy (server)
Admission is expressed ONLY here (no `step.when` field):

```yaml
spec:
  policy:
    admit:
      mode: exclusive            # exclusive | inclusive (default exclusive)
      rules:
        - when: "{{ ... }}"
          then: { allow: true }
        - else:
            then: { allow: false }
```

Semantics:
- Server evaluates `admit.rules` before scheduling a step.
- If `admit` is omitted, default is **allow**.
- `mode` is reserved (future): `inclusive` may allow multiple admission rules to set additional token metadata; v10 runtime treats admission as a boolean gate.

#### 5.2.2 Lifecycle / failure hints (non-control)
Allowed placeholders:
- `lifecycle.timeout_s`, `lifecycle.deadline_s`
- `failure.mode: fail_fast | best_effort`
- `emit.events[]` (optional)
- placeholders: tracing, quotas, compensation

**MUST NOT:** include task control actions (`retry/jump/break/continue/fail`). Those are task scope only.

### 5.3 loop.spec.policy (iteration scheduling)
Allowed:
- `exec: distributed | local` (intent)
- `mode: sequential | parallel`
- `max_in_flight`, ordering hints
- placeholders: reducers, backpressure, partitioning

### 5.4 task.spec.policy (task outcome handling)
This is the canonical “Ok/Err-style” control.

**MUST:** `task.spec.policy` is an **object** with a required `rules:` list (no alternative shapes).

#### Shape
```yaml
spec:
  policy:
    mode: exclusive                 # placeholder (future)
    on_unmatched: continue          # placeholder (future), default continue

    # Optional hooks (placeholders, no control flow in v10)
    before: []
    after: []
    finally: []

    rules:
      - when: "{{ ... }}"
        then:
          do: retry|jump|continue|break|fail
          attempts: 5
          backoff: exponential|linear|none
          delay: 1.0
          to: some_label            # for jump
          set_iter: { ... }         # optional
          set_ctx: { ... }          # optional
      - else:
          then:
            do: continue
```

#### Semantics
- `rules` is the only place where **control actions** are allowed.
- If `else` is omitted and no rule matches, behavior is **continue** (v10 default).
- `set_iter` mutates iteration-local state (safe).
- `set_ctx` mutates execution state (restricted in parallel loops; see §6).

### 5.5 step.next router policy (optional)
`step.next` is a router object. Policy here is non-control (routing hints only).

Canonical `next`:
```yaml
next:
  spec:
    mode: exclusive                 # exclusive | inclusive (default exclusive)
    policy: {}                      # placeholders: priority/dedupe/partitioning
  arcs:
    - step: some_step
      when: "{{ ... }}"
      args: { ... }
```

---

## 6. Context vs iteration vs execution variables

### 6.1 `workload` (immutable)
Inputs merged from:
- playbook workload defaults
- execution request payload  
Result is immutable for the execution.

### 6.2 `ctx` (execution-scoped context)
Mutable execution context is allowed but must be explicit and well-bounded:
- `task.spec.policy.rules[].then.set_ctx` can write to `ctx`
- recommended until reducers exist:
  - treat `ctx` as append-only or write-once per key
  - reject conflicting writes from parallel iterations unless explicitly allowed

### 6.3 `iter` (iteration-scoped context)
In loops, `iter` is the primary mutable scratchpad.
- Always safe: `iter` is isolated per iterator item
- Parallel loops are safe because each iteration gets its own `iter`

### 6.4 Nested loops (MUST)
Canonical addressing rule:
- `iter` is the current loop iteration
- `iter.parent` is the outer iteration
- `iter.parent.parent` for deeper nesting

---

## 7. Tasks and tool list shapes (MUST)

`step.tool` supports:
1) **single task object**
2) **list of tasks**
3) **list of named task maps** (canonical recommended)

Canonical normalization converts everything into:
```yaml
tool:
  - label1: { kind: ... }
  - label2: { kind: ... }
```

### 7.1 How policy applies across shapes
- Policy is always applied **per task** (after that task produces `outcome`).
- If tasks are unnamed, compiler MUST generate stable labels (`task_1`, `task_2`, …) for `jump` targets and event correlation.

---

## 8. Loop behavior and “loop outcome”

A loop is not a tool kind. Loop is a **step-level execution modifier**.

### Loop events (server boundary)
Server emits/records:
- `loop.started`
- `loop.iteration.started`
- `loop.iteration.done` / `loop.iteration.failed`
- `loop.done`

### Task outcomes inside a loop (worker)
Each iteration executes the step’s task list under its own `iter`.
Task policy controls:
- retries
- streaming pagination via `jump` within the task list
- storage routing by status
- `break` (ends the iteration pipeline)

---

## 9. Retry handling (canonical)

Retry belongs to **task.spec.policy.rules**.

### 9.1 Two retry layers (optional)
1) **Tool-internal retry** (inside `task.spec` knobs; e.g. HTTP client retries)
2) **Canonical policy retry** (`then.do: retry`)

**Order**
- task executes using `task.spec` runtime knobs
- task yields final `outcome`
- policy rules evaluate that outcome
- policy may trigger retry of the whole task (canonical)

Recommendation: keep tool-internal retry minimal; prefer canonical policy retry so events are correct and replayable.

---

## 10. Result storage (reference-first)

No special “sink” kind. Storage is **just tools** that write data and return a reference.

Canonical approach:
- large payloads stored externally (Postgres table, object store, NATS object store, etc.)
- events store metadata + references:
  `{ store, key, checksum, size, schema_hint }`

Routing storage by status is done via `jump` to different storage tasks.

---

## 11. Pagination and streaming pipelines inside loops

Two valid patterns:

### 11.1 Distributed loop processing (server-managed iterations)
- loop iterations scheduled possibly across worker pools
- good for independent items (cities/hotels) that do not require ordered streaming per item

### 11.2 Worker-local streaming pagination (recommended for ordered paging)
Inside one iteration (one hotel), keep ordered processing on a single worker lease:
- `fetch_page` → `transform` → `store` → `paginate` (jump back to fetch_page)

This supports:
- cities loop parallel
- hotels loop parallel per city
- rooms paging sequential per hotel

---

## 12. Canonical streaming pagination example (NO fall-through)

```yaml
- step: fetch_all_endpoints

  spec:
    policy:
      admit:
        rules:
          - else:
              then: { allow: true }
      lifecycle: { timeout_s: 600 }
      failure: { mode: best_effort }

  loop:
    in: "{{ workload.endpoints }}"
    iterator: endpoint
    spec:
      mode: parallel
      max_in_flight: 10
      policy:
        exec: distributed   # optional intent

  tool:
    - init_iter:
        kind: noop
        spec:
          policy:
            rules:
              - else:
                  then:
                    do: continue
                    set_iter: { page: 1, has_more: true }

    - fetch_page:
        kind: http
        method: GET
        url: "{{ workload.api_url }}{{ iter.endpoint.path }}"
        params:
          page: "{{ iter.page }}"
          pageSize: "{{ iter.endpoint.page_size }}"
        spec:
          timeout: { connect: 5, read: 15 }
          policy:
            rules:
              - when: "{{ outcome.status == 'error' and outcome.http.status in [429,500,502,503,504] }}"
                then: { do: retry, attempts: 10, backoff: exponential, delay: 2.0 }
              - when: "{{ outcome.status == 'error' and outcome.http.status in [401,403] }}"
                then: { do: fail }
              - else:
                  then:
                    do: continue
                    set_iter:
                      http_status: "{{ outcome.http.status | default(200) }}"
                      has_more: "{{ outcome.result.data.paging.hasMore | default(false) }}"
                      page: "{{ outcome.result.data.paging.page | default(iter.page) }}"
                      items: "{{ outcome.result.data.data | default([]) }}"

    - route_by_status:
        kind: noop
        spec:
          policy:
            rules:
              - when: "{{ iter.http_status == 404 }}"
                then: { do: jump, to: store_404 }
              - else:
                  then: { do: jump, to: store_200 }

    - store_200:
        kind: postgres
        auth: pg_k8s
        command: "INSERT INTO results_ok (...)"
        spec:
          policy:
            rules:
              - when: "{{ outcome.status == 'error' and outcome.pg.code in ['40001','40P01'] }}"
                then: { do: retry, attempts: 5, backoff: exponential, delay: 2.0 }
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then: { do: jump, to: paginate }

    - store_404:
        kind: postgres
        auth: pg_k8s
        command: "INSERT INTO results_not_found (...)"
        spec:
          policy:
            rules:
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then: { do: jump, to: paginate }

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

  next:
    spec:
      mode: exclusive
    arcs:
      - step: validate_results
        when: "{{ event.name == 'loop.done' }}"
      - step: cleanup
        when: "{{ event.name == 'step.failed' }}"
```

---

## 13. Migration checklist (MUST)

- Remove any `step.when` fields → use `step.spec.policy.admit`.
- Replace any legacy `eval` → `task.spec.policy.rules`.
- Replace any `expr` → `when`.
- Replace `step.next[]` lists → `next.spec` + `next.arcs[]` router object.
- Remove “sink” special casing → storage is just tools returning references.
- Pagination:
  - distributed across iterations for independent items
  - streaming pagination within an iteration using `jump`/`break` for ordered processing

---

## 14. Authoring sugar (optional, future): `choose`, `while`, `until`

These are not required for canonical runtime. If implemented, they compile into canonical jump-based tasks.

- `choose`: when/then/else ladder
- `while`: pre-check loop
- `until`: post-check loop

Compiler requirements:
- stable generated labels
- enforced merge points to prevent fall-through
- output must normalize to canonical task list

---

## 15. Future enhancements (placeholders)
- reducers/atomics for safe cross-iteration aggregation
- compensation/rollback hooks
- arc QoS and partitioning (priority/dedupe)
- ResultRef schema registry and validation
- Petri-net reachability analysis
- compiler debug map (author sugar → canonical labels)
- quantum backend placement + execution hints in `executor.spec.policy`
