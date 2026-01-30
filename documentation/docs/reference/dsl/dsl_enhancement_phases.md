---
sidebar_position: 3
title: DSL Enhancement Phases
description: Roadmap for NoETL DSL improvements - Petri Net architecture with spec-based configuration
---

# DSL Enhancement Phases

This document outlines the NoETL DSL architecture evolution toward a Petri Net-compatible execution model with unified `spec:` configuration.

---

## Phase 1: Core Architecture (spec, case_mode, eval_mode, task lists)

**Priority:** Critical
**Status:** Planned
**Goal:** Establish foundational DSL patterns that enable all subsequent enhancements

### 1.1 The `spec:` Configuration Pattern

Every DSL construct can have a `spec:` attribute that configures its behavior. This provides a uniform, extensible configuration mechanism.

**Key principle:** `spec:` controls *how* a construct behaves, while other attributes define *what* it does.

```yaml
- step: process
  spec:                          # Step-level behavior
    case_mode: inclusive
    eval_mode: on_event
  tool:
    kind: http
    spec:                        # Tool-level behavior
      timeout: 30s
      retry: 3
    url: "{{ api_url }}"
  loop:
    spec:                        # Loop-level behavior
      mode: parallel
      batch_size: 10
    collection: "{{ items }}"
    element: item
  retry:
    spec:                        # Retry-level behavior
      mode: exponential
      jitter: true
    max_attempts: 5
    delay: 10
  case:
    - when: "{{ condition }}"
      spec:                      # Condition-level behavior
        cache: true
      then:
        - save_result:           # Task name (any name works)
            tool:
              kind: postgres
              spec:              # Spec goes on tool, not task key
                async: true
              command: "INSERT INTO ..."
        - next:
            spec:                # Transition-level behavior
              delay: 5s
            next:
              - step: end
```

**`spec:` options by construct:**

| Construct | `spec:` Options |
|-----------|-----------------|
| `step` | `case_mode`, `eval_mode`, `timeout`, `on_error` |
| `tool` | `timeout`, `retry`, `async`, `auth_mode` |
| `loop` | `mode` (parallel/sequential), `batch_size`, `on_error` |
| `retry` | `mode` (exponential/linear/fixed), `jitter`, `backoff_base`, `on_exhausted` |
| `when` | `cache`, `eval` (strict/lenient) |
| `next` | `delay`, `guard` |

**Existing data mechanisms:** `vars:` (transient table), `args:` (event context) - these are not part of `spec:`

**Note:** Task keys in `then:` (like `save_result:`, `notify:`, `sink:`) are just names/identifiers. The `tool:` inside defines what action to perform. `spec:` belongs to the `tool:`, not the task key.

### 1.2 Inclusive Gateway via `case_mode`

The `case:` construct gains inclusive evaluation mode:

- **`case_mode: exclusive`** (default) - XOR-split: first matching `when:` wins
- **`case_mode: inclusive`** - OR-split: ALL matching `when:` conditions execute

```yaml
- step: process_order
  spec:
    case_mode: inclusive         # Evaluate ALL conditions
  tool:
    kind: python
    code: |
      result = {"order_id": order_id, "total": total}
  case:
    # All matching conditions execute their then: blocks
    - when: "{{ workload.notify_customer }}"
      then:
        - send_email:                # Task name - can be anything
            tool:
              kind: http
              method: POST
              url: "{{ notification_api }}/email"

    - when: "{{ workload.requires_audit }}"
      then:
        - write_audit:               # Task name - can be anything
            tool:
              kind: postgres
              command: "INSERT INTO audit_log ..."

    - when: "{{ total > 1000 }}"
      then:
        - fraud_check:               # Task name - can be anything
            tool:
              kind: http
              url: "{{ fraud_check_api }}"

    # next: acts as break - exits case evaluation
    - when: "{{ event.name == 'call.done' }}"
      then:
        - next:
            next:
              - step: finalize

    # else: only fires when NO conditions matched
    - else:
        - next:
            next:
              - step: error_handler
```

