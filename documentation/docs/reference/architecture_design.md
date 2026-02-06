# NoETL Architecture (Canonical v10)

NoETL is an event-sourced orchestration system with a strict control-plane / data-plane split:

- **Server (control plane)**: validates playbooks, resolves inputs, admits steps, routes tokens via Petri-net arcs, persists the event log, and schedules work.
- **Worker pools (data plane)**: execute step pipelines (tools), apply **task outcome policies**, and emit events back to the server.
- **CLI**: manages server/worker lifecycle and provides operational commands.

Canonical v10 DSL details live under:
- `documentation/docs/reference/dsl/noetl_step_spec.md`
- `documentation/docs/reference/dsl/spec.md`
- `documentation/docs/reference/dsl/execution_model.md`

---

## System components and responsibilities

- **API server**: hosts execution APIs; ingests worker events; maintains projections; schedules step-runs and (optionally distributed) loop iterations.
- **Catalog**: stores playbooks (content + metadata) and serves them to the server.
- **Event log**: append-only store of execution events (authoritative source of truth).
- **Queue / broker** (implementation-defined): distributes step-run commands to workers; enforces leases and retries at the execution layer.
- **Workers**: claim leases, execute pipelines deterministically, apply task policies, and report events.

---

## Canonical DSL execution model (high level)

### Step structure (Petri-net transition)

A canonical step is:
- **Admission gate** (server): `step.spec.policy.admit.rules`
- **Ordered pipeline** (worker): `step.tool` (labeled task list)
- **Router** (server): `step.next` (`next.spec` + `next.arcs[]`)

There is **no** `step.when` field and **no** step-level `case`.

### Task control flow (worker-side)

Retry/pagination/polling/early-exit are expressed as **task outcome policy rules**:
- `task.spec.policy.rules[]` using `when` conditions and `then.do` actions (`retry|jump|continue|break|fail`)

There is **no** legacy `eval`/`expr`.

### Routing (server-side)

Routing is expressed as Petri-net arcs:
- `next.spec.mode: exclusive|inclusive`
- `next.arcs[]` with optional `when` and `args`

Only the server’s routing creates new tokens/step-runs.

---

## Runtime scopes (templates and policies)

Canonical namespaces:
- `workload` (immutable merged inputs)
- `keychain` (resolved credentials; read-only)
- `ctx` (execution-scoped mutable context; event-sourced patches)
- `iter` (iteration-scoped mutable context inside loops; isolated per iteration)
- `args` (token payload / arc inscription)
- pipeline locals: `_prev`, `_task`, `_attempt`, `outcome`
- routing input: `event` (boundary event for `next.arcs[].when`)

Canonical guidance:
- Use `iter` for pagination cursors and per-item progress.
- Use `ctx` for cross-step state and references (ResultRefs/ManifestRefs).
- Avoid conflicting `ctx` writes from parallel iterations until reducers/atomics exist.

---

## Server–worker lifecycle (canonical)

1) **Request**: client requests execution; server persists request event(s).
2) **Resolve**: server validates playbook, resolves `keychain`, merges request payload into `workload`, initializes `ctx`.
3) **Admit + schedule**: server evaluates admission for the entry step(s); schedules step-run commands.
4) **Execute**: worker claims a step-run lease and executes the pipeline tasks:
   - each task produces one final `outcome`
   - policy rules decide whether to `continue`, `retry`, `jump`, `break`, or `fail`
5) **Emit**: worker emits task/step/loop events; server persists them to the event log.
6) **Route**: server evaluates `next.arcs[]` on boundary events (`step.done`, `step.failed`, `loop.done`) and schedules next step-run(s).
7) **Finish**: server ends execution when quiescence is reached (no runnable tokens, no in-flight runs).

---

## Reference-first results (canonical)

Canonical rule: large outputs MUST be externalized and represented by references.
- storage tasks are normal tool tasks (no special `sink` kind)
- pass **ResultRef** objects + extracted fields, not giant inline payloads

See:
- `documentation/docs/reference/result_storage_canonical_v10.md`
- `documentation/docs/reference/dsl/runtime_results.md`
