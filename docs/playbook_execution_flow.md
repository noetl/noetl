# Playbook Execution Flow

This note captures how a playbook execution travels through the NoETL
stack, which modules participate, and how queue/event tables are used.
Examples reference the most recent run recorded in the local logs.

---

## 1. HTTP Entry Point

- **Endpoint:** `noetl/server/api/run/endpoint.py:execute_resource`
- **Route:** `POST /api/run/{resource_type}` (playbooks use `resource_type=playbook`)
- **Key behavior:**
  - Logs the inbound request and requestor metadata.
  - Delegates execution to `ExecutionService.execute(...)`.

> _Example:_ `logs/server.log:5237` shows the request payload for catalog
> `487178748735782943`.  

---

## 2. Execution Service Pipeline

**Module:** `noetl/server/api/run/service.py`  
**Function:** `ExecutionService.execute(...)`

1. **Catalog lookup** – `CatalogService.get(...)` resolves the playbook
   (path/version or catalog ID).
2. **ID allocation** – `get_snowflake_id()` reserves an `execution_id`
   from the database (`logs/server.log:5243`).
3. **Validation** – `PlaybookValidator.validate_and_parse(...)` ensures
   the YAML is well-formed; workload defaults are extracted.
4. **Planning** – `ExecutionPlanner.build_plan(...)` (see
   `planner.py`) produces:
   - workflow steps persisted to `noetl.workflow`
   - workbook tasks persisted to `noetl.workbook`
   - transitions persisted to `noetl.transition`
   - initial steps (usually `['start']`)
   _(See `logs/server.log:5245-5259`.)_
5. **Workload persistence** – `_persist_workload(...)` inserts the merged
   workload into `noetl.workload`.
6. **Event emission** – `ExecutionEventEmitter`:
   - `emit_execution_start(...)` → `noetl.event` row, event
     `execution_started` (`event_id=487179034200113212`).
   - `persist_workflow(...)`, `persist_workbook(...)`,
     `persist_transitions(...)`.
   - `emit_workflow_initialized(...)` → `noetl.event` row
     (`event_id=487179034401439805`).
7. **Initial queueing** – `QueuePublisher.publish_initial_steps(...)`
   inserts actionable steps into `noetl.queue` via
   `QueueService.enqueue_job(...)`.  
   - For the sample run, `queue_id=487179034443382846` enqueued step
     `start` with priority 100 (`logs/server.log:5264`).
8. **Response** – `ExecutionResponse` is returned to the caller with the
   `execution_id`, event linkage, and published queue IDs.

---

## 3. Queue Table Usage

- **Insertions:** All queue entries go through
  `noetl/server/api/queue/service.py:QueueService.enqueue_job`.
  - Ensures `execution_id`/`catalog_id` are normalized.
  - Serializes `action` (step config) and `context`.
  - Stores `meta` with `parent_event_id` to correlate later events.
- **Initial rows (sample run):**

  | Created At (UTC) | Queue ID | Node | Parent Event |
  | ---------------- | -------- | ---- | ------------ |
  | `04:17:46.581911` | `487179034443382846` | start | `487179034401439805` |
  | `04:17:47.686569` | `487179043712794690` | test_special_characters | `487179043687628865` |
  | `04:17:47.831963` | `487179044937531464` | test_empty_data | `487179044920754247` |
  | `04:17:47.934056` | `487179045793169486` | test_large_payload | `487179045776392269` |
  | `04:17:48.035317` | `487179046640418900` | test_error_recovery | `487179046623641683` |
  | `04:17:49.577412` | `487179059575652442` | test_completion_summary | `487179059550486617` |

  _(Derived from `logs/queue.json`.)_

---

## 4. Worker Lifecycle

**Process:** `noetl/worker/worker.py`

1. **Lease job** – Worker polls `QueueService.lease_job(...)` (logs not
   shown, but executed from the worker loop).
2. **Context rendering** – `_execute_job_sync` calls
   `POST /context/render` so templates are rendered server-side before
   task execution.
3. **Task execution:**
   - `type=python` → `noetl/plugin/python/executor.py:execute_python_task`.
   - `save.storage.type=postgres` → `noetl/plugin/postgres/execution.py`.
   - `save.storage.type=duckdb` → DuckDB plugin, etc.
4. **Save handlers** – `noetl/plugin/save/executor.py` dispatches to the
   proper storage backend after the primary task returns.
5. **Event reporting** – `noetl/plugin/tool/reporting.report_event`
   posts to `POST /api/events`, using
   `noetl/server/api/broker/endpoint.emit_event` +
   `EventService.emit_event`.
6. **Completion** – `_complete_job` marks the queue row `done`, emits
   `action_completed` / `step_result` events, and triggers
   `evaluate_execution`.

> _Observation:_ During the sample run the Postgres plugin hit missing
> tables (`logs/worker.log:382-414`, `603-613`). Error reporting tried to
> insert into `noetl.event` but failed because `catalog_id` was `NULL`,
> leaving only success events. This is worth tracking separately.

---

## 5. Event Table Usage

- **Insertion APIs:**
  - Execution bootstrap uses `ExecutionEventEmitter` (server-side).
  - Workers use `/api/events` → `EventService.emit_event`.
  - Orchestrator also emits synthetic events (`step_completed`,
    `workflow_completed`, etc.).
