---
sidebar_position: 3
title: Runtime Event Model
description: Canonical event taxonomy and event envelope specification for NoETL execution
---

# NoETL Runtime Event Model

This document defines the **canonical event taxonomy** used by NoETL at runtime and stored in the **append-only event log**.

- The **dot-separated** name is the **canonical machine key** (indexes, topics, filters).
- The **PascalCase** name is a **display alias** (UI/CLI).

> Related docs: `docs/spec.md` (normative DSL semantics), `docs/whitepaper.md` (architecture / rationale).

---

## 1. Event naming conventions (canonical)

### 1.1 Canonical name rules

Canonical event types MUST:
- be **lowercase**
- use **dot-separated** segments
- follow the pattern: `<entity>.<subentity?>.<verb>`

Recommended verbs:
- `requested`, `evaluated`, `started`, `finished`, `processed`, `paused`

**Guidance:**
- Use `*.finished` for end-of-scope lifecycle closures (workflow/loop).
- Use `*.processed` for “completed with outcome” entities (tool/sink/retry/playbook).

### 1.2 Display alias

Implementations MAY attach `event_alias` for UI:
- `event_type`: canonical dot name (required)
- `event_alias`: PascalCase name (optional)

---

## 2. Event envelope (normative)

Every stored event MUST include:

- `event_id` (string; unique)
- `event_type` (string; canonical dot name)
- `timestamp` (RFC3339 UTC)
- `execution_id` (string)

And SHOULD include:

- `entity_type` (playbook|workflow|step|tool|loop|retry|sink|case|next)
- `entity_id` (string; e.g., step name, tool name, loop id)
- `parent_id` (string?; links nesting: workflow → step → tool)
- `seq` (int; monotonic per execution, if available)

Optional correlation:

- `workflow_run_id`, `step_run_id`, `tool_run_id`
- `iteration` (int; loop index)
- `iteration_id` (string)
- `attempt` (int; retry attempt index)
- `status` (in_progress|success|error|skipped|paused)
- `duration_ms` (int)

Payload:

- `payload.inputs` (rendered input snapshot)
- `payload.output` (result snapshot)
- `payload.error` (structured error)
- `payload.meta` (free-form metadata)

> Idempotency: event persistence MUST be idempotent by `(execution_id, event_id)`.

---

## 3. Canonical taxonomy (dot name ↔ PascalCase alias)

### 3.1 Playbook lifecycle

| Canonical `event_type` | Alias (display) |
|---|---|
| `playbook.execution.requested` | `PlaybookExecutionRequested` |
| `playbook.request.evaluated` | `PlaybookRequestEvaluated` |
| `playbook.started` | `PlaybookStarted` *(recommended)* |
| `playbook.paused` | `PlaybookPaused` |
| `playbook.processed` | `PlaybookProcessed` |

### 3.2 Workflow lifecycle

| Canonical `event_type` | Alias (display) |
|---|---|
| `workflow.started` | `WorkflowStarted` |
| `workflow.finished` | `WorkflowFinished` |

### 3.3 Step lifecycle

| Canonical `event_type` | Alias (display) |
|---|---|
| `step.started` | `StepStarted` |
| `step.finished` | `StepFinished` *(recommended)* |

### 3.4 Tool lifecycle

| Canonical `event_type` | Alias (display) |
|---|---|
| `tool.started` | `ToolStarted` |
| `tool.processed` | `ToolProcessed` |

### 3.5 Loop lifecycle

| Canonical `event_type` | Alias (display) |
|---|---|
| `loop.started` | `LoopStarted` |
| `loop.iteration.started` | `LoopIterationStarted` |
| `loop.iteration.finished` | `LoopIterationFinished` |
| `loop.finished` | `LoopFinished` *(recommended)* |

### 3.6 Case and routing

| Canonical `event_type` | Alias (display) |
|---|---|
| `case.started` | `CaseStarted` |
| `case.evaluated` | `CaseEvaluated` |
| `next.evaluated` | `NextEvaluated` |

### 3.7 Retry lifecycle

| Canonical `event_type` | Alias (display) |
|---|---|
| `retry.started` | `RetryStarted` |
| `retry.processed` | `RetryProcessed` |

### 3.8 Sink lifecycle

