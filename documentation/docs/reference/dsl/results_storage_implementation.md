---
sidebar_position: 9
title: Result Storage Implementation
description: Implementation guide for ResultRef and manifests
---

# Result Storage — Implementation Guide

This document describes the implementation details for **ResultRef + manifests** while remaining **event-sourced**.

> See also: `docs/runtime/results.md` (model), `docs/runtime/events.md` (envelope), `docs/spec.md` (normative semantics).

---

## A. Worker-side changes (data plane)

### A1. Add a result storage helper

Create `noetl/results.py` (or similar):

- `serialize_result(obj) -> bytes` (stable JSON encoding; safe for decimals/datetimes)
- `truncate_preview(obj, max_bytes) -> object` (UI/debug)
- `store_result_bytes(body: bytes, policy, ctx) -> ResultRef` (artifact drivers)
- `select_fields(obj, selectors) -> dict` (for routing/templating)

**Artifact drivers** (choose any subset initially):
- `localfs`
- `s3` / `minio`
- `gcs`
- `postgres_lo` (optional)

### A2. Centralize payload shaping in the event callback

Tool executors already call `log_event_callback('task_complete', ..., data=result_data, meta=...)`.

Keep executors simple. Implement storage logic in the **callback** that constructs the JSON event posted to the server:

1. Always include:
   - `payload.inputs`
2. If output size is less than or equal to inline cap:
   - set `payload.output_inline = result_data`
3. If output size exceeds inline cap:
   - upload body to artifact store
   - set `payload.output_ref = ResultRef`
   - set `payload.output_select = selected-fields` if configured
   - set `payload.preview = preview` if configured

This yields a consistent event envelope regardless of tool type (`http`, `python`, `postgres`, `duckdb`).

### A3. Correlation keys for loop/pagination/retry

When a tool call is executed under loop/pagination/retry, attach these fields to the event envelope:

- `iteration`, `iteration_id` (loop)
- `page` (pagination)
- `attempt` (retry)

These should be set by the runner/dispatcher that knows the current scope, not by the executor.

---

## B. Server-side changes (control plane)

### B1. Accept ResultRef fields in event ingestion

Update `/api/events` ingestion to persist:

- `payload.output_inline`
- `payload.output_ref`
- `payload.output_select`
- `payload.preview`

The server MUST persist events even when the artifact upload fails; in that case it SHOULD:
- mark status=`error`, and
- include error details in `payload.error`.

### B2. Projection tables (rebuildable from events)

Add projections to avoid scanning full event streams for common reads.

#### `noetl.result_index`
Keyed by:

- `execution_id`
- `step_name`
- `step_run_id`
- `tool_run_id`
- `iteration`, `page`, `attempt`

Stores:
- `result_ref` (json)
- `created_at`

#### `noetl.step_state`
Keyed by:
- `execution_id`
- `step_name`

Stores:
- `status`
- `last_result_ref` (json)
- `aggregate_result_ref` (json; manifest/materialized)

### B3. Context binding rule (preserve template ergonomics)

When building the context for the next step:

- If `output_inline` exists: inject it as `task_name`
- If `output_ref` exists:
  - inject `output_select` (or `{}`) as `task_name`
  - inject `task_name.__ref__ = output_ref`
  - optional `task_name.__preview__ = preview`

This preserves patterns like:

- `{{ evaluate_weather_directly.alert }}`

while allowing full-body access via:

- `{{ evaluate_weather_directly.__ref__ }}`

### B4. Manifest support

When `aggregate.mode=manifest`:

- emit a manifest object representing the step’s logical output:
  - store manifest inline if small, else as an artifact
  - expose as `aggregate_result_ref`

Manifests enable streaming and avoid materializing huge merged arrays.

---

## C. Minimal new tool: `artifact.get` (recommended)

Add a tool kind `artifact` with operation `get`:

- input: `ref` (ResultRef or `noetl://` logical URI)
- output: decoded JSON/body

Downstream steps can then load externalized results without special-casing.

---

## D. Exact fields added to event payload (summary)

When a tool finishes (canonical `tool.processed` or legacy `task_complete`), events SHOULD include:

- `payload.inputs`
- `payload.output_inline` **OR** `payload.output_ref`
- `payload.output_select` (recommended when output_ref is used)
- `payload.preview` (optional)

And SHOULD include correlation keys:

- `iteration`, `iteration_id`
- `page`
- `attempt`

This is sufficient to support efficient retrieval of:
- per-iteration, per-page, per-attempt pieces
- aggregated manifests
- lazy loading for next steps

