---
sidebar_position: 4
title: DSL Specification
description: Complete technical specification for NoETL DSL v2 - Petri Net execution model
---

# NoETL DSL v2 Technical Specification

This document provides a complete technical specification for the NoETL DSL execution model, covering case evaluation, routing control, retry semantics, and event sourcing.

---

## 1. Case Evaluation Model

### 1.1 Case Modes

The `case_mode` attribute controls how multiple `when:` conditions are evaluated and executed.

#### `case_mode: exclusive` (Default)

- **Semantics**: XOR-split - exactly one branch fires
- **Selection**: First matching `when:` in YAML order (or highest priority, then YAML order)
- **Execution**: Single branch executes; no parallel firing
- **Use case**: Traditional if/else-if/else branching

```yaml
- step: process
  spec:
    case_mode: exclusive  # default
  tool:
    kind: postgres
    command: "SELECT * FROM orders WHERE id = {{ order_id }}"
  case:
    - when: "{{ result.rows | length > 0 }}"
      then:
        - next:
            to:
              - step: process_order
    - when: "{{ event.name == 'call.done' }}"
      then:
        - next:
            to:
              - step: order_not_found
```

#### `case_mode: inclusive`

- **Semantics**: OR-split - all matching branches are selected (the "firing set")
- **Selection**: All matching `when:` conditions at evaluation time
- **Execution**: Selected branches execute sequentially in deterministic order (YAML order / priority)
- **Use case**: Fan-out patterns, multiple parallel actions from single result

```yaml
- step: process_order
  spec:
    case_mode: inclusive
  tool:
    kind: python
    code: |
      result = {"order_id": order_id, "total": total}
  case:
    - when: "{{ workload.notify_customer }}"
      then:
        - send_email:
            tool:
              kind: http
              method: POST
              url: "{{ notification_api }}/email"

    - when: "{{ workload.requires_audit }}"
      then:
        - write_audit:
            tool:
              kind: postgres
              command: "INSERT INTO audit_log ..."

    - when: "{{ total > 1000 }}"
      then:
        - fraud_check:
            tool:
              kind: http
              url: "{{ fraud_check_api }}"

    - when: "{{ event.name == 'call.done' }}"
      then:
        - next:
            to:
              - step: finalize
```

### 1.2 Evaluation Modes

The `eval_mode` attribute controls when case conditions are evaluated.

#### `eval_mode: on_entry` (Default)

- Case evaluated once when step is entered
- Tool executes, then case conditions evaluated against result
- Standard request-response pattern

#### `eval_mode: on_event`

- Case evaluated on EVERY event for this execution (Petri Net mode)
- Step runtime stays active, waiting for events
- Enables event-driven workflows, human tasks, external signals

```yaml
- step: wait_for_approval
  spec:
    eval_mode: on_event
    case_mode: exclusive
  case:
    - when: "{{ event.name == 'message.received' and event.data.type == 'approval' }}"
      then:
        - next:
            to:
              - step: process_approved

    - when: "{{ event.name == 'timer.fired' and event.data.timer_id == 'timeout' }}"
      then:
        - next:
            to:
              - step: handle_timeout
```

### 1.3 Branch Ordering

The `branch_order` attribute controls execution order for inclusive mode.

- **`branch_order: source`** (default): YAML order
- **`branch_order: priority`**: By `priority` attribute, then YAML order

```yaml
- step: parallel_tasks
  spec:
    case_mode: inclusive
    branch_order: priority
  case:
    - when: "{{ condition_a }}"
      priority: 10
      then: [...]
    - when: "{{ condition_b }}"
      priority: 5
      then: [...]
```

---

## 2. Routing Control (`next:`)

### 2.1 `next` as Control Action

The `next:` action is NOT "just another action" - it is a **step-control instruction** that creates a `RoutingIntent`.

When an action chain hits `next`:
1. Execution of the current chain stops
2. A routing decision is recorded
3. The `next_policy` determines what happens to other branches

### 2.2 Next Policies

#### `next_policy: end_step` (Recommended Default)

- `next` behaves like `return`:
  - Stop executing the current chain
  - Stop the entire step runtime for this `step_run_id`
  - Skip any remaining queued branches (inclusive mode)
  - Commit routing and transition to target step(s)

This matches the "break" expectation most closely.

```yaml
- step: process
  spec:
    case_mode: inclusive
    next_policy: end_step  # default
  case:
    - when: "{{ condition_a }}"
      then:
        - do_something:
            tool: { ... }
        - next:
            to:
              - step: done
    # If condition_a matches and next is reached, condition_b chain never runs
    - when: "{{ condition_b }}"
      then:
        - do_other:
            tool: { ... }
```

