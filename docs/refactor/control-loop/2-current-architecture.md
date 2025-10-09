# Current Architecture (As-Is)

This document inventories all modules and data flows involved in the playbook execution control loop, with direct code references to the current implementation.

Primary modules:
- Event persistence and triggers: noetl/api/routers/event/service.py
  - emit(): persists events, resolves catalog_id, dedupes markers, triggers broker.
  - get_events*, get_event*: retrieval helpers.
- Broker orchestration: noetl/api/routers/event/processing/broker.py
  - evaluate_broker_for_execution(): core evaluator.
  - _handle_initial_dispatch(): finds first actionable step, emits step_started, enqueues.
  - _handle_loop_step(): expands iterator steps, emits loop_iteration, enqueues per item.
  - _advance_non_loop_steps(): emits step_completed and allows next-step scheduling.
- Broker service notifier: noetl/api/routers/broker/service.py
  - on_event_persisted(): enqueues result_aggregation job on loop_completed and schedules analysis.
- Queue API: noetl/api/routers/queue.py
  - enqueue, lease, complete, fail, heartbeat, list, size; normalization helper for execution_id.
- Worker runtime: noetl/worker/worker.py
  - Lease → render (server) → execute plugin → report events → complete/fail.

Key data tables:
- noetl.event: append-only event log (with JSON columns context/result/meta).
- noetl.queue: work items for workers (status queued/leased/done/dead).
- noetl.workload: execution-scoped snapshot of initial context/workload.
- Snapshot tables to update during lifecycle: transition, workbook, workload, workflow.

Lifecycle (high level):
1) execution_started → EventService.emit() stores workload and event → triggers broker.
2) Broker loads playbook (catalog), determines first actionable step → emits step_started → inserts queue row.
3) Worker leases job, emits action_started, executes plugin, emits action_completed (or error), completes job.
4) EventService.emit() triggers broker again, which may advance to next step(s). Iterator steps emit loop_iteration per item, and once all done, aggregate results and continue.

Known issues (summarized):
- Mixed execution_id types in queue/event paths (partly fixed recently).
- Catalog_id resolution failures when context/meta incomplete.
- Parent/child lineage propagation gaps (parent_event_id).
- Idempotency/dedupe for markers; DB constraints not fully enforced.
- Divergent payload overlay rules between server and worker.

See docs/system_control_loop_communication_protocol.md for an in-depth narrative and references already compiled. This refactor plan builds upon those findings.