**Execution semantics:**
1. All `when:` conditions are evaluated
2. ALL matching `then:` blocks execute sequentially on the same worker
3. `next:` in any `then:` block acts as a break - stops evaluation and transitions
4. `else:` only executes if zero `when:` conditions matched

### 1.3 Petri Net Mode via `eval_mode`

The `eval_mode` controls when case conditions are evaluated:

- **`eval_mode: on_entry`** (default) - case evaluated once when step is entered
- **`eval_mode: on_event`** - case evaluated on EVERY event for this execution (Petri Net mode)

```yaml
- step: wait_and_process
  spec:
    eval_mode: on_event          # Re-evaluate on every event
    case_mode: inclusive
  case:
    - when: "{{ event.name == 'message.received' and event.data.type == 'approval' }}"
      then:
        - mark_approved:
            tool: { kind: python, code: "result = {'approved': True}" }
        - next:
            next:
              - step: process_approved

    - when: "{{ event.name == 'timer.fired' and event.data.timer_id == 'timeout' }}"
      then:
        - next:
            next:
              - step: handle_timeout
```

**Petri Net mapping:**

| Petri Net Concept | DSL Element |
|-------------------|-------------|
| Place | `step:` |
| Transition | `when:` condition |
| Token | Event / execution state |
| Firing | `then:` task execution |
| Guard | `when:` expression |
| Arc | `next:` transition |

### 1.4 `then:` as Sequential Task List

The `then:` block is a list of **tasks** that execute sequentially on the same worker. Each task is a dict with a **key name** (any identifier) and a **`tool:`** that defines what action to perform:

```yaml
then:
  - save_order:                  # Task name (any identifier)
      tool:
        kind: postgres
        command: "INSERT INTO orders ..."

  - notify_webhook:              # Task name (any identifier)
      tool:
        kind: http
        url: "{{ webhook_url }}"

  - next:                        # Transition control
      next:
        - step: confirmation
```

**Task structure:**

- **Named tasks** (any key name): Contains a `tool:` that defines the action
- **`next:`**: Controls transition to next step

**Data handling (existing mechanisms):**

1. **`vars:`** - stored in `noetl.transient` table, tied to `execution_id`, accessible via server API across steps
2. **`args:`** - stored in `noetl.event` context column, can be templates (evaluated lazily when needed)
3. **Tool results** - automatically available as `{{ task_name.result }}` or `{{ step_name.data }}`
4. **Template expressions** - `{{ workload.field }}`, `{{ step_name.data.result }}`

```yaml
- step: process
  tool:
    kind: python
    args:                        # Passed via context, stored in event
      order_id: "{{ workload.order_id }}"
    code: "result = {'processed': order_id}"
  case:
    - when: "{{ event.name == 'call.done' }}"
      then:
        - next:
            next:
              - step: done
```

**Example with tool spec:**

```yaml
then:
  - persist_data:
      tool:
        kind: postgres
        spec:                    # Spec on tool
          async: true
          timeout: 30s
        command: "INSERT INTO ..."
  - next:
      next:
        - step: done
```

**Error handling:** If any task fails, execution breaks and returns control to the case evaluator (or error handler if configured).

### 1.5 Optional `tool:` on Step

When using `case:` to drive all tool executions, the step-level `tool:` becomes optional:

```yaml
# Traditional: tool on step
- step: process
  tool:
    kind: python
    code: "result = {...}"
  case:
    - when: "{{ event.name == 'call.done' }}"
      then:
        - next:
            next:
              - step: end

# New: case-driven execution (no step-level tool)
- step: process
  spec:
    case_mode: inclusive
    eval_mode: on_event
  case:
    - when: "{{ event.name == 'start' }}"
      then:
        - compute:
            tool: { kind: python, code: "result = {...}" }
    - when: "{{ event.name == 'call.done' }}"
      then:
        - next:
            next:
              - step: end
```

