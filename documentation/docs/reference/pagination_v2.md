---
sidebar_position: 12
title: HTTP Pagination (Canonical)
description: Canonical pagination model for NoETL DSL v2 (eval + jump + iter state, reference-first results)
---

# HTTP Pagination (Canonical v2)

This document consolidates and replaces the prior pagination materials (`pagination.md`, `pagination_design.md`, `pagination_implementation_summary.md`) and updates them to the **canonical NoETL DSL v2** model.

## Canonical alignment

Pagination in canonical v2 is expressed as **pipeline control flow** inside a step:

- A step executes an ordered pipeline: `step.tool: [task1, task2, ...]`
- Each task can apply **tool-level `eval: expr`** directives
- Pagination is a loop inside the pipeline implemented with:
  - `do: jump` back to the fetch task, and
  - iteration-scoped state in `iter.*`
- Retry is also expressed via `eval` (`do: retry`)
- Large page payloads are handled with **reference-first results** (store externally; emit references)

There is **no canonical** `loop.pagination:` block and no step-level `retry:` wrapper.

---

## 1) What pagination solves

Many REST APIs return data in pages. Pagination support must:
- request the first page
- decide whether another page exists (flag/cursor/offset)
- construct the next request (page+1, offset+limit, cursor token, header token, etc.)
- optionally merge or stream results across pages
- stop safely (max pages / max time)
- be observable (events for each page, retry attempt, and final stop condition)

Canonical v2 implements these capabilities as a **deterministic mini state machine** in the step pipeline.

---

## 2) Core pagination model

### 2.1 Control actions used
Pagination uses the same pipeline actions used for retry and polling:

- `continue` — proceed to next task
- `retry` — rerun current task (bounded attempts, backoff/delay)
- `jump` — set program counter to a labeled task (pagination loop)
- `break` — end the step successfully (no more pages)
- `fail` — end the step with error

### 2.2 State location (iter)
Pagination state MUST live in **iteration scope** (`iter.*`) when the step is looped over endpoints/items, and MAY live in `vars.*` when not looped.

Recommended `iter` fields:
- `iter.page` (page-number pattern)
- `iter.offset`, `iter.limit` (offset pattern)
- `iter.cursor` (cursor pattern)
- `iter.has_more` (continuation boolean)
- `iter.pages_fetched` (safety counter)

### 2.3 Continuation decision
Continuation is evaluated after the fetch (and optionally after store/transform), typically by setting `iter.has_more` in `eval.set_iter` based on `outcome.result` or extracted fields.

The pipeline then executes a small decision task (often `noop`) whose `eval` chooses:
- `jump` back to fetch when `iter.has_more == true`
- `break` otherwise

---

## 3) Supported pagination patterns

### 3.1 Page-number pagination
Common API signals:
- response includes `page`, `pageSize`, `hasMore` (or similar)

Canonical approach:
- initialize `iter.page = 1`
- request with `page=iter.page`
- compute `iter.has_more` from response (or extracted fields)
- on `iter.has_more`, set `iter.page = iter.page + 1` and `jump` to fetch

### 3.2 Offset/limit pagination
Common API signals:
- response includes `offset`, `limit`, `has_more` or derived from counts

Canonical approach:
- initialize `iter.offset = 0`, `iter.limit = N`
- request with `offset=iter.offset`, `limit=iter.limit`
- if `has_more`, set `iter.offset = iter.offset + iter.limit` and `jump` to fetch

### 3.3 Cursor-based pagination
Common API signals:
- response includes `next_cursor` / `nextPageToken` / continuation token
- continuation depends on token presence

Canonical approach:
- initialize `iter.cursor = null`
- request includes cursor when present
- set `iter.cursor` to `next_cursor` from response
- set `iter.has_more = (iter.cursor is not null/empty)`
- `jump` to fetch while `iter.has_more` is true

### 3.4 Header-driven pagination (Link / tokens)
Common API signals:
- cursor or “next” URL is in headers

Canonical approach:
- read token/header values from tool outcome helpers (e.g., `outcome.http.headers`)
- store in `iter.cursor` or `iter.next_url`
- `jump` while token/url exists

---

## 4) Retry and resilience (pagination-safe)

