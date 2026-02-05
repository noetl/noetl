---
sidebar_position: 30
title: Optional Distributed Fan‑Out Mode (Non‑Canonical Profile)
description: An optional execution profile for distributing loop iterations across workers without contradicting canonical v2 semantics
---

# Optional Distributed Fan‑Out Mode (Non‑Canonical Profile)

This document defines an **optional** “distributed fan‑out” execution profile for NoETL DSL v2. It is designed to **coexist** with the **canonical v2** model (single-worker step run executing `step.tool` pipelines with tool-level `eval`) without contradicting it.

## Status and intent

- **Canonical default:** worker-local step pipelines; loops executed within the worker with `iter.*` isolation; routing via step `next[]` evaluated on the server.
- **This profile:** enables the server to **split loop iterations** into independent step runs (“shards”) and distribute them across worker pools when scale/out or tail-latency dominates.

> This mode is **not** a change to the core DSL concepts. It is a *profile* selected via `executor.spec` / `step.spec` policies. Playbooks remain valid canonical v2; only execution strategy changes.

---

## 1) When to use distributed fan‑out

Use this profile when:
- the loop collection is extremely large (10⁵–10⁹ items)
- per-iteration work is heavy and parallelizable across workers
- you need better cluster utilization than a single worker can provide for one step run
- you want per-iteration isolation as independent jobs for observability and retries

Avoid this profile when:
- strict in-order iteration is required
- per-iteration tasks depend on shared mutable state without reducers
- you need strict “single worker controls entire step pipeline” semantics for correctness

---

## 2) Compatibility with canonical v2

### What remains the same (MUST)
- Step structure remains: `when + tool(pipeline) + next[]`
- Tool-level flow control remains: `eval: expr → do: continue|retry|jump|break|fail`
- Results are reference-first; “sink” remains a pattern (storage task returning a reference)
- Server remains authoritative for:
  - validating playbooks
  - routing between steps (`next[]` evaluation)
  - persisting event log
- Workers remain authoritative for:
  - executing tool tasks
  - emitting task/step events

### What changes (ONLY in this profile)
- **Where loop iteration is executed:** the loop is not executed as a single worker-local iteration program; instead, the loop is **expanded** into many independent step runs.
- **Iteration identity and fan-in:** the runtime tracks shard/iteration ids and optionally merges/aggregates outputs via reducers or external storage.

> Canonical playbooks remain valid; fan‑out affects runtime scheduling, not playbook syntax.

---

## 3) Profile activation

Distributed fan‑out is activated by a policy flag. Recommended locations:

### 3.1 Executor-level policy (applies to all steps unless overridden)
```yaml
executor:
  kind: distributed
  spec:
    loop_mode: fanout     # canonical default is "local"
```

### 3.2 Step-level override (preferred granularity)
```yaml
- step: process_items
  spec:
    loop_mode: fanout     # overrides executor default for this step
```

If neither is set, the runtime uses canonical loop execution (worker-local).

---

## 4) Execution semantics

### 4.1 Token model and shard creation
In fan‑out mode, a step with a `loop` is treated as a **fan‑out transition**:

1. Server evaluates `step.when` and accepts a token for the step.
2. Server evaluates `loop.in` to a collection **descriptor** (not necessarily materialized).
3. Server splits the iteration space into **shards** and enqueues child tokens:
   - each child token is a **step run** with `args` containing iteration identity and the specific element (or a reference to it).

### 4.2 Shard identity (recommended)
Each iteration/shard MUST have stable identifiers:

- `loop_id` — stable id for the loop expansion instance
- `shard_id` — stable id for the shard
- `iter_index` — numeric index (if available)
- `iter_key` — key/cursor for idempotency (if available)

These identifiers should be present in:
- event envelope metadata
- result references emitted by storage tasks
- projection tables for monitoring

### 4.3 Worker execution of a shard
A shard is executed as a normal step run:
- worker runs `step.tool` pipeline
- tool-level `eval` applies normally
- `iter.*` exists but is **shard-local** (it represents the current iteration only)

> In fan‑out mode, `iter.*` is still available, but it no longer represents a loop cursor across pages/items; it represents **one** loop element.

### 4.4 Retry semantics in fan‑out mode
Retry remains **worker-local** via `eval` on the failing task.

Additionally, the server MAY offer **job-level retry** for shard step-runs:
- if a worker fails mid-run (crash, lease expiry)
- if the shard run reaches a terminal `step.failed` and policy allows re-enqueue

