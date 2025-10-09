# NoETL Server ↔ Worker Communication Algorithm

This document describes the end‑to‑end flow between the API server and workers, with precise code references, and outlines the issues to fix in the enqueue → work → report → event → next‑enqueue pipeline.

Contents:
- High‑level lifecycle
- Server: enqueue logic (broker/processors)
- Queue API contracts (lease/heartbeat/complete/fail)
- Worker behavior (lease → render → execute → emit events → complete)
- Event ingestion and broker triggers
- Known gaps and what to fix


## 1) High‑level lifecycle

1. Client starts an execution (via runtime APIs), which causes an `execution_start(ed)` event to be emitted and the initial workload persisted. The server will then evaluate the playbook and enqueue the first actionable step (if any).
2. Workers poll the queue for jobs, lease a job, execute the step, emit action events back to the server, and mark the queue item complete or failed.
3. Each event persisted triggers broker analysis that may enqueue follow‑up steps. Loops generate per‑iteration jobs and a final aggregated result.

Key components:
- Event persistence service: noetl/api/routers/event/service.py
- Broker/evaluation: noetl/api/routers/event/processing/broker.py
- Queue endpoints: noetl/api/routers/queue.py
- Worker implementation: noetl/worker/worker.py
- Broker notifications: noetl/api/routers/broker/service.py


## 2) Server: event persistence and trigger

When anyone (client or worker) submits an event, EventService writes it to the `noetl.event` table, enforces catalog linkage, and triggers broker processing.

- Event ingestion: noetl/api/routers/event/service.py
  - emit(): lines ~171–758
    - ID generation and status validation: 175–195
    - Parent event derivation from context/_meta: 216–233
    - Node name/type inference from context: 234–272
    - Dedupe guards (step_started, loop_iteration): 282–317
    - Resolve catalog_id (REQUIRED) from metadata/context/work/workload: 328–387
    - Upsert event record (insert via EventLog): 462–521
    - Error logging side‑channel: 523–546
    - Workload upsert on execution_start(ed): 548–562
    - route_event dispatch (best effort): 565–571
    - Completion handler for child executions → maps results back to parent: 601–725
    - Notify BrokerService.on_event_persisted and proactively run `evaluate_broker_for_execution`: 726–749

- Broker notification: noetl/api/routers/broker/service.py
  - on_event_persisted(): lines ~29–124
    - Enqueues a `result_aggregation` queue job when a `loop_completed` event appears, and schedules broker analysis.


## 3) Server: broker evaluation and enqueue

The broker reads the workload and playbook, figures out the next actionable step(s), and enqueues jobs into `noetl.queue`.

- Entry point: noetl/api/routers/event/processing/broker.py
  - evaluate_broker_for_execution(): 18–72
    - Guards against error states, then:
    - _handle_initial_dispatch(): 81–447
    - _advance_non_loop_steps(): 599–740
  
- Initial dispatch: _handle_initial_dispatch()
  - Checks for pending queue items and prior progress: 91–113
  - Loads workload context and playbook (via catalog): 116–170, 148–166
  - Determines the first actionable step, builds task, merges transition payloads (input/payload/with + data overlay): 178–307
  - Emits a `step_started` event (idempotent): 377–401
  - Encodes task for queue and INSERTs into `noetl.queue`: 410–437
    - Uses the execution’s first event to derive `catalog_id`: 413–419
    - Queue insert SQL: 420–434 (node_id = f"{execution_id}:{next_step_name}")

- Loop step expansion: _handle_loop_step(): 450–596
  - Renders items, emits `loop_iteration` events, enqueues a job per item: 492–596
    - Queue insert SQL for each item: 572–587 (node_id = f"{execution_id}:{step_name}:{idx}")

- Post‑step advancement: _advance_non_loop_steps(): 599–740
  - Detects completed steps from `action_completed` or `step_result` events: 612–649
  - Emits `step_completed` (idempotent) to allow controllers to enqueue the next transition: 724–735


