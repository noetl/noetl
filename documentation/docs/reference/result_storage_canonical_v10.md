---
sidebar_position: 6
title: Result Storage & References (Canonical)
description: Reference-first result storage for NoETL DSL v2 (Canonical v10) — NATS KV/ObjectStore, GCS, Postgres, manifests, and event-sourced access
---

# Result Storage & References — Canonical v10

This document **merges and supersedes** the older result/TempRef docs and updates them to the **latest Canonical v10 DSL** rules:

- No `sink` concept: **“sink” is a pattern**, not a tool kind.
- No `eval:` / `expr:`. Outcome handling uses **`spec.policy.rules` with `when`**.
- Events and step context pass **references only** (inline only for small previews / extracted fields).
- Storage backends: **NATS KV**, **NATS Object Store**, **Google Cloud Storage**, **Postgres**.

---

## 0) Goals

1. **Event-sourced correctness**: event log remains the source of truth for *what happened*.
2. **Efficiency**: large payloads MUST NOT bloat the event log.
3. **Composable access**: downstream steps can reference:
   - latest result
   - per-attempt (retry) results
   - per-page (pagination) results
   - per-iteration (loop) results
   - combined results via **manifests** (streamable)
4. **Pluggable storage**: store results in Postgres / NATS KV / NATS Object Store / GCS, and keep only refs in events.
5. **Streaming-friendly**: combine via manifests; avoid giant merged arrays.

---

## 1) Concepts

### 1.1 Tool output vs step result
- **Tool output**: output of a single task invocation (HTTP call, DB command, Python run).
- **Step result**: the logical outcome of a step; may include multiple tool outputs from pagination/loop/retry.

### 1.2 Reference-first rule
A task output is either:
- **inline** (only if size <= cap), OR
- stored externally with a **ResultRef** (preferred).

The event log stores: metadata + ResultRef + extracted fields + preview.

---

## 2) ResultRef (canonical pointer)

### 2.1 Structure
```json
{
  "kind": "result_ref",
  "ref": "noetl://execution/123/step/fetch/task/fetch_page/run/abc123",
  "store": "nats_kv|nats_object|gcs|postgres",
  "scope": "step|execution|workflow|permanent",
  "expires_at": "2026-02-01T13:00:00Z",
  "meta": {
    "content_type": "application/json",
    "bytes": 52480,
    "sha256": "abc123...",
    "compression": "gzip"
  },
  "extracted": {
    "has_more": true,
    "page": 2,
    "next_cursor": "c_123"
  },
  "preview": {
    "truncated": true,
    "bytes": 1024,
    "sample": [{"id": 1}, {"id": 2}]
  }
}
```

### 2.2 Logical vs physical addressing
- `ref` is a **logical URI** (`noetl://...`) stable across backends.
- Physical details (bucket/key/object/table range) live in `meta` and/or a server mapping.

---

## 3) Storage backends (canonical)

### 3.1 NATS KV (small)
Use for:
- cursors, tokens, small JSON
- small page payloads (within practical limits)

Recommended ResultRef meta:
- `meta.bucket`, `meta.key`

### 3.2 NATS Object Store (medium)
Use for:
- medium artifacts (page payloads, streamed chunks)

Recommended ResultRef meta:
- `meta.bucket`, `meta.key`, optional `meta.etag`

### 3.3 Google Cloud Storage (large / durable)
Use for:
- large payloads
- longer retention
- cross-system access

Recommended ResultRef meta:
- `meta.bucket`, `meta.object` (or `meta.uri`)

### 3.4 Postgres (queryable)
Use for:
- queryable intermediate tables (facts, audit rows)
- projections and indices for refs

Recommended ResultRef meta:
- `meta.schema`, `meta.table`, `meta.range` (or `meta.pk`)

> Canonical: Postgres is both **event store/projections** and optionally a **result store** (tables).

---

## 4) Auto-selection (recommended)

A runtime SHOULD support `store.kind: auto` with size-aware selection:

- `<= inline_max_bytes` → inline
- `<= kv_max_bytes` → NATS KV
- `<= object_max_bytes` → NATS Object Store
- else → GCS (or Postgres table when queryability is required)

