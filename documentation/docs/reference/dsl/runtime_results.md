---
sidebar_position: 4
title: Runtime Results (Canonical v10)
description: How NoETL stores, indexes, and retrieves task outcomes and step results using reference-first storage
---

# NoETL Runtime Results — Storage & Access (Canonical v10)

This document defines how NoETL stores and retrieves **task outcomes** and **step results** in a **reference-first, event-sourced** system.

Aligned with **Canonical v10 DSL**:
- No `sink` tool kind: storage is **just tools** that write data and return references.
- No `retry`/`pagination`/`case` blocks: retries + pagination are handled by **task policies** (`task.spec.policy.rules`) and **iteration scope** (`iter.*`).
- No `eval:`/`expr:`: use `when` in policies.
- Events and context pass **references only** (inline only for size-capped preview/extracted fields).

See also:
- [NoETL Canonical Step Spec (v10)](./step_spec)
- [Runtime Event Model (Canonical v10)](./runtime_events)
- [Result Storage (Canonical v10)](../result_storage_canonical_v10)

---

## 1) Goals

1. **Event-sourced correctness**: the event log is the source of truth for *what happened*.
2. **Efficiency**: large payloads MUST NOT bloat the event log.
3. **Composable access**: downstream steps MUST be able to reference:
   - latest outcome
   - per-attempt outcomes (retry)
   - per-page outcomes (pagination streams)
   - per-iteration outcomes (loop)
   - combined outcomes via **manifests** (streamable)
4. **Pluggable storage**: store bodies in:
   - Postgres
   - NATS KV
   - NATS Object Store
   - Google Cloud Storage (GCS)
   and keep only **references + extracted fields** in events/context.
5. **Streaming-friendly**: represent combined results as **manifests**, not huge merged arrays.

---

## 2) Concepts

### 2.1 Task outcome vs step result
- **Task outcome**: the final result of a single task invocation in a step pipeline (e.g., one HTTP call).
- **Step result**: logical outcome of a step; may be comprised of many task outcomes due to:
  - retries (multiple attempts)
  - pagination (multiple pages)
  - loops (multiple iterations)

Canonical v10 produces step boundaries via `step.done` / `step.failed` events.

### 2.2 Reference-first output rule
A task’s output body is either:
- **inline** (only if small and within caps), OR
- externalized to a backend and returned as a **ResultRef**.

The event log stores:
- the **outcome envelope** (`status`, `error`, `meta`)
- **ResultRef** + extracted fields + preview

---

## 3) ResultRef

A **ResultRef** is a lightweight pointer to externally stored data.

### 3.1 Canonical shape
```json
{
  "kind": "result_ref",
  "ref": "noetl://execution/<eid>/step/<step>/task/<task>/run/<task_run_id>/attempt/<n>",
  "store": "nats_kv|nats_object|gcs|postgres",
  "scope": "step|execution|workflow|permanent",
  "expires_at": "2026-02-01T13:00:00Z",
  "meta": {
    "content_type": "application/json",
    "bytes": 123456,
    "sha256": "...",
    "compression": "gzip"
  },
  "extracted": {
    "page": 2,
    "has_more": true
  },
  "preview": {
    "truncated": true,
    "bytes": 2048,
    "sample": [{"id": 1}]
  }
}
```

### 3.2 Logical vs physical addressing
- `ref` is a **logical NoETL URI**.
- Physical location is derived from `store` + `meta` (bucket/key/object/table range), and/or a control-plane mapping.

---

## 4) Storage tiers and recommended usage

### 4.1 Inline (small)
Store directly in the event payload for small results.
- controlled by `inline_max_bytes`

Use for:
- small status objects
- small aggregates
- extracted fields

### 4.2 Postgres (queryable)
Use for:
- queryable intermediate tables
- projections / indices
- moderate-sized JSON stored in tables (when useful)

Recommended ResultRef meta:
- `{ "schema": "...", "table": "...", "pk": "...", "range": "id:100-150" }`

### 4.3 NATS KV (small, fast)
Use for:
- cursors
- session-like state
- small JSON parts (within practical limits)

Recommended ResultRef meta:
- `{ "bucket": "...", "key": "execution/<eid>/..." }`

### 4.4 NATS Object Store (medium artifacts)
Use for:
- paginated pages
- chunked streaming parts
- medium artifacts

Recommended ResultRef meta:
- `{ "bucket": "...", "key": ".../page_001.json.gz" }`