## 4) Queue API contracts (server)

- File: noetl/api/routers/queue.py
  - Helper: normalize_execution_id(): 14–31
    - Defers to normalize_execution_id_for_db to ensure bigint execution_id for all SQL params touching queue/event.
  - Helper: get_catalog_id_from_execution(): 33–46
    - Reads catalog_id from the execution’s first event.
  - POST /queue/enqueue → enqueue_job(): 47–93
    - Validates input, normalizes execution_id via helper, resolves `catalog_id` via first event, inserts into `noetl.queue`: 65–86
  - POST /queue/lease → lease_job(): 95–152
    - Atomically sets status=leased, assigns worker_id, increments attempts, sets lease_until / last_heartbeat: 112–129
    - Returns a JSON object with job fields; normalizes `context` for consumers: 140–146
  - POST /queue/{id}/complete → complete_job(): 154–636
    - Marks status=done; then best‑effort emits parent/loop result mapping to events and triggers broker re‑evaluation: 169–629
  - POST /queue/{id}/fail → fail_job(): 638–671
    - If retry=false or attempts>=max_attempts → status=dead; else requeue with delay: 657–665
  - POST /queue/{id}/heartbeat → heartbeat_job(): 674–698
    - Updates last_heartbeat and optional lease extension: 685–690
  - GET /queue → list_queue(): 701–727; GET /queue/size: 729–741


## 5) Worker behavior

- File: noetl/worker/worker.py
  - QueueWorker
    - Leasing: _lease_job(): 356–370 → POST /queue/lease
    - Completion: _complete_job(): 372–378 → POST /queue/{id}/complete
    - Failure: _fail_job(): 380–386 → POST /queue/{id}/fail (defaults to terminal dead)
    - Execution: _execute_job_sync(): 391–796
      - Renders context/task on server: POST /context/render (lines 399–431)
      - Determines task type (incl. `result_aggregation`), handles special plugins: 487–515
      - Prepares and emits `action_started` event via noetl.plugin.report_event: 560–580
        - start_event context includes { work: <ctx>, task: <cfg> } and loop metadata when present.
      - Executes plugin based on task type (http/python/duckdb/postgres/secrets/workbook/playbook/iterator/save). Each plugin typically emits `action_completed` or `action_error` via the same report_event path.
      - After success, worker calls _complete_job(); on error, _fail_job().
    - run_forever(): 889–933 loops: lease → execute → complete/fail; plus metrics and optional heartbeats.

Note: Worker reports events through plugin layer:
- noetl/plugin/report_event → server /event/emit → EventService.emit() (Section 2).


## 6) Event-to-next-queue flow

1. Worker emits `action_completed` (or `result`) → EventService.emit() persists event, then:
   - Notifies BrokerService.on_event_persisted(): broker/service.py 29–124
   - Calls evaluate_broker_for_execution(), which:
     - For non‑loop steps: _advance_non_loop_steps() emits `step_completed` and lets controllers enqueue next step(s).
     - For loop steps: detects `loop_iteration` per item; later, when all items complete, aggregates results and emits a final `action_completed` + `result` + `loop_completed` event for the loop; BrokerService may enqueue `result_aggregation` jobs as needed.
2. queue.complete endpoint also best‑effort emits mapping events for loop child executions back to parent and triggers broker evaluation (queue.py 150–611).


## 7) What to fix (actionable items)

The following issues are observed or likely to cause inconsistencies in the enqueue → work → report → next‑enqueue pipeline. Each item includes suggested changes with code references.

