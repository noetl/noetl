---
sidebar_position: 15
title: Result Storage System (Canonical)
description: Reference-first result handling for NoETL DSL v2 (externalized payloads + lightweight events)
---

# Result Storage System (Canonical)

NoETL uses a **reference-first** result model: tool outputs MAY be externalized to an optimal storage backend and only **lightweight references** (ResultRef) are persisted in the event log and propagated through the workflow. This avoids bloating event tables and keeps render contexts small and deterministic.

> **Important:** There is **no special `sink` tool kind**. A “sink” is only a *pattern*: any tool task that writes data to external storage and returns a reference.

This document is aligned with the canonical runtime model:
- Step = `when + tool(pipeline) + next`
- Tool-level `eval: - expr:` drives retry/jump/break/fail/continue
- Runtime scopes: `workload` (immutable), `ctx` (execution), `vars` (step), `iter` (loop iteration)

---

## 1. Why ResultRefs exist

### 1.1 The problem
Embedding full tool outputs directly in the event log causes:
- event table bloat (large JSONB payloads)
- expensive copies across steps
- slow queries and slow template rendering
- high memory pressure on server and workers

### 1.2 The solution
Store large results externally and pass a pointer:

```
Tool produces data
   ↓
ResultHandler stores externally → returns ResultRef
   ↓
Worker emits events containing ResultRef + small extracted fields
   ↓
Server stores only metadata in event log / projections
   ↓
Next steps use extracted fields immediately
   ↓
Full data is resolved only when needed (explicit)
```

---

## 2. ResultRef structure

A ResultRef is a small JSON object representing an externally stored payload.

```json
{
  "kind": "result_ref",
  "ref": "noetl://execution/123456/step/fetch_data/task/fetch_page/abc123",
  "store": "kv",
  "scope": "execution",
  "expires_at": "2026-02-01T13:00:00Z",
  "meta": {
    "content_type": "application/json",
    "bytes": 52480,
    "sha256": "abc123...",
    "compression": "gzip"
  },
  "extracted": {
    "next_cursor": "page2",
    "total_count": 100,
    "has_more": true
  },
  "preview": {
    "_items": 100,
    "_sample": [{"id": 1}, {"id": 2}, {"id": 3}]
  }
}
```

### Fields (normative intent)
| Field | Meaning |
|------|---------|
| `kind` | MUST be `"result_ref"` |
| `ref` | Logical URI identifying the stored artifact |
| `store` | Storage tier: `memory`, `kv`, `object`, `s3`, `gcs`, `db` |
| `scope` | Lifecycle: `step`, `execution`, `workflow`, `permanent` |
| `expires_at` | TTL expiration timestamp (null for permanent) |
| `meta` | Content type, size, hash, compression |
| `extracted` | Small fields available without resolving full payload |
| `preview` | Truncated sample for UI/debugging (optional) |

---

## 3. Storage tiers

The runtime can store artifacts in different tiers. Selection may be `auto` or explicit.

| Tier | Backend examples | Typical size | Typical use |
|------|------------------|--------------|-------------|
| `memory` | in-process | <10KB | hot step-local temps |
| `kv` | NATS KV | <1MB | cursors, small payloads, small pages |
| `object` | NATS Object Store | ~1–10MB | medium artifacts, page results |
| `s3` | AWS S3 / MinIO | large | large blobs, reports |
| `gcs` | GCS | large | large blobs, reports |
| `db` | Postgres | varies | queryable intermediate results |

### Auto-selection (recommended default)
```
if bytes <= inline_max_bytes:
  inline (no ref)
elif bytes < 1MB:
  kv
elif bytes < 10MB:
  object
else:
  s3/gcs (or db if queryable required)
```

---

## 4. Scopes and lifecycle

| Scope | Meaning | Cleanup |
|------|---------|---------|
| `step` | artifact valid until step completes | step finalizer |
| `execution` | artifact valid until playbook completes | execution finalizer |
| `workflow` | artifact valid until root workflow completes | workflow finalizer |
| `permanent` | never auto-cleaned | manual only |

TTL formats: `"30m"`, `"1h"`, `"2h"`, `"1d"`, `"7d"`, `"30d"`, `"1y"`, or `"permanent"`.

---

## 5. DSL configuration (canonical placement)

Result externalization is configured **inside each tool task**. There is no step-level `sink:` and no special `sink` kind.

### 5.1 Tool task output policy

Recommended shape (canonical):

```yaml
- fetch_page:
    kind: http
    spec:
      result:
        store: { kind: auto, ttl: "1h", compression: gzip }
        inline_max_bytes: 65536
        preview_max_bytes: 1024
        select:
          - path: "$.pagination.nextCursor"
            as: next_cursor
          - path: "$.pagination.hasMore"
            as: has_more
```

