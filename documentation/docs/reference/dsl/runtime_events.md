---
sidebar_position: 3
title: Runtime Event Model (Canonical v10)
description: Canonical event taxonomy and event envelope specification for NoETL execution (aligned with noetl_canonical_step_spec_v10)
---

# NoETL Runtime Event Model — Canonical v10

This document defines the **canonical event taxonomy** used by NoETL at runtime and stored in the **append-only event log**.

It is aligned to **NoETL Canonical Step Spec (v10)**:
- **No `case` entity/events**
- **No special `retry` entity/events** (retry is represented as multiple task attempts + policy decisions)
- **No `sink` entity/events** (storage is just tool tasks returning references)
- **Tools are executed as pipeline `tasks`** (task labels), each producing a single final `outcome`
- Routing is server-side via **Petri-net arcs**: `step.next.spec` + `step.next.arcs[]`

> Related docs: `noetl_canonical_step_spec_v10.md`, `spec_v3.md` (DSL canonical), `result_storage_canonical_v10.md` (reference-first results).

---

## 1) Event naming conventions (canonical)

### 1.1 Canonical name rules
Canonical event types MUST:
- be **lowercase**
- use **dot-separated** segments
- follow the pattern: `<entity>.<subentity?>.<verb>`

Recommended verbs:
- `requested`, `evaluated`, `scheduled`, `started`, `done`, `failed`, `finished`, `paused`, `processed`

**Guidance**
- Prefer `*.done` / `*.failed` for boundary outcomes (step/task/iteration).
- Prefer `*.finished` for higher-level closures (workflow/playbook).
- Use `*.evaluated` for decisions (admission, routing).

### 1.2 Display alias (optional)
Implementations MAY attach `event_alias` for UI/CLI:
- `event_type`: canonical dot name (required)
- `event_alias`: PascalCase alias (optional)

---

## 2) Event envelope (normative)

Every stored event MUST include:
- `event_id` (string; unique)
- `event_type` (string; canonical dot name)
- `timestamp` (RFC3339 UTC)
- `execution_id` (string)

And SHOULD include:
- `source` (`server` | `worker`)
- `entity_type` (`playbook` | `workflow` | `step` | `task` | `loop` | `next` | `policy` | `result`)
- `entity_id` (string; e.g. step name, task label, loop id)
- `parent_id` (string?; nesting: workflow → step → task)
- `seq` (int; monotonic per execution, if available)

Optional correlation (highly recommended):
- `workflow_run_id`, `step_run_id`, `task_run_id`
- `iteration` (int; loop index)
- `iteration_id` (string; stable)
- `attempt` (int; task attempt index; starts at 1)
- `status` (`in_progress` | `success` | `error` | `skipped` | `paused`)
- `duration_ms` (int)

Payload fields (recommended):
- `payload.inputs` (rendered input snapshot; size-capped)
- `payload.outcome` (canonical outcome envelope; size-capped)
- `payload.result_ref` (ResultRef; preferred for large payloads)
- `payload.error` (structured error)
- `payload.meta` (free-form metadata)

**Idempotency**
- Event persistence MUST be idempotent by `(execution_id, event_id)`.

**Reference-first**
- Large outputs MUST be externalized; events SHOULD store only **references + extracted fields**.

---

## 3) Canonical taxonomy (dot name ↔ PascalCase alias)

### 3.1 Playbook lifecycle (server)
| Canonical `event_type` | Alias (display) |
|---|---|
| `playbook.execution.requested` | `PlaybookExecutionRequested` |
| `playbook.request.evaluated` | `PlaybookRequestEvaluated` |
| `playbook.started` | `PlaybookStarted` |
| `playbook.paused` | `PlaybookPaused` |
| `playbook.finished` | `PlaybookFinished` |
| `playbook.processed` | `PlaybookProcessed` |

### 3.2 Workflow lifecycle (server)
| Canonical `event_type` | Alias (display) |
|---|---|
| `workflow.started` | `WorkflowStarted` |
| `workflow.finished` | `WorkflowFinished` |