Job-level retry MUST be bounded and must preserve idempotency keys (`iter_key`, `shard_id`).

---

## 5) Fan‑in / completion semantics

Fan‑out introduces a fan‑in boundary: the original step is not “complete” until all shards are terminal.

### 5.1 Fan‑in tracking (server responsibility)
The server MUST maintain a fan‑in tracker keyed by `loop_id` that records:
- total expected shards (or completion condition)
- shard states (pending/running/succeeded/failed)
- retries used
- references to shard outputs

### 5.2 Completion condition
The step fan‑out instance transitions to one of:
- **complete** — all shards succeeded (or policy allows partial success)
- **failed** — one or more shards failed and policy requires all succeed
- **partial** — some shards failed but policy allows proceed

### 5.3 Routing after fan‑in
Only after fan‑in reaches a terminal state does the server evaluate the parent step’s `next[]` transitions.

Recommended: the server exposes a synthesized `vars`-like projection for `next[].when`, e.g.:
- `fanin.status`
- `fanin.succeeded`
- `fanin.failed`
- `fanin.refs` (result references list or a pointer)

> The playbook itself does not define this structure; it is runtime-provided state for `next[]` guards.

---

## 6) Shared state and reducers

### 6.1 Why reducers are needed
In fan‑out mode, shard runs are independent and may execute in parallel on many workers. Shared mutable writes (to `ctx` or `vars`) are unsafe unless coordinated.

### 6.2 Rule: avoid shared writes by default
- Shards SHOULD NOT write shared `ctx` directly.
- Shards SHOULD write outputs to external storage and return references.

### 6.3 Reducer pattern (optional)
If you need aggregation, define a separate **reduce step** that consumes shard outputs.

Two recommended reducer approaches:
1) **External store aggregation** (preferred):
   - each shard writes rows/objects tagged with `loop_id` and `shard_id`
   - reduce step queries/aggregates using SQL/object listings
2) **Runtime reducer API** (advanced):
   - explicit atomic ops like `set_shared` with commutative reducers (sum, min, max, append, merge)
   - only safe for associative/commutative operations and must be explicitly enabled

---

## 7) Pagination interaction

Pagination remains canonical and **worker-local** inside a shard when the shard’s job is “fetch pages for one endpoint”.

However, fan‑out is typically used for:
- splitting **endpoints** or **items** across shards
- not splitting pages of a single endpoint across workers (unless the API supports independent page ranges)

Recommended patterns:
- fan‑out across endpoints; within each shard, paginate pages sequentially via `eval: jump` and `iter.page`
- fan‑out across independent page ranges only if the API allows `page=N` random access and merging is externalized

---

## 8) Event model additions (profile-specific)

The event taxonomy remains compatible, with added fields for fan‑out:

- `loop.fanout.started` (server): loop expanded, `loop_id`, shard count
- `loop.shard.enqueued` (server): child step run created
- `loop.shard.started` (worker): shard step run started
- `loop.shard.done/failed` (worker): shard terminal
- `loop.fanin.completed` (server): fan‑in terminal state reached

All shard task events (`task.started/task.processed`) remain unchanged; they include shard metadata.

---

## 9) Operational considerations

### 9.1 Backpressure and limits
Fan‑out mode must enforce:
- max shards per loop
- max concurrent shards (cluster backpressure)
- shard queue TTL and lease timeouts

### 9.2 Idempotency
Because shards can be retried at job level, shard storage writes SHOULD be idempotent:
- include `(execution_id, loop_id, shard_id, iter_key)` in primary keys or dedupe keys
- use upsert semantics for “exactly-once” effect when needed

### 9.3 Failure policies
Define policies at `executor.spec` or `step.spec`:
- `fanout.fail_fast`: stop early on first shard failure
- `fanout.allow_partial`: allow proceed with partial success
- `fanout.max_job_retries`: job-level retries if worker dies or step fails

---

## 10) Summary

Distributed fan‑out is an **optional execution profile** that:
- keeps the canonical DSL intact
- changes *runtime scheduling* for loop steps to distribute iterations across workers
- requires careful fan‑in tracking and, when needed, reducer/aggregation steps
- is best for large-scale independent iteration workloads, including quantum parameter sweeps

Canonical v2 remains the default and simplest model; fan‑out is a scalability mode selected by policy.