### 1.6 `next:` Syntax

The `next:` task in a `then:` list has consistent syntax:

```yaml
# Standard form
- next:
    next:
      - step: target_step
      - step: parallel_step    # Multiple targets = parallel fork

# With spec (delayed transition)
- next:
    spec:
      delay: 5s
    next:
      - step: target_step

# Tool-based form (alternative syntax)
- next:
    tool:
      kind: next
      step: target_step
```

### 1.7 Root-Level `executor:` (Not `spec:`)

Runtime configuration stays in `executor:` at root level, NOT in `spec:`:

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: example
  path: workflows/example

executor:                        # Runtime configuration
  profile: local                 # local | distributed
  version: noetl-runtime/1

workflow:
  - step: start
    spec:                        # DSL construct behavior (NOT at root)
      case_mode: inclusive
    # ...
```

---

## Phase 1 Implementation Plan

### Step 1: Schema Updates

1. **Update playbook schema** to accept `spec:` on all constructs
2. **Define `spec:` schemas** for each construct type
3. **Validation** - ensure `spec:` options are valid for each construct

### Step 2: Worker Changes

1. **Implement `case_mode: inclusive`** in case evaluator
   - Evaluate all conditions, collect matching `then:` blocks
   - Execute `then:` tasks sequentially
   - Stop on `next:` task (break behavior)
   - Execute `else:` only if no matches

2. **Implement `eval_mode: on_event`** in step processor
   - Subscribe to events for execution
   - Re-evaluate case on each event
   - Track which conditions have fired

3. **Implement task list execution** in `then:` processor
   - Sequential task execution on same worker
   - Error handling with break semantics
   - Named tasks with `tool:` execute tools (any tool kind)
   - `next:` is the only reserved task (controls transitions)

### Step 3: Orchestrator Changes

1. **Update event routing** for `eval_mode: on_event`
2. **Track inclusive gateway state** (which conditions fired)
3. **Support optional step-level `tool:`**

### Step 4: Server API Changes

1. **Extend event schema** for new task types
2. **Add spec validation endpoints**
3. **Update context rendering** for new patterns

### Step 5: Testing

1. **Unit tests** for each `spec:` option
2. **Integration tests** for inclusive gateway patterns
3. **Petri Net mode tests** with multiple events
4. **Performance tests** for same-worker task chains

### Step 6: Migration

1. **Update all existing playbooks** to new syntax
2. **Remove deprecated patterns**
3. **Update documentation**

---

## Phase 2: Timer Events (Future)

**Priority:** High
**Status:** Not Implemented
**Depends on:** Phase 1

Timer events enable scheduled workflows and time-based transitions.

### Proposed Syntax

```yaml
# Timer start event (cron trigger)
trigger:
  timer:
    spec:
      timezone: "America/New_York"
    cron: "0 6 * * *"

# Intermediate timer (delay)
- step: wait
  timer:
    spec:
      cancellable: true
    duration: PT2H30M
  case:
    - when: "{{ event.name == 'timer.fired' }}"
      then:
        - next:
            next:
              - step: continue

# Timer boundary (timeout with alternative path)
- step: long_task
  tool: { ... }
  timeout:
    spec:
      on_timeout: alternative    # alternative | fail | ignore
    duration: 300s
    alternative_step: timeout_handler
```

---

## Phase 3: Signal and Message Events (Future)

**Priority:** Medium
**Status:** Not Implemented
**Depends on:** Phase 1

External event waiting without polling.

### Proposed Syntax

```yaml
- step: wait_for_approval
  message:
    spec:
      timeout_action: escalate
    name: "approval_received"
    correlation:
      execution_id: "{{ execution_id }}"
      order_id: "{{ workload.order_id }}"
    timeout: 86400s
  case:
    - when: "{{ event.name == 'message.received' }}"
      then:
        - next:
            next:
              - step: process_approved
    - when: "{{ event.name == 'message.timeout' }}"
      then:
        - next:
            next:
              - step: escalate