### 3.3 Step lifecycle (worker + server scheduling)
| Canonical `event_type` | Alias (display) |
|---|---|
| `step.scheduled` | `StepScheduled` |
| `step.started` | `StepStarted` |
| `step.done` | `StepDone` |
| `step.failed` | `StepFailed` |

> Notes:
> - `step.scheduled` is emitted by the server when a step token is committed for execution.
> - `step.started/done/failed` are emitted by the worker and ingested by the server.

### 3.4 Task lifecycle (worker)
| Canonical `event_type` | Alias (display) |
|---|---|
| `task.started` | `TaskStarted` |
| `task.attempt.started` | `TaskAttemptStarted` |
| `task.attempt.done` | `TaskAttemptDone` |
| `task.attempt.failed` | `TaskAttemptFailed` |
| `task.done` | `TaskDone` |
| `task.failed` | `TaskFailed` |

> Notes:
> - Retries are represented by multiple `task.attempt.*` events for the same `task_run_id`.
> - The final outcome is `task.done` or `task.failed`.

### 3.5 Loop lifecycle (server + worker)
| Canonical `event_type` | Alias (display) |
|---|---|
| `loop.started` | `LoopStarted` |
| `loop.iteration.scheduled` | `LoopIterationScheduled` |
| `loop.iteration.started` | `LoopIterationStarted` |
| `loop.iteration.done` | `LoopIterationDone` |
| `loop.iteration.failed` | `LoopIterationFailed` |
| `loop.done` | `LoopDone` |

### 3.6 Policies and decisions (server + worker)
| Canonical `event_type` | Alias (display) | Emitted by |
|---|---|---|
| `policy.admit.evaluated` | `PolicyAdmitEvaluated` | server |
| `policy.task.evaluated` | `PolicyTaskEvaluated` | worker |
| `next.evaluated` | `NextEvaluated` | server |

> Notes:
> - `policy.admit.evaluated` corresponds to `step.spec.policy.admit.rules` evaluation.
> - `policy.task.evaluated` records which rule matched in `task.spec.policy.rules` and what action was taken (`retry/jump/continue/break/fail`).
> - `next.evaluated` records which arcs matched and which were fired.

### 3.7 Result externalization (optional but recommended)
| Canonical `event_type` | Alias (display) |
|---|---|
| `result.stored` | `ResultStored` |
| `result.manifest.updated` | `ResultManifestUpdated` |

> Notes:
> - These are emitted when the worker (or server) externalizes a payload and produces a ResultRef/ManifestRef.
> - If you don’t want extra events, you MAY embed ResultRef in `task.attempt.*` and omit these.

---

## 4) Legacy compatibility (non-canonical)

If older executors emit legacy events, the server SHOULD normalize to canonical equivalents.

| Legacy | Canonical |
|---|---|
| `tool.started` | `task.started` |
| `tool.processed` | `task.done` / `task.failed` |
| `retry.started` | `task.attempt.started` |
| `retry.processed` | `task.attempt.done` / `task.attempt.failed` |
| `sink.*` | `task.*` (storage task) |
| `case.*` | `next.evaluated` + `policy.*` (depending on purpose) |

Canonical v10 validators SHOULD reject new emissions of legacy types from first-party components.

---

## 5) Control plane vs data plane emission (normative intent)

### 5.1 Server (control plane) MUST emit / persist
- `playbook.execution.requested`
- `playbook.request.evaluated`
- `playbook.started`
- `workflow.started`
- `policy.admit.evaluated` (per step admission evaluation)
- `step.scheduled` (when server commits a step token)
- `next.evaluated` (server-authoritative routing via arcs)
- `workflow.finished`
- `playbook.paused` (if applicable)
- `playbook.finished` / `playbook.processed`

### 5.2 Worker pool (data plane) MUST emit (reported to server ingestion)
- `step.started`
- `task.started`
- `task.attempt.*` (if retries occur)
- `policy.task.evaluated` (recommended for observability/replay)
- `task.done` / `task.failed`
- `step.done` / `step.failed`
- loop iteration events when the worker executes iteration bodies (`loop.iteration.*`)