#### `next_policy: break_chain`

- `next` stops only the current chain
- Other inclusive branches (already selected) may continue executing
- Routing is deferred until all selected branches complete

```yaml
- step: parallel_tasks
  spec:
    case_mode: inclusive
    next_policy: break_chain
  case:
    - when: "{{ cond_a }}"
      then:
        - task_a:
            tool: { ... }
        - next:
            to:
              - step: done
    - when: "{{ cond_b }}"
      then:
        - task_b:
            tool: { ... }
        # task_b still executes even if task_a's next was reached
```

#### `next_policy: defer`

- `next` records a routing request, but execution continues
- Routing happens at the end of the "epoch" (after all selected branches finish)
- Multiple `next` requests are collected; winner is determined by priority or first-reached

### 2.3 Winner Rule for Inclusive Mode

When inclusive mode selects multiple branches, more than one might hit `next`.

**Winner Rule (deterministic)**:
- The first `next` reached in execution order wins
- "Execution order" = branch execution order (YAML/priority), then action order within chain

When the winner `next` is reached:
1. Emit `next.evaluated` event (or `next.requested` with `pending=true`)
2. Apply the `next_policy`

If policy is `end_step`:
- Mark remaining branches as `suppressed`
- Emit `case.branch.suppressed` event for audit trail

### 2.4 Next Syntax

```yaml
# Standard form
- next:
    to:
      - step: target_step
      - step: parallel_step    # Multiple targets = parallel fork

# With policy override
- next:
    to:
      - step: target_step
    policy: end_step           # Override step default
    priority: 10               # If multiple next requested, choose highest

# With spec (delayed transition)
- next:
    spec:
      delay: 5s
    to:
      - step: target_step

# Conditional routing
- next:
    to:
      - step: "{{ 'success' if result.valid else 'failure' }}"
```

---

## 3. Task Execution in `then:` Blocks

### 3.1 Task Structure

The `then:` block is a list of **tasks** that execute sequentially on the same worker.

```yaml
then:
  - task_name:           # Any identifier (user-defined name)
      tool:              # Required: defines what action to perform
        kind: http
        method: POST
        url: "{{ api_url }}"
      retry:             # Optional: retry policy for this tool
        max_attempts: 3
        backoff: { ... }

  - another_task:
      tool:
        kind: postgres
        command: "INSERT INTO ..."

  - next:                # Control action: transition to next step
      to:
        - step: done
```

### 3.2 Reserved Task Names

- `next:` - Routing control (see section 2)
- `sink:` - Data sink operation (alias for a task with tool)

All other names are user-defined identifiers for the task.

### 3.3 Data Flow

1. **`args:`** - Passed to tool via context, stored in event
2. **`vars:`** - Stored in `noetl.transient` table, accessible across steps via server API
3. **Tool results** - Available as `{{ task_name.result }}` or `{{ step_name.data }}`
4. **Template expressions** - `{{ workload.field }}`, `{{ step_name.data.result }}`

---

## 4. Retry Semantics

### 4.1 Retry Scope

Retry applies to **executable actions** (tool calls), not to steps.

#### `retry.scope: tool` (Recommended Default)

- Retry wraps each tool invocation
- Each tool call can override retry policy

```yaml
- compute:
    tool:
      kind: http
      url: "{{ api_url }}"
    retry:
      scope: tool
      max_attempts: 5
      backoff:
        type: exponential
        delay_seconds: 1
        max_delay_seconds: 30
```

#### `retry.scope: chain` (Optional)

- Retry wraps a specific `then:` chain as a unit
- If any tool in the chain fails, restart the entire chain

```yaml
- step: transactional
  case:
    - when: "{{ event.name == 'call.done' }}"
      retry:
        scope: chain
        max_attempts: 3
      then:
        - step_a:
            tool: { ... }
        - step_b:
            tool: { ... }
        # If step_b fails, entire chain (step_a + step_b) retries
```

#### `retry.scope: step` (Avoid)

- **Not recommended** under `eval_mode: on_event`
- Only allow for "simple step" with single entry tool and no case-driven tool calls
- Step-level retry should be treated as **default tool retry inheritance**

### 4.2 Retry Inheritance

Priority order (highest to lowest):
1. `action.tool.retry` - explicit on the tool call
2. `case.then[*].retry` - chain default
3. `step.retry` - step default (inherited by tools)
4. Runtime default

### 4.3 Retry vs Polling

