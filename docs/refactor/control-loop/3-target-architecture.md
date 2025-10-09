# Target Architecture (To-Be)

This document defines the desired structure of the control loop, with a clear state machine, modular boundaries, and data contracts. It also captures the semantic goals (Rust-like borrow semantics for data/context ownership).

State machine (per step):
- execution_started (playbook) → step_started (step) → action_started (task) → action_completed | action_error → step_completed → next step(s) → … → execution_complete.

Principles:
- Idempotency-by-default: every marker event has app-level dedupe and DB constraints.
- Single source of truth: event log drives state; snapshot tables are derived/updated on each event.
- Canonical payloads: server computes final task config; worker executes without re-merging.
- Lineage propagation: _meta.parent_event_id flows trigger→queue→worker→events.
- Borrow semantics: 
  - Broker reads from immutable workload and prior results to schedule work; 
  - Workers receive a read-only view of context + a scoped mutable result; 
  - Results are emitted back as new events; snapshots are updated immutably; no in-place mutation of shared state.

Module responsibilities:
- EventService (server):
  - Validate and persist events; resolve catalog_id; enforce status validation; trigger broker.
  - Update snapshots: transition, workbook, workload, workflow (append/update as needed).
- Broker (server):
  - Parse playbook; determine next actionable steps.
  - Emit step_started; enqueue queue items with full execution context.
  - Iterator: expand items; emit loop_iteration; enqueue per-item jobs; aggregate results and emit loop_completed + result/action_completed.
- Queue API (server):
  - Atomic lease/complete/fail/heartbeat; maintain attempts/leases; keep idempotent inserts via (execution_id,node_id) uniqueness.
- Worker:
  - Lease → render on server (/context/render) → execute plugin → emit events (action_started/…/completed/error) → complete or fail job.

Data contracts:
- Event envelope: { event_type, status, node_id, node_name, node_type, context, result, meta, error, stack_trace, iterator/current_* for loops }.
- Queue item: { execution_id (bigint), catalog_id, node_id, action (JSON), context (JSON), priority, attempts, status }.

Refactor checkpoints:
1) Normalize execution_id across all boundaries (done recently; verify globally).
2) Enforce idempotency via DB constraints for step_started and loop_iteration.
3) Guarantee lineage propagation with parent_event_id across all paths.
4) Canonicalize payload overlay; worker uses server-rendered task.
5) Strengthen catalog_id fallback in EventService.emit.
6) Explicit set of broker triggers (include loop/result markers) and parent evaluations.
7) Snapshot update rules formalized for each event type.

Deliverables:
- Code changes per issue breakdown.
- Migration scripts for DB constraints.
- Tests validating state machine progress and idempotency.


## Playbook Schema (v2 requirements)

- metadata.path and metadata.name are mandatory; the broker and EventService use these (plus version) to resolve catalog_id.
- workload defines baseline variables; transition payloads may overlay these per step.
- workbook is a list of named actions; steps reference them using `type: workbook` and `task: <name>`.
- Steps may declare `data` which is merged with transition payloads according to precedence rules described in the broker docs (transition `data` overlays step `data`).
- A `start` router step determines initial transitions; an `end` step terminates all branches (implicit fallthrough to `end` when a step has no explicit next).

Iterator step (control-flow) schema:
- type: iterator — control step that fans out a nested task over a collection.
- Required fields: collection (list or template returning list), element (name of item variable).
- Optional fields: mode (async|sequential, default async), concurrency, enumerate, where, limit, chunk, order_by.
- Nested task represents the executable action and uses `tool: <plugin>` (e.g., http, python, postgres, duckdb, save, event_log). The task may define data/input/payload/with according to canonical precedence.
- Per-iteration results can be saved via task.save blocks (use `tool: event_log` or another store).
- The loop produces events: step_started (once), loop_iteration (per item), action_started/completed (per item, from worker), and finally aggregated result + loop_completed (emitted by server once all items finish).

Broker usage:
- On initial dispatch, broker reads metadata.path/name (and version) from workload/context to load the playbook from catalog.
- Queue context always includes `path`, `version`, and `catalog_id` for worker event linkage.
