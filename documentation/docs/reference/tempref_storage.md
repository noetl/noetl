---
sidebar_position: 17
title: ResultRef / TempRef Storage System (Canonical v10)
description: Reference-first (zero-copy) data passing using ResultRef pointers — aligned with Canonical v10 DSL
---

# ResultRef / TempRef Storage System (Canonical v10)

Canonical v10 uses **reference-first** results: large tool outputs are stored externally and only lightweight pointers are propagated and persisted.

Terminology:
- **ResultRef** is the canonical pointer object in v10.
- **TempRef** is a legacy name; if it exists in older components, treat it as an alias of ResultRef semantics.

Authoritative reference docs:
- `documentation/docs/reference/result_storage.md`
- `documentation/docs/reference/dsl/runtime_results.md`

---

## 1) Why references exist

Embedding full tool outputs directly in the event log causes:
- event-store bloat (large JSON payloads)
- expensive copies across steps
- slower queries and template rendering
- high memory pressure on server/workers

Canonical solution:
- store large bodies externally (Postgres, NATS KV/Object Store, GCS, etc.)
- emit/persist only **metadata + references + extracted fields**

---

## 2) ResultRef structure (canonical)

```json
{
  "kind": "result_ref",
  "ref": "noetl://execution/<eid>/step/<step>/task/<task>/run/<task_run_id>/attempt/<n>",
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
    "page": 2
  },
  "preview": {
    "truncated": true,
    "bytes": 2048,
    "sample": [{"id": 1}]
  }
}
```

Key idea: downstream steps should rely on `extracted` fields for routing/state without resolving the full body.

---

## 3) DSL configuration (Canonical v10)

Result externalization is configured **per task** under `task.spec.result`:

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
          kind: auto
          scope: execution
          ttl: "1h"
          compression: gzip
        select:
          - path: "$.paging.hasMore"
            as: has_more
          - path: "$.paging.page"
            as: page
```

---

## 4) Resolving references (explicit)

Resolving full bodies MUST be explicit (never automatic in routing/policy evaluation).
Common approaches:
- server API endpoint (implementation-defined)
- a dedicated resolution tool task (for example `kind: artifact`, `action: get`)

Example tool-based resolution:
```yaml
- resolve_page:
    kind: artifact
    action: get
    args:
      ref: "{{ ctx.last_page_ref }}"
```