1) Normalize execution_id handling across queue and broker (Implemented)
- Status: Implemented in commit 66f2dda1f596f3ce2b0db9a23c6b8d1dbd6ea582 (2025-10-08). Added queue.normalize_execution_id() delegating to normalize_execution_id_for_db and used it in /queue/enqueue. BrokerService now normalizes via normalize_execution_id_for_db; broker evaluation continues to use snowflake_id_to_int at DB boundaries.
- Impact: Clients may submit execution_id as string; server persists/queries using bigint consistently. Roundtrip enqueue → lease → complete works with string inputs.
- Evidence/References:
  - noetl/api/routers/queue.py: helper 14–31; enqueue 47–93 (uses helper); catalog resolver 33–46.
  - noetl/api/routers/broker/service.py: normalization at 42–48, checks/enqueue use int 78–95.
  - noetl/api/routers/event/processing/broker.py: queue inserts cast via snowflake_id_to_int at 414–419, 424–439, 595–603.
- Follow-ups: Add unit test asserting enqueue → lease → complete roundtrip when execution_id is provided as string (see Section 10 task 1 acceptance criteria).

2) Strengthen dedupe and idempotency around step_started and loop_iteration
- Symptom: Duplicate marker events can produce noisy logs and confusing UI.
- Evidence: EventService.emit() has guards for step_started and loop_iteration (lines 282–317), but other producer paths can still emit duplicates if contexts differ slightly.
- Fix:
  - Consider adding a UNIQUE partial index or server‑side check keying on (execution_id, node_name, event_type [, current_index]) at DB level to guarantee idempotency.
  - Optionally extend dedupe in emit() to include common aliases for node_name and index extraction from context.

3) Ensure parent_event_id propagation for lineage from broker → queue → worker → event
- Symptom: Aggregation and parent/child linkage logic relies on context._meta.parent_event_id; missing propagation breaks mapping from child results back to parent loop iterations.
- Evidence:
  - processing/broker.py sets `_meta.parent_event_id` in ctx when trigger_event_id is provided: 371–375 (non‑loop), 529–536 (loop items).
  - Worker copies parent_event_id into emitted events: worker.py 545–576.
- Fix:
  - Guarantee that when evaluate_broker_for_execution is called from EventService.emit, the provided trigger_event_id (set at 568–569 in service.py) propagates into subsequent enqueue contexts for both non‑loop and loop paths. Verify route_event controllers preserve this.

4) Catalog_id resolution failures block event insertion
- Symptom: EventService.emit() requires a valid `catalog_id` and will raise ValueError if it cannot resolve one (service.py 375–387). This can happen for events produced by clients or workers missing path/version in context/meta.
- Fix:
  - Standardize metadata enrichment on the worker’s start_event to always include playbook `path` and `version` in context.work or top‑level context when missing. See worker.py 560–580 where start_event.context is constructed; ensure it contains path/version (available in job.context from broker enqueue paths 365–370).
  - Add a fallback in emit() to infer catalog_id from the execution’s earliest event if all else fails (one extra SELECT using execution_id).

5) Queue completion should always re‑evaluate both child and parent when loops are in play
- Symptom: Parent workflow sometimes stalls until another event happens.
- Evidence:
  - queue.complete triggers evaluate_broker_for_execution for the job’s execution_id, and conditionally for parent_execution_id (lines 590–608). The conditional path depends on context metadata presence.
- Fix:
  - Ensure that loop/child workflows always include `_meta.parent_execution_id` and `parent_step` in job.context. processing/broker.py already injects trigger metadata, but confirm controllers and iterator paths include `_meta` consistently.
  - As a safety net, after emitting loop aggregate events, explicitly trigger broker on parent as is already attempted (lines 575–583). Consider broadening the guard to trigger parent evaluation whenever a `loop_completed` or `result` with loop metadata is emitted (service.emit() area 733–747).

6) Normalize task payload overlay rules server‑side and worker‑side
- Symptom: Disagreement between transition payload merging and worker input construction can yield unexpected `input` seen by plugins.
- Evidence:
  - Server merges transition payloads with precedence and supports `data` overlay: processing/broker.py 203–301.
  - Worker reconstructs `task_data` combining data/with/payload/input with precedence input > payload > with: worker.py 582–606.
- Fix:
  - Document and align exact precedence. Prefer server authoritative render via /context/render so worker avoids re‑merging, instead using the server‑rendered `task` directly (worker.py already prefers rendered_task). Update plugins to rely on `context.work.input`/`context.work.data` rather than recomputing.