| Canonical `event_type` | Alias (display) |
|---|---|
| `sink.started` | `SinkStarted` |
| `sink.processed` | `SinkProcessed` |

---

## 4. Legacy compatibility (executor task events)

Some tool executors may emit legacy events:

| Legacy | Canonical |
|---|---|
| `task_start` | `tool.started` |
| `task_complete` | `tool.processed` (status=`success`) |
| `task_error` | `tool.processed` (status=`error`) |

If legacy events are emitted, the server SHOULD either:
- normalize them to the canonical taxonomy (recommended), or
- store both (canonical + raw legacy) for backward compatibility.

---

## 5. Control plane vs data plane emission

### 5.1 Server (control plane)

The server SHOULD emit:
- `playbook.execution.requested`
- `playbook.request.evaluated`
- `playbook.started`
- `workflow.started`
- `step.started` (when scheduling a step)
- `case.started` / `case.evaluated` (when evaluating routing on server)
- `next.evaluated` (server-authoritative routing decision)
- `workflow.finished`
- `playbook.paused`
- `playbook.processed`

### 5.2 Worker pool (data plane)

Workers MUST emit (and report to server ingestion):
- `tool.started` / `tool.processed`
- `retry.started` / `retry.processed` (for any re-execution attempts)
- `sink.started` / `sink.processed` (if sink executes on worker)
- `loop.*` iteration events (if the worker is the iteration executor)

Workers MUST NOT persist events directly into the event log storage; they report events to the server API.

---

## 6. Topics and indexing (recommended)

### 6.1 Storage indexes
Recommended event store indexes:
- `(execution_id, seq)`
- `(execution_id, event_type)`
- `(execution_id, entity_type, entity_id)`
- `(event_type, timestamp)`

### 6.2 Optional pub/sub topics
If events are also published to a broker:
- Topic = `noetl.events.<event_type>` (e.g., `noetl.events.tool.processed`)
- Include `execution_id` in message headers for fast filtering

---

## 7. Example events

### 7.1 Tool success event
```json
{
  "event_id": "01JH...",
  "event_type": "tool.processed",
  "event_alias": "ToolProcessed",
  "timestamp": "2026-01-17T23:11:22Z",
  "execution_id": "exec_01JH...",
  "entity_type": "tool",
  "entity_id": "http.fetch_weather",
  "parent_id": "step:fetch_and_evaluate:run:7",
  "status": "success",
  "duration_ms": 312,
  "iteration": 3,
  "payload": {
    "inputs": {"city": "Seattle"},
    "output": {"temp_f": 51, "rain": false},
    "meta": {"http_status": 200}
  }
}
```

### 7.2 Retry attempt event
```json
{
  "event_id": "01JH...",
  "event_type": "retry.processed",
  "event_alias": "RetryProcessed",
  "timestamp": "2026-01-17T23:11:27Z",
  "execution_id": "exec_01JH...",
  "entity_type": "retry",
  "entity_id": "retry:http.fetch_weather",
  "parent_id": "tool:http.fetch_weather:run:1",
  "attempt": 2,
  "status": "success",
  "payload": {
    "policy": "exponential",
    "delay_ms": 1000,
    "reason": "http_status_503"
  }
}
```

### 7.3 Next evaluated event (routing)
```json
{
  "event_id": "01JH...",
  "event_type": "next.evaluated",
  "event_alias": "NextEvaluated",
  "timestamp": "2026-01-17T23:11:30Z",
  "execution_id": "exec_01JH...",
  "entity_type": "next",
  "entity_id": "step:fetch_and_evaluate",
  "parent_id": "step:fetch_and_evaluate:run:7",
  "status": "success",
  "payload": {
    "selected": [
      {"step": "end_city_loop", "with": {"city": "Seattle"}}
    ],
    "mode": "server"  
  }
}
```

---

## 8. Quantum orchestration note (informative)

The taxonomy is intentionally compatible with asynchronous quantum job lifecycles:
- submission tool → `tool.processed` contains `job_id`
- polling implemented as predicate retry → `retry.*` events
- parameter sweeps implemented as loops → `loop.iteration.*` events
- results persistence → `sink.*` events

This yields a reproducible experiment trace keyed by `execution_id`.

