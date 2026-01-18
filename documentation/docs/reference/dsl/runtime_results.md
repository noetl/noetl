---
sidebar_position: 4
title: Result Storage & Access
description: How NoETL stores and retrieves tool outputs and step results
---

# NoETL Runtime Result Storage & Access

This document defines how NoETL stores and retrieves **tool outputs** and **step results** in an **event-sourced** system—efficiently and at scale.

## Goals

1. **Event-sourced correctness**: the event log remains the source of truth for *what happened*.
2. **Efficiency**: large payloads must not bloat the event log or overload queries.
3. **Composable access**: downstream steps must be able to reference:
   - the **latest** result
   - **per-attempt** results (retry)
   - **per-page** results (pagination)
   - **per-iteration** results (loop)
   - **combined/aggregated** results (optional)
4. **Pluggable storage**: results can be stored inline, in the event log, or externalized to an artifact store (S3/GCS/MinIO/localfs/DB large-object), with only a **reference** kept in events.
5. **Streaming-friendly**: allow “combined results” to be represented as a **manifest** referencing parts (pages/iterations), rather than materializing a massive array.

---

## 1. Concepts

### 1.1 Tool call output vs Step result

- **Tool call output**: the raw output of a single tool invocation (e.g., one HTTP response).
- **Step result**: the logical output of a step, potentially derived from:
  - multiple tool call outputs (pagination)
  - multiple iterations (loop)
  - multiple attempts (retry)

A step may publish:
- **part results** (many) — tool call outputs, iteration outputs, page outputs
- **aggregate result** (one) — a combined view for convenient downstream use

### 1.2 Result reference

NoETL represents results using a **ResultRef** (a lightweight pointer):

```json
{
  "kind": "result_ref",
  "ref": "noetl://execution/<execution_id>/step/<step>/call/<tool_run_id>",
  "store": "inline|eventlog|artifact",
  "artifact": {
    "id": "art_...",
    "uri": "s3://bucket/.../payload.json.gz",
    "content_type": "application/json",
    "compression": "gzip",
    "bytes": 123456,
    "sha256": "..."
  },
  "preview": {
    "truncated": true,
    "bytes": 32768,
    "data": {"...": "..."}
  }
}
```

Key idea:
- The **event log** stores the pointer (and optionally a small preview).
- The **artifact store** holds the large body.

---

## 2. Storage tiers

### 2.1 Inline (small)
- Store output directly in the event payload.
- Size capped (e.g., `inline_max_bytes = 64KB`).

Use for:
- small JSON responses
- status objects
- short summaries

### 2.2 Eventlog (medium)
- Store output in a dedicated `result` column/table inside Postgres (still part of the event store domain).
- Useful when:
  - output is moderate (e.g., 64KB–2MB)
  - you want transactional proximity

### 2.3 Artifact store (large)
- Store output in external storage (S3/GCS/MinIO/localfs/DB large object).
- Store only `ResultRef` in events.

Use for:
- large paginated API fetches
- big query result sets
- file outputs
- quantum measurement datasets

---

## 3. Addressing model (how you reference pieces)

### 3.1 Logical URIs

NoETL uses **logical** `noetl://` URIs to identify results, independent of physical storage:

- Tool call output:
  - `noetl://execution/<eid>/step/<step>/call/<tool_run_id>`

- Retry attempt output:
  - `noetl://execution/<eid>/step/<step>/attempt/<n>/call/<tool_run_id>`

- Loop iteration output:
  - `noetl://execution/<eid>/step/<step>/iteration/<i>/call/<tool_run_id>`

- Pagination page output:
  - `noetl://execution/<eid>/step/<step>/page/<p>/call/<tool_run_id>`

- Combined (aggregate) step result:
  - `noetl://execution/<eid>/step/<step>/result`

The server maintains a mapping from logical refs to physical artifact URIs.

### 3.2 Correlation keys

Every tool output event SHOULD include these fields (when applicable):
- `step_run_id`
- `tool_run_id`
- `attempt` (retry)
- `iteration` and `iteration_id` (loop)
- `page` (pagination)

These keys enable deterministic retrieval of *pieces*.

---

## 4. Aggregation without bloat: manifests

### 4.1 Manifest-based aggregation

Instead of merging 1,000 pages into one giant JSON array, NoETL can publish a **manifest**:

```json
{
  "kind": "manifest",
  "strategy": "append",
  "merge_path": "data.items",
  "parts": [
    {"ref": "noetl://.../page/1/call/..."},
    {"ref": "noetl://.../page/2/call/..."}
  ]
}
```

Downstream steps can:
- stream parts
- selectively load pages
- materialize on demand into DuckDB/Postgres

### 4.2 When to materialize a combined result

Materialize (store a combined body) only when:
- the combined output remains bounded
- downstream requires random access to the entire merged dataset

Otherwise prefer manifest aggregation.

---

## 5. DSL extension: `result` storage policy

A step MAY specify a `result` block to control how outputs are stored and published.

### 5.1 Step-level result policy