**Hard rule**
- Workers MUST NOT start steps. Step creation is server-only via `next.arcs` routing.

---

## 6) Topics and indexing (recommended)

### 6.1 Storage indexes (event store)
Recommended indexes:
- `(execution_id, seq)`
- `(execution_id, event_type)`
- `(execution_id, entity_type, entity_id)`
- `(event_type, timestamp)`

### 6.2 Optional pub/sub topics
If also published to a broker:
- Subject/topic = `noetl.events.<event_type>` (e.g., `noetl.events.task.attempt.failed`)
- Include `execution_id` in headers for fast filtering
- Prefer reference-only payloads (ResultRef, ManifestRef).

---

## 7) Example events (canonical v10)

### 7.1 Task attempt failed → policy retries
```json
{
  "event_id": "01JH...",
  "event_type": "task.attempt.failed",
  "event_alias": "TaskAttemptFailed",
  "timestamp": "2026-02-05T23:11:22Z",
  "execution_id": "exec_01JH...",
  "source": "worker",
  "entity_type": "task",
  "entity_id": "fetch_page",
  "parent_id": "step:fetch_all_endpoints:run:7",
  "task_run_id": "task:fetch_page:run:1",
  "attempt": 2,
  "status": "error",
  "payload": {
    "outcome": {
      "status": "error",
      "error": {"kind": "http", "retryable": true},
      "meta": {"duration_ms": 312, "http_status": 503}
    }
  }
}
```

### 7.2 Policy evaluated → action retry
```json
{
  "event_id": "01JH...",
  "event_type": "policy.task.evaluated",
  "event_alias": "PolicyTaskEvaluated",
  "timestamp": "2026-02-05T23:11:23Z",
  "execution_id": "exec_01JH...",
  "source": "worker",
  "entity_type": "policy",
  "entity_id": "task:fetch_page",
  "parent_id": "task:fetch_page:run:1",
  "status": "success",
  "payload": {
    "matched_rule_index": 0,
    "action": {"do": "retry", "attempts": 10, "backoff": "exponential", "delay": 2.0}
  }
}
```

### 7.3 Result stored (reference-first)
```json
{
  "event_id": "01JH...",
  "event_type": "result.stored",
  "event_alias": "ResultStored",
  "timestamp": "2026-02-05T23:11:30Z",
  "execution_id": "exec_01JH...",
  "source": "worker",
  "entity_type": "result",
  "entity_id": "task:fetch_page:attempt:3",
  "parent_id": "task:fetch_page:run:1",
  "status": "success",
  "payload": {
    "result_ref": {
      "kind": "result_ref",
      "store": "nats_object",
      "ref": "noetl://execution/..../page_001.json.gz",
      "meta": {"bytes": 52480, "sha256": "..."}
    },
    "extracted": {"has_more": true, "page": 1}
  }
}
```

### 7.4 Next evaluated (Petri-net arcs)
```json
{
  "event_id": "01JH...",
  "event_type": "next.evaluated",
  "event_alias": "NextEvaluated",
  "timestamp": "2026-02-05T23:12:10Z",
  "execution_id": "exec_01JH...",
  "source": "server",
  "entity_type": "next",
  "entity_id": "step:fetch_all_endpoints",
  "parent_id": "step:fetch_all_endpoints:run:7",
  "status": "success",
  "payload": {
    "mode": "exclusive",
    "matched": [
      {"step": "validate_results", "when": "event.name == 'loop.done'"}
    ],
    "selected": [
      {"step": "validate_results", "args": {"execution_id": "exec_01JH..."}}
    ]
  }
}
```

---

## 8) Quantum orchestration note (informative)

The taxonomy is compatible with asynchronous quantum job lifecycles:
- submission tool → `task.done` contains `job_ref` (ResultRef or small id)
- polling implemented as task policy retries/jumps → `task.attempt.*` + `policy.task.evaluated`
- parameter sweeps implemented as loops → `loop.iteration.*`
- results persistence is just storage tasks producing ResultRef → `result.stored` (optional)

This yields a reproducible experiment trace keyed by `execution_id` without embedding large payloads in the event log.