**Failure Retry**:
- Triggered by: error, status_code, exception
- Exponential/linear/fixed backoff
- Events: `retry.started`, `retry.processed`

**Polling / Until**:
- Triggered by: predicate not yet true
- Separate concept from failure retry
- Events: `poll.started`, `poll.iteration`, `poll.finished`

```yaml
- wait_for_ready:
    tool:
      kind: http
      url: "{{ status_api }}"
    retry:
      on: error
      max_attempts: 3
    poll:
      until: "{{ result.status == 'ready' }}"
      interval: 5s
      max_attempts: 60
      deadline: 300s
```

### 4.4 Idempotency Keys

Each tool invocation gets a stable `action_id` for idempotency:

```
action_id = hash(step_run_id, branch_id, chain_index, iteration, page, event_epoch)
```

Retries share the same `action_id` with incrementing `attempt`:
- `tool.started { action_id: X, attempt: 1 }`
- `tool.processed { action_id: X, attempt: 1, status: error }`
- `retry.started { action_id: X, attempt: 2 }`
- `tool.started { action_id: X, attempt: 2 }`
- `tool.processed { action_id: X, attempt: 2, status: success }`

---

## 5. Event Sourcing Model

### 5.1 Event Layers

Three primary layers plus control events:

```
┌─────────────────────────────────────────────────────────────┐
│ Workflow Layer (Control Plane)                              │
│   playbook.execution.requested                              │
│   playbook.request.evaluated                                │
│   playbook.started                                          │
│   workflow.started                                          │
│   workflow.finished                                         │
│   playbook.processed                                        │
├─────────────────────────────────────────────────────────────┤
│ Step Layer (Step Instance Lifecycle)                        │
│   step.started                                              │
│   step.paused / step.resumed                               │
│   step.finished                                             │
├─────────────────────────────────────────────────────────────┤
│ Tool Layer (Data Plane)                                     │
│   tool.started                                              │
│   tool.processed                                            │
├─────────────────────────────────────────────────────────────┤
│ Control Sub-entities                                        │
│   case.started / case.evaluated                            │
│   next.evaluated                                            │
│   loop.started / loop.iteration.* / loop.finished          │
│   retry.started / retry.processed                          │
│   sink.started / sink.processed                            │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 Event Ownership

| Event Type | Emitted By | Authoritative |
|------------|------------|---------------|
| `workflow.*` | Server | Server |
| `playbook.*` | Server | Server |
| `step.started` | Server | Server |
| `step.finished` | Server | Server |
| `tool.*` | Worker | Worker |
| `case.*` | Worker | Worker |
| `next.evaluated` | Worker | Server (commits) |
| `retry.*` | Worker | Worker |
| `sink.*` | Worker | Worker |

### 5.3 Event Envelope

Every event contains these fields for queryability:

```json
{
  "event_id": "snowflake_id",
  "event_type": "tool.processed",
  "timestamp": "2026-01-31T12:00:00Z",

  "execution_id": "123",
  "workflow_run_id": "W1",
  "step_run_id": "S7",
  "tool_run_id": "T9",

  "entity_type": "tool",
  "entity_id": "T9",
  "parent_id": "S7",

  "action_id": "stable_hash",
  "attempt": 1,
  "iteration": 0,
  "page": 0,

  "payload": { ... }
}
```

### 5.4 Case Evaluation Events

When inclusive mode selects branches:

```json
{
  "event_type": "case.evaluated",
  "step_run_id": "S7",
  "payload": {
    "matched": ["case_0", "case_1", "case_2"],
    "order": ["case_0", "case_1", "case_2"],
    "case_mode": "inclusive",
    "eval_mode": "on_entry",
    "trigger_event": "call.done"
  }
}
```

When `next` is reached:

```json
{
  "event_type": "next.evaluated",
  "step_run_id": "S7",
  "payload": {
    "selected": [{"step": "done", "with": {}}],
    "policy": "end_step",
    "winner_branch": "case_0",
    "suppressed_branches": ["case_1", "case_2"],
    "routing_committed": true
  }
}
```

### 5.5 Nesting via IDs

Events reference their parent scope:

```
workflow.started  → workflow_run_id=W1
  step.started    → step_run_id=S7, parent=W1
    tool.started  → tool_run_id=T9, parent=S7
    tool.processed→ parent=S7
    case.evaluated→ parent=S7
    next.evaluated→ parent=S7
  step.finished   → step_run_id=S7, parent=W1
