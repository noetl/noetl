---
sidebar_position: 5
title: Artifact Tool
description: Tool for reading and writing externally stored results
---

# Artifact Tool

The `artifact` tool provides a uniform interface for **reading** and (optionally) **writing** externally stored results referenced by `ResultRef`.

This tool is the standard way for downstream steps to load large outputs that were externalized from the event log.

---

## 1. When to use

Use `artifact.get` when:
- a prior step produced `payload.output_ref` (externalized result)
- the next step needs the full body (not just `output_select`)
- the step is processing a manifest (pagination/loop aggregation)

---

## 2. Tool kind

```yaml
tool:
  kind: artifact
  op: get
```

- `kind` MUST be `artifact`
- `op` MUST be one of the supported operations below

---

## 3. Operations

### 3.1 `get`

Fetch and return the artifact body for a given reference.

#### Inputs

- `ref` (required)
  - may be a **ResultRef object**
  - or a **logical URI** (`noetl://execution/...`)

Optional:
- `resolve_manifest` (bool, default: true)
  - If `ref` is a manifest, resolve and return the resolved parts.
- `mode` (string, default: `json`)
  - `json` → parse JSON and return an object
  - `text` → return decoded text
  - `bytes` → return raw bytes (base64 or stream handle, depending on runtime)
- `max_bytes` (int)
  - safety cap on fetched body
- `range` (object)
  - request a byte range (for large files)
  - `{ start: 0, end: 1048575 }`

#### Outputs

- `status` (success|error)
- `data` (object|string)
- `meta`
  - `content_type`, `compression`, `bytes`, `sha256`, and storage info

#### Example

```yaml
- step: load_users_manifest
  tool:
    kind: artifact
    op: get
    ref: "{{ fetch_users.users_manifest.__ref__ }}"
    resolve_manifest: true
    mode: json
```

### 3.2 `head` (recommended)

Return only artifact metadata (no body). Useful for planning and debugging.

Inputs:
- `ref` (required)

Outputs:
- `status`
- `meta`

### 3.3 `put` (optional)

Store a body as an artifact and return a ResultRef.

Use when:
- a python task produces a large output that should be externalized
- a step wants to persist intermediate datasets

Inputs:
- `data` (required; json/text/bytes)
- `content_type` (default: application/json)
- `compression` (optional)
- `store` (driver + uri template)

Outputs:
- `status`
- `ref` (ResultRef)

---

## 4. Security & access model

### 4.1 Worker access

Workers typically access artifacts directly via the storage driver credentials (S3/GCS/etc.).

### 4.2 Server access

The server MAY:
- stream artifacts to clients, or
- generate signed URLs for clients (recommended)

In either model, the event log stores only a `ResultRef` and metadata.

---

## 5. Manifest handling

When `resolve_manifest=true` and `ref` is a manifest:

- `artifact.get` returns either:
  - `data = { manifest, parts: [ {data, meta}, ... ] }` (default)
  - OR streaming iterator handle (future extension)

For very large manifests, prefer:
- resolve parts incrementally (loop over `parts` refs)
- materialize into DuckDB/Postgres

---

## 6. DSL pattern: passing refs between steps

If the prior step externalized its output, the server binds:

- `task_name.__ref__` (ResultRef)
- `task_name.__preview__` (optional)
- `task_name.<selected fields>` (from output_select)

So you can:

- use selected fields in routing:
  - `{{ fetch_users.next_cursor }}`

- load the full body when needed:
  - `ref: "{{ fetch_users.__ref__ }}"`

---

## 7. Recommended implementation notes

- Prefer a single resolver in the server:
  - resolve `noetl://...` to `(driver, uri, artifact_id)`
- Maintain `noetl.artifact` metadata table in Postgres.
- Implement `artifact.get` as:
  - worker-side direct download (for internal pipelines)
  - server-side signed URL/stream (for UI and external clients)



---

## 10. Postgres DDL (recommended)

A concrete PostgreSQL schema for event log + artifact metadata + projections is provided in:

- `docs/runtime/schema/postgres.sql`



---

## Postgres schema

A recommended PostgreSQL DDL for the event log + artifacts + projections is included at:

- `docs/runtime/schema/postgres.sql`