### 4.1 Retry applies per page request
Retries SHOULD apply to the fetch task, and MAY also apply to downstream tasks (transform/store) independently.

Typical retryable conditions:
- HTTP: 429, 5xx, timeouts, transient network errors
- DB: serialization failures, deadlocks

Retry decision is expressed by `eval` on the specific task that failed (not global).

### 4.2 Ordering and idempotency
Pagination implies repeated requests; retry amplifies this. Recommended practices:
- Prefer idempotent fetches (GET) and idempotent stores (dedupe keys / upserts)
- Include execution id + page/offset/cursor in stored rows to support replay auditing
- Consider “at least once” semantics for store tasks unless strict exactly-once is required

---

## 5) Result handling and memory safety

Canonical v2 prefers **streaming storage** (store each page, return references) over accumulating everything in memory.

### 5.1 Reference-first page payloads
- Large response bodies SHOULD be externalized (db/object/kv)
- Events should store metadata + a ResultRef with small extracted fields:
  - `{ store, key, checksum, size, schema_hint, extracted }`
- Downstream steps should rely on extracted fields (e.g., cursor, counts), and resolve full payload only when needed

### 5.2 Merge strategies (conceptual)
If accumulation is required (small datasets), define a merge policy at the runtime/tool layer (implementation-defined). Common strategies:
- **append**: concatenate arrays
- **extend**: flatten nested arrays and concatenate
- **replace**: keep the last response only
- **collect**: store each page response as an element

In canonical v2, “merge” is not a special DSL block; it is realized either by:
- a transform task that merges `_prev` into an accumulator kept in `vars/iter`, or
- external storage (preferred) and later query/aggregation.

---

## 6) Safety limits

Pagination MUST include guardrails to avoid infinite loops and runaway costs. Recommended limits:
- `iter.pages_fetched` with max-pages cutoff
- maximum wall-clock time per step run
- maximum total bytes stored per execution (policy)

These limits may be expressed as:
- `tool.spec` policy (timeouts/limits), and/or
- `eval` rules that `fail` when limits exceed thresholds.

---

## 7) Observability and event model

For each page attempt, the worker should emit events capturing:
- task started / processed with attempt number
- response status and minimal metadata
- continuation decision (jump/break) as a directive
- stored reference identifiers (if externalized)

This enables:
- replay and deterministic debugging
- per-page latency and error analysis
- automated optimization (adaptive page sizes, rate limit handling)

---

## 8) Migration notes (from legacy `loop.pagination`)

If you previously used a declarative `loop.pagination` block with fields like:
- `continue_while`, `next_page`, `merge_strategy`, `merge_path`, `max_iterations`, `retry`

In canonical v2, map these to:
- `iter.*` state initialization
- fetch task that sets `iter.has_more` and next request parameters (via `set_iter`)
- pagination decision task (`noop`) that jumps/breaks
- retry rules on fetch task (and optionally store/transform tasks)
- optional accumulator/merge handled by a transform task or external storage

---

## 9) Recommended canonical pagination pipeline (conceptual shape)

A canonical pagination step typically contains these tasks (labels are examples):

1. **init**: initialize `iter.page/offset/cursor` and `iter.pages_fetched`
2. **fetch_page**: execute HTTP request for the current page
3. **transform** (optional): reshape/validate/normalize
4. **store_page** (recommended): persist page and return ResultRef
5. **paginate**: decide `jump` to `fetch_page` or `break`

All flow decisions are captured by `eval` directives, making pagination a deterministic, event-sourced program.

---

## 10) Design principles (why this model)

- **One mechanism** (`eval`) for retry, pagination, polling, and early-exit
- **Clear separation** of responsibilities:
  - worker executes pipelines and emits events
  - server routes steps using `next[]`
- **Petri-net compatibility**:
  - step is the transition; `next[]` are arcs; pagination is internal transition firing logic
- **Scalable results** via reference-first storage
- **Replayable** and debuggable from the event log

---

## Related docs
- Execution Model (canonical): `execution_model_v2.md`
- Pipeline Execution (canonical): `pipeline_execution_v2.md`
- Retry Handling (canonical): `retry_mechanism_v2.md`
- Result Storage (canonical): `result_storage_v2.md`
- Loop Iteration (canonical): `iterator_v2.md`