workflow.finished → workflow_run_id=W1
```

---

## 6. Session Management (NATS K/V)

### 6.1 Overview

Sessions are stored in NATS Key/Value store instead of PostgreSQL for:
- Built-in TTL support
- Version tracking (history)
- Faster access (in-memory)
- Distributed caching

### 6.2 Key Structure

```
noetl.sessions.<session_token>
```

### 6.3 Value Structure

```json
{
  "session_id": 123,
  "user_id": 456,
  "email": "user@example.com",
  "display_name": "User Name",
  "roles": ["admin", "developer"],
  "created_at": "2026-01-31T12:00:00Z",
  "expires_at": "2026-02-01T12:00:00Z",
  "last_activity_at": "2026-01-31T12:30:00Z",
  "client_ip": "192.168.1.1",
  "auth0_id": "auth0|123"
}
```

### 6.4 Operations

| Operation | NATS K/V Method |
|-----------|-----------------|
| Create session | `kv.put(key, value, ttl)` |
| Validate session | `kv.get(key)` |
| Update activity | `kv.update(key, value, revision)` |
| Invalidate | `kv.delete(key)` |
| List user sessions | `kv.keys("noetl.sessions.user.<user_id>.*")` |

### 6.5 TTL Management

- Session TTL set on creation (e.g., 24 hours)
- TTL refreshed on activity (sliding expiration)
- Automatic cleanup by NATS

---

## 7. Complete Step Spec Schema

```yaml
- step: step_name
  desc: "Step description"

  spec:
    # Case evaluation
    case_mode: exclusive | inclusive    # default: exclusive
    eval_mode: on_entry | on_event      # default: on_entry
    branch_order: source | priority     # default: source

    # Routing control
    next_policy: end_step | break_chain | defer  # default: end_step

    # Step-level defaults
    timeout: 300s
    on_error: fail | ignore | retry

  # Entry tool (optional if case-driven)
  tool:
    kind: postgres | python | http | shell | ...
    spec:
      timeout: 30s
      retry: 3
      async: true
    auth: "{{ credential_ref }}"
    command: "..."

  # Default retry policy (inherited by tools)
  retry:
    max_attempts: 3
    backoff:
      type: exponential | linear | fixed
      delay_seconds: 1
      max_delay_seconds: 60
      jitter: true

  # Loop configuration
  loop:
    spec:
      mode: parallel | sequential
      batch_size: 10
      on_error: fail | continue
    collection: "{{ items }}"
    element: item

  # Case conditions
  case:
    - when: "{{ condition }}"
      priority: 10                      # optional, for branch_order: priority
      spec:
        cache: true
      then:
        - task_name:
            tool:
              kind: http
              method: POST
              url: "{{ api_url }}"
            retry:
              max_attempts: 5
        - next:
            to:
              - step: target
            policy: end_step            # optional override

    - else:
        - next:
            to:
              - step: error_handler
```

---

## 8. Implementation Phases

### Phase 1: Core Architecture
1. Implement `spec:` configuration pattern
2. Implement `case_mode: exclusive | inclusive`
3. Implement `eval_mode: on_entry | on_event`
4. Implement `then:` as sequential task list with named tasks
5. Implement `next:` as control action with policies

### Phase 2: Event Sourcing
1. Add workflow-level events
2. Add step-level events
3. Add tool-level events
4. Add control events (case, next, loop, retry)
5. Implement event envelope with correlation IDs

### Phase 3: Session Management
1. Implement NATS K/V session store
2. Migrate from PostgreSQL sessions table
3. Add TTL management
4. Add session versioning

### Phase 4: Retry Enhancements
1. Implement retry scope (tool, chain)
2. Implement retry inheritance
3. Implement polling/until semantics
4. Add idempotency key generation

---

## 9. Migration Guide

### From Current DSL to v2

**Before (current)**:
```yaml
case:
  - when: "{{ condition }}"
    then:
      - sink:
          tool:
            kind: http
            ...
      - next:
          - step: end
```

**After (v2)**:
```yaml
case:
  - when: "{{ condition }}"
    then:
      - send_result:
          tool:
            kind: http
            ...
      - next:
          to:
            - step: end
```

Key changes:
1. `sink:` becomes a named task with `tool:`
2. `next:` uses `to:` instead of direct list
3. Add `spec:` for behavior configuration
4. Add `retry:` at tool level, not step level

---

## References

- [DSL Enhancement Phases](./dsl_enhancement_phases.md)
- [BPMN 2.0 Specification](https://www.omg.org/spec/BPMN/2.0/)
- [Workflow Patterns](http://www.workflowpatterns.com/)
- [Petri Net Theory](https://en.wikipedia.org/wiki/Petri_net)