```yaml
- step: fetch_users
  tool:
    kind: http
    endpoint: "{{ workload.base_url }}/users"
    method: GET

  loop:
    in: "{{ workload.regions }}"
    iterator: region

  retry:
    max_attempts: 5
    backoff:
      type: exponential
      delay_seconds: 1
      max_delay_seconds: 30

  pagination:
    type: response_based
    continue_while: "{{ response.data.next is not none }}"
    next_page:
      params:
        cursor: "{{ response.data.next }}"

  result:
    store:
      kind: artifact
      inline_max_bytes: 65536
      artifact:
        driver: s3              # s3|gcs|minio|localfs|postgres_lo
        uri: "s3://noetl-results/{{ execution_id }}/{{ step.name }}/{{ region }}/{{ tool_run_id }}.json.gz"
        content_type: application/json
        compression: gzip

    publish:
      parts_as: users_pages      # list of ResultRef (per page/call)
      combined_as: users_manifest # manifest ResultRef (or inline)

    aggregate:
      mode: manifest             # manifest|materialize
      strategy: append
      merge_path: data.data
```

### 5.2 Publish semantics

- `parts_as`: exposes a collection of piece refs (per-page, per-iteration, per-attempt).
- `combined_as`: exposes a single ref representing the step’s logical output.

Downstream steps can use these published values through normal templating (as refs):
- pass the ref to a loader tool
- pass the ref to DuckDB for direct scan
- request the server to resolve a signed URL

---

## 6. Runtime implementation strategy (event-sourced & efficient)

### 6.1 What gets written where

**Worker**
- executes tool call
- produces tool output
- applies result storage policy:
  - inline if small
  - artifact upload if large
- emits `tool.processed` event with:
  - `payload.output_inline` (optional)
  - `payload.output_ref` (optional)
  - `payload.preview` (optional)

**Server**
- persists the event
- updates projections:
  - `step_last_result_ref` (latest)
  - `result_index` (lookup by step/iteration/page/attempt)
  - optional `step_aggregate_ref` (manifest/materialized)

### 6.2 Projection tables (recommended)

To avoid scanning the full event stream for common reads, maintain projections:

1) `noetl.result_index`
- `execution_id`
- `step_name`
- `step_run_id`
- `tool_run_id`
- `iteration`, `page`, `attempt`
- `result_ref` (json)
- `created_at`

2) `noetl.step_state`
- `execution_id`
- `step_name`
- `last_result_ref` (json)
- `aggregate_result_ref` (json)
- `status`

These tables are derived from events and can be rebuilt.

### 6.3 Server APIs (recommended)

- `GET /executions/{id}/steps/{step}/result` → returns aggregate ref or inline result
- `GET /executions/{id}/steps/{step}/parts?iteration=&page=&attempt=` → returns list of refs
- `GET /artifacts/{artifact_id}` → streams artifact (or returns signed URL)

Workers can use these APIs to resolve refs when needed for downstream tools.

---

## 7. How next steps access results

### 7.1 Lightweight path (inline)
If the result is inline, the server MAY include it directly in the step context passed to the next step.

### 7.2 Reference path (artifact/eventlog)
If the result is stored externally, the server passes only `ResultRef` into context.

Downstream steps then:
- pass the ref to a loader tool (e.g., `artifact.get`, `http.get` presigned URL, `duckdb.scan`)
- or request the server to materialize a view

### 7.3 Combining pieces
Downstream steps can choose:
- iterate over `parts_as` for streaming processing
- materialize `combined_as` when needed

---

## 8. Pagination + retry + loop example (what gets indexed)

A single step with loop + pagination + retry can generate outputs indexed as:

- By **iteration** (loop): region=0..N
- By **page** (pagination): 1..P
- By **attempt** (retry): 1..A

Each tool output maps to a unique tuple:

`(execution_id, step_name, iteration, page, attempt, tool_run_id)`

This is sufficient to retrieve:
- “give me page 3 for region 2”
- “give me all pages for region 2”
- “give me the final successful attempt for region 2/page 3”
- “give me the manifest for region 2” (aggregate)

---

## 9. Quantum note

Quantum tools often produce large outputs (measurement counts, shots, calibration metadata). Store the body in an artifact store and keep only:
- job_id
- backend metadata
- result refs

in the event log. Manifests work well for shot batches or iterative algorithms.



---

## 9. Result payload conventions (recommended)

NoETL separates **small** results (kept close to events) from **large** results (stored externally), while keeping the event log authoritative.

Within an event `payload`, prefer these fields:

- `payload.inputs`: rendered input snapshot (safe/redacted)

Result fields:
- `payload.output_inline`: small result body (size-capped)
- `payload.output_ref`: a ResultRef pointing to externally stored result body
- `payload.preview`: truncated sample for UI/debugging

Errors/metadata:
- `payload.error`: structured error object
- `payload.meta`: free-form metadata (http status, row counts, provider job_id, etc.)

See `docs/runtime/results.md` for ResultRef schema, manifests, and access patterns.