7) Event status normalization and validation
- Symptom: Mixed case and legacy statuses are present.
- Evidence: service.get_all_executions normalizes legacy statuses: 79–99, 119–142. worker._validate_event_status enforces allowed set before sending: 335–348.
- Fix:
  - Keep worker validation. In EventService.emit, replace the fallback to PENDING (191–195) with a clear error when invalid status provided by clients; add a short list of accepted statuses to 400 response in endpoints that proxy emit.

8) DB‑level constraints for queue idempotency
- Add db constraints/indexes to enforce uniqueness on (execution_id, node_id) in queue (already implied by ON CONFLICT in some INSERTs), and optionally on marker events to guarantee dedupe. Align all INSERTs to use the same ON CONFLICT DO NOTHING strategy where appropriate.


## 8) End‑to‑end sequence (example)

1. EventService.emit receives `execution_started` with context containing playbook path/version → persists event and workload; notifies broker.
2. Broker `_handle_initial_dispatch` loads playbook, finds first actionable step `fetch`, emits `step_started`, enqueues queue row:
   - node_id: `<execution_id>:fetch`
   - context: `{ workload: {...}, step_name: 'fetch', path, version }`
3. Worker leases job via POST /queue/lease, renders context via POST /context/render, emits `action_started`, runs plugin, emits `action_completed` with result, POST /queue/{id}/complete.
4. EventService.emit persists `action_completed` and triggers broker, which emits `step_completed` and enqueues next step.
5. For iterator steps, `_handle_loop_step` emits `loop_iteration` per item and enqueues `<execution_id>:loop:<idx>` tasks. After all complete, queue.complete and broker completion handlers emit aggregated `action_completed` + `result` + `loop_completed`, then enqueue downstream transitions.


## 9) References (quick index)

- Event ingestion and triggers: noetl/api/routers/event/service.py: 171–758, 726–749
- Broker evaluation and enqueue: noetl/api/routers/event/processing/broker.py: 81–447, 450–596, 599–740
- Queue API: noetl/api/routers/queue.py: 28–73, 76–132, 135–616, 619–652, 655–679
- Worker: noetl/worker/worker.py: 356–386, 391–796
- Broker service notifier: noetl/api/routers/broker/service.py: 17–124


---

This document should be used to guide fixes to the server enqueue process, worker reporting, and broker re‑evaluation to ensure a robust, idempotent, and well‑linked execution pipeline.


## 10) Issue-ready breakdown (detailed tasks for GitHub)

Below is a curated set of actionable issues you can create in GitHub. Each task includes a clear title, problem statement, proposed solution, acceptance criteria, references to code, labels, and an effort estimate.

1) Normalize execution_id handling across queue and broker
- Title: Normalize execution_id types (string Snowflake → bigint) on all queue paths
- Problem: Inconsistent use of string vs bigint Snowflake IDs causes failed lookups (e.g., catalog_id) and queue inserts.
- Proposed solution:
  - Add a small helper normalize_execution_id(value) that defers to snowflake_id_to_int and use it in all server enqueue points.
  - Audit and fix any remaining queue inserts to pass bigint to SQL parameters.
- Acceptance criteria:
  - All INSERT/UPDATE/SELECT statements touching noetl.queue and noetl.event use bigint execution_id consistently.
  - New unit test: enqueue → lease → complete roundtrip works when client submits execution_id as string.
- References:
  - noetl/api/routers/queue.py: lines 49–54, 55–68
  - noetl/api/routers/event/processing/broker.py: lines 413–419, 427–434, 566–586
- Labels: area:queue, reliability, tech-debt | Effort: M | Priority: High

2) DB-level idempotency for marker events
- Title: Enforce idempotency for step_started and loop_iteration events at DB level
- Problem: Duplicate marker events create noise and complicate UI.
- Proposed solution:
  - Add UNIQUE partial indexes (or constraints) on event table for (execution_id, node_name, event_type) where event_type='step_started'; and (execution_id, node_name, event_type, current_index) where event_type='loop_iteration'.
  - Keep existing app-level dedupe guards.