Thresholds are runtime config, but the **tier model** is stable.

---

## 5) DSL configuration (Canonical v10)

### 5.1 Where config lives
Result storage config is per-task under `task.spec.result`.

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
        select:
          - path: "$.paging.hasMore"
            as: has_more
          - path: "$.paging.page"
            as: page
          - path: "$.paging.nextCursor"
            as: next_cursor
```

### 5.2 Extracted fields
`select` fields become `ResultRef.extracted.*`.
They are small, safe for:
- routing decisions
- pagination state
- UI/observability

---

## 6) Manifests (combined result without bloat)

### 6.1 Manifest object
```json
{
  "kind": "manifest",
  "strategy": "append|concat|merge|replace",
  "merge_path": "$.data.items",
  "parts": [
    { "ref": "noetl://.../page/1/..." },
    { "ref": "noetl://.../page/2/..." }
  ],
  "total_parts": 2,
  "total_bytes": 30270
}
```

### 6.2 Storage
Manifests are stored reference-first like any other result:
- inline if tiny
- else NATS Object Store / GCS / Postgres

---

## 7) Correlation keys (MUST for indexing)

Each `task.done` event SHOULD include when applicable:
- `iteration`, `iteration_id` (loop)
- `page` (pagination)
- `attempt` (retry)
- `step_run_id`, `task_run_id`

This supports retrieval patterns:
- page 3 of iteration 7
- last successful attempt for page 2
- all parts for step X

---

## 8) Passing results to next steps (reference-only)

Canonical rule: **server binds only extracted + refs**, not full bodies.

Recommended binding for task label `fetch_page`:
- `fetch_page.<field>` for extracted fields
- `fetch_page.__ref__` for ResultRef
- optional `fetch_page.__preview__` for small UI/debug sample

Downstream steps:
- use extracted fields directly
- explicitly resolve full payload if needed

---

## 9) Resolving refs (explicit)

Full payload resolution MUST be explicit:
- server API: `GET /results/resolve?ref=...`
- or tool: `kind: artifact` / `kind: result` with `action: get`

Example:
```yaml
- load_full_page:
    kind: artifact
    action: get
    args:
      ref: "{{ fetch_page.__ref__ }}"
```

---

## 10) Canonical pagination + streaming pattern (single worker logical thread)

Use **loop** for outer fan-out (endpoints/cities/hotels), but inside each iteration run a **sequential stream**:
- fetch page
- transform
- route store by response code (200 vs 404 etc.)
- decide continue (jump fetch) or finish (break)

All control is via **task policy**: `spec.policy.rules`.

---

## 11) Implementation requirements (what to build)

### 11.1 Worker-side (data plane)
Implement a result handler that runs after each task:
1. stable serialize (JSON)
2. apply `task.spec.result`:
   - preview (optional)
   - select/extract (optional)
   - choose store backend
   - write payload externally (unless inline)
3. return final `outcome` with:
   - `outcome.result` containing small fields
   - `outcome.result.__ref__` containing ResultRef (if externalized)

Emit `task.done` with:
- `outcome.status`, `outcome.error`, `outcome.meta`
- inline small result or ResultRef (+ extracted + preview)
- correlation keys

### 11.2 Server-side (control plane)
On event ingest:
- persist event
- upsert projections:
  - `result_index` keyed by execution/step/task/iteration/page/attempt
  - `step_state` keyed by execution/step with latest refs and status

Context binding:
- inject extracted fields and ResultRefs only

---

## 12) Garbage collection

Use `scope` + `ttl`:
- `step` → cleanup at step finalize
- `execution` → cleanup at execution finalize
- `workflow` → cleanup at workflow finalize
- `permanent` → manual only

Backend-specific deletes:
- NATS KV: delete key
- NATS Object Store: delete object
- GCS: delete object
- Postgres: delete rows (or partition retention)

---

## 13) Terminology: TempRef vs ResultRef

Legacy docs used **TempRef** (`kind: temp_ref`) for step-to-step pointers.

Canonical v10 uses **ResultRef** (`kind: result_ref`) everywhere.

If reading legacy:
- treat `temp_ref` as alias of `result_ref` at resolution time
- emit only `result_ref` going forward