### 4.5 Google Cloud Storage (large, durable)
Use for:
- large payloads
- durable datasets
- cross-system distribution

Recommended ResultRef meta:
- `{ "bucket": "...", "object": ".../payload.json.gz" }`

---

## 5) DSL controls for result storage (Canonical v10)

Result storage controls live under **task.spec.result**.

```yaml
- fetch_page:
    kind: http
    method: GET
    url: "{{ workload.api_url }}/items"
    spec:
      result:
        inline_max_bytes: 65536
        preview_max_bytes: 2048
        store:
          kind: auto                 # auto|nats_kv|nats_object|gcs|postgres
          scope: execution           # step|execution|workflow|permanent
          ttl: "1h"
          compression: gzip
        select:                      # extracted fields for routing/state
          - path: "$.paging.hasMore"
            as: has_more
          - path: "$.paging.page"
            as: page
```

### 5.1 Extracted fields
`select` extracts small values into `ResultRef.extracted`.
These are safe to pass in context and to use in routing decisions without resolving the full body.

---

## 6) Indexing (how to address pieces)

To retrieve “pieces” deterministically, every task completion SHOULD record correlation keys:

- `execution_id`
- `step_name`, `step_run_id`
- `task_label`, `task_run_id`
- `attempt` (retry attempt number, starting at 1)
- `iteration` / `iteration_id` (loop)
- `page` (pagination)

This enables queries like:
- final successful attempt for iteration 2 / page 3
- all pages for iteration 7
- latest output for task `transform` in step `fetch_transform_store`

---

## 7) Manifests (aggregation without bloat)

### 7.1 Why manifests
Do not materialize huge merged arrays in memory/events. Use **manifest refs** listing part refs.

```json
{
  "kind": "manifest",
  "strategy": "append",
  "merge_path": "$.data.items",
  "parts": [
    {"ref": "noetl://.../page/1/..."},
    {"ref": "noetl://.../page/2/..."}
  ]
}
```

### 7.2 Where manifests live
A manifest itself is stored reference-first:
- inline if tiny
- else NATS Object Store / GCS / Postgres

The step boundary event stores only a reference to the manifest.

---

## 8) How downstream steps access results (reference-only)

Canonical rule: downstream steps receive **ResultRef + extracted fields**, not full payload bodies.

Recommended bindings for a task label `fetch_page`:
- `fetch_page.__ref__` → ResultRef
- `fetch_page.page`, `fetch_page.has_more` → extracted fields
- `fetch_page.__preview__` → optional preview

To read the full body, the playbook MUST explicitly resolve the ref:
- via server API (resolve endpoint), or
- via a tool (`kind: artifact/result`, `action: get`), or
- by scanning the artifact directly (DuckDB, etc.), depending on backend.

---

## 9) Implementation strategy (event-sourced & efficient)

### 9.1 Worker responsibilities
On each task completion:
1. compute `outcome` (status/error/meta + raw result)
2. apply `task.spec.result`:
   - create preview (optional)
   - extract selected fields (optional)
   - choose store backend (auto/explicit)
   - store full body if needed
3. emit `task.attempt.*` + `task.done/failed` events containing:
   - `outcome` (size-capped)
   - ResultRef (if externalized) and extracted fields
   - correlation keys

### 9.2 Server responsibilities
On event ingestion:
- persist events
- upsert projections (rebuildable):

**`noetl.result_index`** (recommended)
- execution_id, step_name, task_label
- step_run_id, task_run_id
- iteration, page, attempt
- result_ref (json)
- status, created_at

**`noetl.step_state`** (recommended)
- execution_id, step_name
- last_result_ref
- aggregate_result_ref (manifest)
- status

These projections prevent scanning the full event stream for common reads.

---

## 10) Pagination + retry + loop (canonical mental model)

A single step with loop + pagination + retry yields a lattice of pieces indexed by:
- iteration (outer loop: endpoint/city/hotel)
- page (pagination stream inside that iteration)
- attempt (retry per page)

Each externally stored page becomes a ResultRef part, and the entire stream is represented as a manifest ref.

---

## 11) Quantum orchestration note

Quantum tools often return large measurement datasets.
Canonical pattern:
- tool returns a ResultRef (NATS Object Store or GCS)
- extracted fields store small metadata (job id, backend, shots, cost)
- manifests represent iterative algorithms (VQE/QAOA) or shot batches

This preserves a complete experiment trace keyed by `execution_id` without embedding large payloads in events.