- **Key fields:**
  - `event_type` (e.g., `action_started`, `action_completed`,
    `step_result`, `step_completed`).
  - `parent_event_id` and `meta.queue_meta.parent_event_id` tie back to
    the queue record / workflow tree.
  - `context` carries task payloads and rendered inputs for condition
    evaluation.

**Sample timeline** (`logs/event.json`, filtered for
`execution_id=487179034023952443`):

| Timestamp (UTC) | Event Type | Node | Event ID | Parent |
| --------------- | ---------- | ---- | -------- | ------ |
| `04:17:46.553` | `execution_started` | playbook | `487179034200113212` | — |
| `04:17:46.576` | `workflow_initialized` | workflow | `487179034401439805` | `487179034200113212` |
| `04:17:47.585` | `action_started` | start | `487179042848768063` | `487179034401439805` |
| `04:17:47.669` | `action_completed` | start | `487179043570188352` | `487179042848768063` |
| `04:17:47.682` | `step_completed` | start | `487179043687628865` | `487179034401439805` |
| ... | ... | ... | ... | ... |
| `04:17:49.775` | `workflow_completed` | workflow | `487179061244985441` | `487179034401439805` |
| `04:17:49.775` | `execution_completed` | playbook | `487179061253374050` | `487179061244985441` |

The full sequence covers each workflow step (`test_special_characters`,
`test_empty_data`, `test_large_payload`, `test_error_recovery`,
`test_completion_summary`, `end`) and mirrors the queue records.

---

## 6. Orchestrator Feedback Loop

- **Entry point:** `noetl/server/api/run/orchestrator.py:evaluate_execution`
  (imported as `evaluate_execution`).
- **Triggers:** Each call to `/api/events` invokes `evaluate_execution`
  with the corresponding `execution_id`, `event_type`, and `event_id`.
- **State reconstruction:** `_get_execution_state(...)` inspects
  `noetl.event` to decide whether the execution is `initial`,
  `in_progress`, or `completed`.
- **Transition processing:** `_process_transitions(...)`:
  - Identifies completed steps lacking a `step_completed` event via
    `OrchestratorQueries.get_completed_steps_without_step_completed`.
  - Loads the playbook from catalog to fetch workflow definitions.
  - Evaluates transition conditions (Jinja expressions) using prior
    results.
  - Emits a `step_completed` event (server-side call to
    `EventService.emit_event`).
  - Calls `QueuePublisher.publish_step(...)` for actionable next steps.
- **Completion checks:** `_check_execution_completion(...)` emits
  `workflow_completed` and `execution_completed` when all actionable
  steps are done.

> _Example:_ `logs/server.log:22833-22872` shows `action_completed`
> for `test_completion_summary` triggering orchestrator processing which
> emits `step_completed` and ultimately the completion events.

---

## 7. End-to-End Flow (Sample Run Summary)

1. **HTTP call** – `POST /api/run/playbook` (server log lines
   `5230-5284`).
2. **Execution bootstrap** – Workload persisted, events emitted, queue
   seeded (`logs/server.log:5240-5265`).
3. **Worker execution** – Worker fetches queue tasks, renders context,
   runs Python + storage plugins (`logs/worker.log:360-620` for the first
   two steps). Errors surfaced in logs but not recorded due to the
   catalog ID constraint.
4. **Event reporting** – Each task posted `action_started`,
   `action_completed`, and `step_result` events (visible in
   `logs/event.json` and `logs/server.log:22820+`).
5. **Orchestrator loop** – On each completion the orchestrator
   reevaluated transitions and queued the next step (`logs/server.log:22831-22872`).
6. **Completion** – Final queue item `test_completion_summary` completed;
   orchestrator emitted `workflow_completed` and `execution_completed`
   events (`logs/event.json` final rows).

Despite the Postgres insert errors in the worker log, the system marked
the steps successful because the error reporting insert failed; this is
visible at `logs/worker.log:412-416`.

---

## 8. Key Modules at a Glance

| Concern | Module / Function |
| ------- | ----------------- |
| REST entrypoint | `noetl/server/api/run/endpoint.py:execute_resource` |
| Core execution | `noetl/server/api/run/service.py:ExecutionService.execute` |
| Planning | `noetl/server/api/run/planner.py:ExecutionPlanner.build_plan` |
| Event persistence | `noetl/server/api/run/events.py:ExecutionEventEmitter` |
| Queue publishing | `noetl/server/api/run/publisher.py:QueuePublisher` |
| Queue service | `noetl/server/api/queue/service.py:QueueService.enqueue_job` |
| Worker engine | `noetl/worker/worker.py:Worker._execute_job_sync` |
| Worker event reporting | `noetl/plugin/tool/reporting.report_event` |
| Event API | `noetl/server/api/broker/endpoint.py:emit_event` |
| Orchestrator | `noetl/server/api/run/orchestrator.py:evaluate_execution` |
| DB queries | `noetl/server/api/run/queries.py:OrchestratorQueries` |

---

### Notes for Future Improvements

- Ensure error events supply a `catalog_id` before inserting into
  `noetl.event` to avoid silent drops (`logs/worker.log:412-416`).
- Consider surfacing worker log errors back through orchestration so
  failed steps do not appear successful.