**Notes**
- `spec.result.store.kind` can be `auto|memory|kv|object|s3|gcs|db`
- `select` extracts small fields into `ResultRef.extracted`
- extracted fields may be copied into `iter/vars/ctx` via `eval.set_iter/set_vars/set_ctx`

### 5.2 “Sink” pattern
A sink is simply a storage-writing task that returns a reference.

Examples:
- write rows to Postgres table and return `{store:"db", key:"table", range:"id:1-100"}`
- write a file to object store and return `{store:"object", key:"objname"}`

---

## 6. Access patterns in templates

### 6.1 What is available without resolving full payload
- extracted fields (`ResultRef.extracted.*`)
- metadata (`_ref`, `_store`, `_meta`, `_preview`)

Recommended runtime exposure (canonical):
- Each **task label** produces a task result object accessible as:
  - `{{ <step>.<task>._ref }}`
  - `{{ <step>.<task>.extracted.next_cursor }}` (or a shortcut `{{ <step>.<task>.next_cursor }}` if your renderer flattens extracted)
- Step-level `ctx/vars/iter` values are accessed by name: `{{ ctx.x }}`, `{{ vars.y }}`, `{{ iter.page }}`

### 6.2 Resolving full payload
Full payload resolution MUST be explicit. Options:
- server API: `GET /api/result/resolve?ref=...`
- a tool kind dedicated to resolution (implementation-defined), e.g. `kind: artifact` / `kind: result` with `action: get`

Example (tool-based resolution):

```yaml
- load_full_data:
    kind: artifact
    action: get
    args:
      ref: "{{ fetch_data.fetch_page._ref }}"
```

---

## 7. Pagination without huge payloads (canonical)

Pagination is modeled as a state machine inside the pipeline using `eval`:

1) fetch page → externalize payload or extract fields
2) store page (db/object) and return reference
3) if more pages → increment page and `jump` back to fetch
4) else `break`

### Example (loop + pagination + externalization)

```yaml
- step: fetch_all_endpoints
  loop:
    spec: { mode: sequential }
    in: "{{ workload.endpoints }}"
    iterator: endpoint

  tool:
    - init:
        kind: noop
        eval:
          - else:
              do: continue
              set_iter: { page: 1 }

    - fetch_page:
        kind: http
        method: GET
        url: "{{ workload.api_url }}{{ iter.endpoint.path }}"
        params:
          page: "{{ iter.page }}"
          pageSize: "{{ iter.endpoint.page_size }}"
        spec:
          result:
            store: { kind: auto, ttl: "30m", compression: gzip }
            select:
              - path: "$.paging.hasMore"
                as: has_more
              - path: "$.paging.page"
                as: page
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
              set_iter:
                has_more: "{{ outcome.result.extracted.has_more | default(false) }}"

    - store_page:
        kind: postgres
        auth: pg_k8s
        command: "INSERT INTO pagination_test_results (...) VALUES (...)"
        eval:
          - expr: "{{ outcome.status == 'error' and outcome.pg.code in ['40001','40P01'] }}"
            do: retry
            attempts: 5
            backoff: exponential
            delay: 2
          - expr: "{{ outcome.status == 'error' }}"
            do: fail
          - else:
              do: continue
              set_ctx:
                last_page_ref: "{{ outcome.result._ref | default(fetch_page._ref) }}"

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

---

## 8. Event payload rules (reference-first)

### 8.1 What events should store
Events SHOULD store:
- `outcome.status`
- small `outcome.meta`
- `ResultRef` (if externalized) and extracted fields
- error objects (small)

Events SHOULD NOT store multi-MB response bodies inline by default.

### 8.2 Projection tables
A database projection table MAY store ResultRef metadata for fast UI queries (ref list, scope, ttl, bytes, extracted, preview). The actual payload remains in external storage.

Example projection (illustrative):

```sql
CREATE TABLE noetl.result_ref (
  ref TEXT PRIMARY KEY,
  execution_id BIGINT NOT NULL,
  step_name TEXT NOT NULL,
  task_label TEXT NOT NULL,
  scope TEXT NOT NULL,
  store TEXT NOT NULL,
  bytes_size BIGINT,
  expires_at TIMESTAMPTZ,
  extracted JSONB,
  preview JSONB
);
```

---

## 9. Garbage collection

- TTL sweep deletes expired refs per tier
- step/execution/workflow finalizers delete by scope
- permanent scope requires explicit deletion

---

## 10. Notes on NATS KV vs Object Store

- KV is best for small values and cursors.
- Object store is better for medium artifacts and page payloads.
- Treat both as storage backends behind the same ResultRef interface.

(Backend maturity and operational guidance live in the runtime docs; this spec remains backend-agnostic.)