- Acceptance criteria:
  - Attempts to insert duplicates are rejected by DB, and emit() handles integrity errors gracefully (no crash; returns OK/no-op).
- References:
  - noetl/api/routers/event/service.py: lines 282–317
  - schema migrations folder (add Alembic/SQL DDL)
- Labels: area:event, db, idempotency | Effort: M | Priority: Medium

3) Parent-child lineage propagation
- Title: Guarantee parent_event_id propagation from trigger → queue ctx → worker → events
- Problem: Missing _meta.parent_event_id breaks mapping of child results back to parent loop iterations.
- Proposed solution:
  - Ensure evaluate_broker_for_execution always passes trigger_event_id into ctx['_meta'].parent_event_id for both non-loop and loop paths.
  - Verify all controllers preserve _meta when enqueueing.
  - Add validation in worker to log a warning when parent_event_id is expected but missing for iterator tasks.
- Acceptance criteria:
  - loop_iteration and action_started/completed events contain correct parent_event_id for items originating from a triggering event.
  - Integration test: end-to-end loop with child execution emits mapping events with correct lineage.
- References:
  - noetl/api/routers/event/service.py: 565–571 (sets trigger_event_id)
  - noetl/api/routers/event/processing/broker.py: 371–375, 529–536
  - noetl/worker/worker.py: 545–576
- Labels: area:broker, lineage | Effort: M | Priority: High

4) Catalog_id fallback inference in EventService.emit
- Title: Add fallback to derive catalog_id from earliest execution event
- Problem: emit() hard-requires catalog_id and can fail for client/worker events missing path/version in context/meta.
- Proposed solution:
  - If metadata/context lookup fails, query SELECT catalog_id FROM event WHERE execution_id = %s ORDER BY created_at LIMIT 1 and use it.
  - Emit a warning log indicating fallback used.
- Acceptance criteria:
  - Events with minimal context (but belonging to an existing execution) are accepted and linked to the proper catalog_id.
  - Unit test for fallback path.
- References:
  - noetl/api/routers/event/service.py: 328–387
- Labels: area:event, ux, resiliency | Effort: S | Priority: High

5) Broker reevaluation triggers for loop and result events
- Title: Broaden broker triggers on loop/result lifecycle
- Problem: Parent workflow may stall until an unrelated event occurs.
- Proposed solution:
  - In EventService.emit, include loop_completed and result (with loop metadata) in the fast-path set that triggers evaluate_broker_for_execution.
  - Add parent execution check to also evaluate the parent when appropriate.
- Acceptance criteria:
  - After final iteration mapping or loop_completed, broker advances without manual intervention.
  - Integration test: iterator playbook completes automatically.
- References:
  - noetl/api/routers/event/service.py: 733–749
  - noetl/api/routers/broker/service.py: 29–94
- Labels: area:broker, scheduling | Effort: S | Priority: Medium

6) Align payload overlay rules between server and worker
- Title: Canonicalize payload precedence and avoid double-merge
- Problem: Divergent merging can produce different inputs seen by plugins.
- Proposed solution:
  - Define canonical precedence: transition data overlay (next.data overlays step.data), and for task input: input > payload > with; server computes final task via /context/render.
  - Worker should prefer rendered_task and avoid re-merging unless rendered not present; document this behavior.
  - Update plugins to read from context.work.input (alias: context.work.data) consistently.
- Acceptance criteria:
  - Unit tests verifying server-rendered task equals what worker uses.
  - Documentation updated in docs/runtime.md as needed.
- References:
  - noetl/api/routers/event/processing/broker.py: 203–301
  - noetl/worker/worker.py: 582–606, 441–447
- Labels: area:dsl, consistency | Effort: M | Priority: Medium