```

---

## Phase 4: Human Tasks (Future)

**Priority:** Medium
**Status:** Not Implemented
**Depends on:** Phase 1, Phase 3

Human-in-the-loop workflows with task assignment.

### Proposed Syntax

```yaml
- step: manager_approval
  human_task:
    spec:
      escalation_mode: reassign
    title: "Approve Purchase Order"
    assignee:
      role: "finance_manager"
    form:
      - field: decision
        type: enum
        options: [approve, reject]
    due_date: "{{ now() + duration('P2D') }}"
    escalation:
      after: 48h
      to_role: "finance_director"
  case:
    - when: "{{ event.name == 'task.completed' }}"
      then:
        - next:
            next:
              - step: "{{ 'process' if result.decision == 'approve' else 'reject' }}"
```

---

## Phase 5: Compensation Handlers / Saga (Future)

**Priority:** Medium
**Status:** Not Implemented
**Depends on:** Phase 1

Automatic rollback for failed multi-step transactions.

### Proposed Syntax

```yaml
- step: create_order
  tool:
    kind: postgres
    command: "INSERT INTO orders ..."
  compensate:
    spec:
      idempotent: true
    tool:
      kind: postgres
      command: "DELETE FROM orders WHERE id = {{ result.order_id }}"
  case:
    - when: "{{ event.name == 'call.done' }}"
      then:
        - next:
            next:
              - step: reserve_inventory
    - when: "{{ event.name == 'call.error' }}"
      then:
        - next:
            spec:
              trigger_compensation: true    # Run all compensations in reverse
            next:
              - step: order_failed
```

---

## Phase 6: Advanced Event Patterns (Future)

**Priority:** Low
**Status:** Not Implemented
**Depends on:** Phase 1, Phase 2, Phase 3

Complex event-driven patterns.

### Event Sub-Process

```yaml
- step: main_processing
  tool: { ... }
  on_event:
    spec:
      interrupting: false
    - event: "audit.required"
      then:
        - log_audit:
            tool: { kind: audit_logger, ... }
```

### Event-Based Gateway

```yaml
- step: wait_for_response
  spec:
    eval_mode: on_event
    case_mode: exclusive         # First event wins
  case:
    - when: "{{ event.name == 'message.received' }}"
      then:
        - next: { next: [{ step: handle_response }] }
    - when: "{{ event.name == 'timer.fired' }}"
      then:
        - next: { next: [{ step: send_reminder }] }
    - when: "{{ event.name == 'signal.received' and event.data.name == 'cancelled' }}"
      then:
        - next: { next: [{ step: abort }] }
```

---

## Implementation Priority Matrix

| Phase | Feature | Impact | Complexity | Priority |
|-------|---------|--------|------------|----------|
| 1 | Core Architecture (spec, case_mode, eval_mode) | **Critical** | High | **P0** |
| 2 | Timer Events | High | Medium | **P1** |
| 3 | Signal/Message Events | Medium | High | **P2** |
| 4 | Human Tasks | Medium | High | **P2** |
| 5 | Compensation Handlers | Medium | Medium | **P2** |
| 6 | Advanced Event Patterns | Low | High | **P3** |

**Note:** Data handling uses existing mechanisms: `vars:` (transient table), `args:` (event context), and tool results.

---

## References

- [BPMN 2.0 Specification](https://www.omg.org/spec/BPMN/2.0/)
- [Workflow Patterns](http://www.workflowpatterns.com/)
- [Petri Net Theory](https://en.wikipedia.org/wiki/Petri_net)
- [NoETL DSL Analysis](./dsl_analysis_and_evaluation.md)
- [Saga Pattern](https://microservices.io/patterns/data/saga.html)
