# NoETL Architecture Overview

This document explains how the NoETL server and worker instances collaborate to execute playbooks, and describes the end-to-end chain of processing for playbooks in the noetl package. It also highlights the main code locations that implement each responsibility so you can navigate the repository effectively.

- Server implementation: noetl/server.py and noetl/server/api/*
- Orchestration engine (server-side progression and local broker): noetl/server/api/event and noetl/server/api/broker
- Worker implementation: noetl/worker.py
- Task/action executors: noetl/job/*
- Rendering and templating: noetl/render.py
- Shared utilities and configuration: noetl/common.py, noetl/config.py, noetl/logger.py


## High-level Components

- API Server (FastAPI): Hosts REST APIs for catalog, events, queue, context rendering, and health. The server records runtime status in the database and coordinates playbook execution by evaluating steps and enqueuing work for distributed workers.
  - File: noetl/server.py
  - Routers: noetl/server/api/__init__.py aggregates individual routers such as queue, event, catalog, runtime/system, etc.
- Catalog: Stores playbooks (content, metadata, versions) in the database and provides retrieval endpoints.
  - File: noetl/server/api/catalog.py (CatalogService)
- Event Log: Persists execution events (start, step start/complete, action started/completed, errors). Used by the server to reconstruct state and decide next steps.
  - Module: noetl/server/api/event (EventService and persistence logic); see event_log table usage in SQL queries.
- Queue: A lightweight job queue implemented via a Postgres table (noetl.queue) and REST endpoints. Workers lease jobs from this queue.
  - File: noetl/server/api/queue.py
- Worker: A polling worker that leases jobs, executes the described task/action, and reports results back to the server.
  - File: noetl/worker.py
- Broker Engine:
  - Server-side broker evaluator: Decides which steps are actionable next and enqueues them.
    - Module: noetl/server/api/event/processing.py (evaluate_broker_for_execution)
  - Local broker runner: Enables local/on-demand playbook execution and implements step execution primitives (loops, pass/skip, transitions).
    - Module: noetl/server/api/broker (class Broker in core.py)
- Action/Task Executors: Implement concrete action types (http, python, duckdb, postgres, secrets).
  - Files: noetl/job/__init__.py (dispatcher), and noetl/job/http.py, python.py, duckdb.py, postgres.py, secrets.py


## Lifecycle: Server and Worker Collaboration

The following sequence describes typical execution when running with the server and distributed workers.

1) Playbook Registration (optional but typical)
- A YAML playbook is registered into the catalog with path and version.
- API: POST via Catalog endpoints; code: CatalogService.register_resource in noetl/server/api/catalog.py.

2) Playbook Execution is Initiated
- A client (CLI/UI) triggers an execution for a playbook path/version.
- The server creates initial events (including execution_start) with the provided input context (workload/payload) and metadata (playbook path/version).

3) Server Builds Context and Decides Next Step(s)
- The server-side broker evaluator reconstructs the execution state from event_log and playbook content, then determines the next actionable step(s):
  - Code: noetl/server/api/event/processing.py → evaluate_broker_for_execution
  - It reads the first event to extract playbook_path, version, and initial payload/workload.
  - It parses the YAML content from the catalog and identifies steps/workbook definitions.
  - It applies server-side rendering (via noetl/render.py) for conditions (when/pass), step parameters, and decides which step(s) should run next.
  - For steps that are skipped due to conditions (pass/when false), it emits step_skip/complete events without creating jobs.

4) Server Enqueues Jobs for Workers
- For each actionable step that requires a task/action execution, the server enqueues a job in noetl.queue with fields:
  - execution_id, node_id, action (task definition), input_context (the server-rendered context for that node).
- API: POST /api/queue/enqueue; code: noetl/server/api/queue.py → enqueue_job

5) Workers Poll for Jobs and Execute Actions
- Workers register their pool info (best-effort) and continuously poll the server to lease jobs:
  - Lease: POST /api/queue/lease with worker_id
  - Complete: POST /api/queue/{id}/complete
  - Fail: POST /api/queue/{id}/fail
  - Code: noetl/worker.py → QueueWorker._lease_job/_complete_job/_fail_job
- For each leased job, the worker:
  - Calls the server to render the context and task config deterministically: POST /api/context/render
    - Code: noetl/server/api/event/context.py → render_context
  - Executes the task locally using the action dispatch in noetl/job/__init__.py → execute_task
  - Emits action_started, action_completed (or action_error) events back to the server: noetl/job/action.py:report_event (invoked by worker); stored in event_log via event API.
  - Marks the job complete or failed via queue endpoints.

6) Server Reacts to Completion and Advances the Workflow
- On job completion, the queue API best-effort schedules evaluate_broker_for_execution(execution_id) to compute the next step(s) based on accumulated results in event_log.
  - Code: noetl/server/api/queue.py → complete_job triggers evaluate_broker_for_execution
- The cycle (3–6) repeats until there are no more actionable steps, at which point the workflow reaches end.


## Database Entities (Conceptual)

- catalog: Stores resources (playbooks) with content and versions.
- event_log: Stores all execution events with input contexts and output results for every node/step/action.
- queue: Stores queued/leased/failed/done jobs for workers. Fields include execution_id, node_id, action (task spec), input_context, status, attempts, worker_id, lease_until, etc.
- runtime: Tracks server_api and worker_pool registrations/heartbeats (from server.py lifespan, worker registration utilities in worker.py).


## Where Conditions and Templating Happen

- Server-side templating: For deterministic orchestration, the server renders conditions and many step parameters using Jinja (noetl/render.py). Workers also fetch a server-rendered view of the input_context and task config (POST /api/context/render) to minimize divergence.
- Pass flag and when expressions: Evaluated by the broker/evaluator to decide whether to skip steps or which branches to follow.
  - Local broker path: noetl/server/api/broker → execute_step, get_next_steps
  - Server-side evaluator path: noetl/server/api/event/processing.py → evaluate_broker_for_execution


## Broker: Local Step Orchestration Primitives

When running locally (without server/queue), the Broker implements the same step semantics:
- execute_step(step_name, with): Finds the step, evaluates pass, logs events, executes the step or skips it, updates context, and decides the next step(s).
- Looping:
  - execute_loop_step: Expands a collection into iterations, emitting loop_start/loop_iteration events and running nested steps per item.
  - end_loop_step: Aggregates loop results into context (e.g., <loop_name>_results) and applies the result mapping to compute aggregated values.
- get_next_steps: Applies when conditions to choose the next steps; supports then/else lists and with overrides.
- run(): Drives execution from start to end using the agent interface (find_step, save_step_result, update_context, etc.).

Files: noetl/server/api/broker (core methods: execute_step, execute_loop_step, end_loop_step, get_next_steps, run)


## Worker: Action Execution

QueueWorker in noetl/worker.py is responsible for turning a job (node action) into actual work:
- Renders input context via server API /api/context/render to ensure consistent evaluation.
- Executes the action using the dispatcher execute_task (noetl/job/__init__.py).
- Emits action_started, action_completed/e rror to event_log via server.
- Ensures any loop metadata (if present) is propagated in events for observability.


## Sequence Narrative (Server + Worker)

Textual sequence for one actionable step:

1) Client triggers execution → server writes execution_start event.
2) Server evaluate_broker_for_execution builds context and picks next actionable step → POST /api/queue/enqueue.
3) Worker polls /api/queue/lease, receives job with action + input_context.
4) Worker POST /api/context/render to resolve templates.
5) Worker executes the resolved task via noetl/job/*.
6) Worker emits action_completed/action_error event.
7) Worker marks job complete/fail on /api/queue/{id}/complete|fail.
8) Server evaluates broker again to advance to the next step(s).
9) Repeat until end.


## Entry Points and Configuration

- Server start: CLI starts FastAPI app from noetl/server.py:create_app().
  - On startup/shutdown (lifespan), server registers/deregisters itself into runtime.
  - CORS and UI static assets are mounted.
- Workers: Run QueueWorker or ScalableQueueWorkerPool (noetl/worker.py). Workers register their pool (best-effort) and poll the server.
- Environment variables: See docs/environment_variables.md. Key ones include NOETL_SERVER_URL, NOETL_WORKER_POOL_NAME/RUNTIME, etc.


## Relating to the Code

- Server runtime registration: noetl/server.py → register_server_directly (lifespan)
- Broker evaluator (server-side): noetl/server/api/event/processing.py → evaluate_broker_for_execution
- Queue endpoints: noetl/server/api/queue.py (enqueue, lease, complete, fail)
- Worker leasing and execution: noetl/worker.py (QueueWorker and ScalableQueueWorkerPool)
- Local broker execution (for agent-style runs): noetl/server/api/broker
- Templating: noetl/render.py (render_template), API /api/context/render in noetl/server/api/event/context.py
- Task dispatch: noetl/job/__init__.py → execute_task, calling concrete executors under noetl/job/


## Notes on Reliability and Scaling

- Queue locking: /queue/lease uses SELECT ... FOR UPDATE SKIP LOCKED to avoid contention.
- Heartbeats and lease_until: Workers can extend or fail jobs; server can reap expired leases.
- Idempotency: Steps and actions should be designed to be idempotent where possible; server uses event_log as source of truth for progression.
- Horizontal scaling: Add more worker instances or use ScalableQueueWorkerPool to scale processes/threads. The server remains stateless aside from DB.


## See Also

- docs/execution_model.md for the conceptual process model
- docs/playbook_structure.md for the DSL structure