7) Strict status validation on server
- Title: Reject invalid event statuses at API boundaries
- Problem: Mixed legacy statuses observed; emit() currently normalizes to PENDING in some places.
- Proposed solution:
  - In EventService.emit, remove fallback to PENDING for invalid inputs coming from clients; raise ValueError → HTTP 400 (already logged).
  - Ensure any endpoint that proxies emit returns 400 with allowed status set listed.
- Acceptance criteria:
  - Invalid statuses produce 400; valid statuses pass untouched.
  - Tests for validation paths.
- References:
  - noetl/api/routers/event/service.py: 189–195
  - noetl/worker/worker.py: 335–348
- Labels: api, validation | Effort: S | Priority: Medium

8) Queue API normalization helper
- Title: Introduce queue.normalize_execution_id() and reuse in endpoints
- Problem: Multiple endpoints convert execution_id inconsistently.
- Proposed solution:
  - Implement a helper in queue router (or shared util) to normalize execution_id.
  - Use it in /queue/enqueue, /queue/list, and any new endpoints.
- Acceptance criteria:
  - Shared helper used across queue endpoints; tests pass.
- References:
  - noetl/api/routers/queue.py: 49–54, 682–707
- Labels: area:queue, refactor | Effort: S | Priority: Medium

9) DB constraints for queue idempotency
- Title: Enforce uniqueness on (execution_id, node_id) in noetl.queue
- Problem: Duplicate queue items can slip in from multiple code paths.
- Proposed solution:
  - Add/confirm UNIQUE(execution_id, node_id) in schema; align all INSERTs to rely on ON CONFLICT DO NOTHING.
- Acceptance criteria:
  - Duplicate inserts are dropped; no errors thrown in app flow.
  - Test: simulate racing enqueue; only one row remains.
- References:
  - noetl/api/routers/event/processing/broker.py: 420–434, 572–587
  - noetl/api/routers/queue.py: 55–68
- Labels: db, idempotency | Effort: S | Priority: High

10) End-to-end tests for enqueue→lease→execute→emit→complete
- Title: Add integration tests for basic step and iterator loop
- Problem: Regressions slip in without broad coverage.
- Proposed solution:
  - Add pytest scenarios that spin up an in-memory/test DB (or dockerized PG), seed a simple playbook, run broker to enqueue, simulate worker lease/complete, and assert expected events and queue states.
- Acceptance criteria:
  - Tests cover: first step dispatch, non-loop progression, iterator per-iteration queueing, aggregation and loop completion.
- References:
  - tests/ (new files), leverage fixtures in tests/fixtures/
- Labels: tests, integration | Effort: L | Priority: High

11) Observability improvements around loop aggregation
- Title: Structured logs and metrics for loop aggregation path
- Problem: Difficult to diagnose aggregation timing and data issues.
- Proposed solution:
  - Add structured log lines around: loop_iteration emit, item queue insert, result mapping emission, final aggregation emission, broker re-evaluation triggers.
  - Optional: basic counters/timers (prometheus or log-derived).
- Acceptance criteria:
  - Logs contain execution_id, step_name, current_index, counts; easy to correlate.
- References:
  - noetl/api/routers/event/processing/broker.py: 492–596, 418–447
  - noetl/api/routers/queue.py: 418–556
  - noetl/api/routers/broker/service.py: 29–94
- Labels: observability, logs | Effort: S | Priority: Medium

12) Documentation updates
- Title: Expand runtime docs on payload precedence and lineage
- Problem: Users need clarity for authoring playbooks and debugging.
- Proposed solution:
  - Update docs/runtime.md and this document to include explicit precedence tables and lineage diagrams.
- Acceptance criteria:
  - New subsections present; cross-links added.
- References:
  - docs/runtime.md
  - docs/communication-algorithm.md
- Labels: docs | Effort: S | Priority: Low

Notes on rollout and risk:
- Most changes are backward-compatible; DB constraint additions require short migrations and may reject rare duplicates—schedule during a maintenance window.
- Ensure workers and server are upgraded together for lineage and payload precedence alignment.

