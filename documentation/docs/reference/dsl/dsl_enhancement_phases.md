---
sidebar_position: 3
title: DSL Enhancement Phases
description: Roadmap for NoETL DSL improvements to achieve full BPMN 2.0 and workflow pattern coverage
---

# DSL Enhancement Phases

This document outlines planned enhancements to the NoETL DSL to achieve complete coverage of BPMN 2.0 patterns and advanced workflow capabilities. Each phase is prioritized by impact and implementation complexity.

---

## Phase 1: Inclusive Gateway (OR-Split/OR-Join)

**Priority:** High  
**Status:** Not Implemented  
**Gap:** No mechanism for multiple conditional branches where ALL matching conditions fire

### Problem Statement

Currently, the DSL supports:
- **AND-split** (parallel fork): `next:` with multiple steps - ALL paths taken unconditionally
- **XOR-split** (exclusive choice): `case:` with `when:` conditions - FIRST match wins

Missing: **OR-split** (inclusive gateway) - evaluate ALL conditions, take ALL paths where condition is TRUE.

### Current Workaround

Use explicit parallel fork with guards at each branch:

```yaml
- step: dispatch
  tool: { kind: python, code: "result = {}" }
  next:
    - step: check_a
    - step: check_b
    - step: check_c

- step: check_a
  case:
    - when: "{{ workload.condition_a }}"
      then:
        next:
          - step: do_a
  next:
    - step: or_join

- step: check_b
  case:
    - when: "{{ workload.condition_b }}"
      then:
        next:
          - step: do_b
  next:
    - step: or_join

# ... each branch checks its condition and either proceeds or skips to join
```

**Limitation:** Verbose, requires explicit skip-to-join logic, error-prone.

### Proposed Enhancement

#### Option A: `mode: inclusive` on `next:`

```yaml
- step: decision_point
  tool: { kind: python, code: "..." }
  next:
    mode: inclusive  # Evaluate ALL conditions, take ALL matching paths
    branches:
      - when: "{{ workload.priority == 'high' }}"
        step: high_priority_handler
      - when: "{{ workload.requires_audit }}"
        step: audit_logger
      - when: "{{ workload.notify_user }}"
        step: send_notification
    default: skip_to_end  # If no conditions match
```

#### Option B: Explicit `or_gateway:` construct

```yaml
- step: or_split
  or_gateway:
    - when: "{{ condition_a }}"
      then: branch_a
    - when: "{{ condition_b }}"
      then: branch_b
    - when: "{{ condition_c }}"
      then: branch_c
    default: fallback_step
```

#### Option C: `all_matching: true` flag on `case:`

```yaml
- step: decision
  tool: { kind: python, code: "..." }
  case:
    all_matching: true  # Fire ALL matching conditions (not just first)
    conditions:
      - when: "{{ condition_a }}"
        then:
          next:
            - step: branch_a
      - when: "{{ condition_b }}"
        then:
          next:
            - step: branch_b
```

### OR-Join (Inclusive Merge)

The corresponding OR-join waits for ALL active incoming branches (only those that were actually taken):

```yaml
- step: or_join
  join:
    mode: inclusive  # Wait for all ACTIVE incoming branches
    timeout: 300     # Optional timeout in seconds
  next:
    - step: continue_workflow
```

**Implementation Note:** Server must track which branches were activated at the OR-split to know which ones to wait for at OR-join.

### Implementation Requirements

1. **Server-side tracking:** Track activated branches per execution
2. **Event extension:** Add `branches.activated` event with list of taken paths
3. **Join logic:** OR-join step queries active branches and waits accordingly
4. **NATS KV:** Store branch activation state for join resolution

---

## Phase 2: Timer Events

**Priority:** High  
**Status:** Not Implemented  
**Gap:** No timer start events, intermediate timer events, or deadline-based triggers

### Problem Statement

Workflows cannot:
- Start on a schedule (cron-like)
- Wait for a duration before proceeding
- Have deadline-based timeouts on steps

### Current Workaround

External scheduler (cron, Kubernetes CronJob) triggers workflow via API.

### Proposed Enhancement

#### Timer Start Event

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: scheduled_report
  path: reports/daily_summary
trigger:
  timer:
    cron: "0 6 * * *"  # Daily at 6 AM
    timezone: "America/New_York"
workflow:
  - step: start
    # ...
```

#### Intermediate Timer Event (Wait/Delay)

```yaml
- step: rate_limit_pause
  timer:
    duration: 60s  # Wait 60 seconds before next step
  next:
    - step: continue_processing
```

Or as ISO 8601 duration:

```yaml
- step: wait_for_settlement
  timer:
    duration: PT2H30M  # Wait 2 hours 30 minutes
  next:
    - step: check_settlement
```

#### Timer Boundary Event (Step Timeout with Alternative Path)

```yaml
- step: long_running_task
  tool:
    kind: http
    url: "{{ api_url }}/process"
  timeout:
    duration: 300s
    on_timeout:
      step: timeout_handler  # Alternative path if step exceeds duration
  next:
    - step: normal_continuation
```

### Implementation Requirements

1. **Timer service:** Background process that fires timer events
2. **Event types:** `timer.fired`, `timer.cancelled`
3. **State tracking:** Pending timers stored in NATS KV or database
4. **Trigger integration:** Server listens for timer events to start executions

---

## Phase 3: Signal and Message Events

**Priority:** Medium  
**Status:** Partial (polling via retry)  
**Gap:** No true wait-for-external-event capability

### Problem Statement

Workflows cannot pause and wait for external signals/messages without polling.

### Current Workaround

```yaml
- step: poll_for_completion
  tool:
    kind: http
    url: "{{ callback_url }}/status"
  retry:
    max_attempts: 60
    delay: 10
    when: "{{ result.status != 'complete' }}"
  next:
    - step: continue
```

**Limitation:** Wastes resources polling, not event-driven.

### Proposed Enhancement

#### Message Catch Event (Wait for External Message)

```yaml
- step: wait_for_approval
  message:
    name: "approval_received"
    correlation:
      execution_id: "{{ execution_id }}"
      order_id: "{{ workload.order_id }}"
    timeout: 86400s  # 24 hour timeout
    on_timeout:
      step: escalate_approval
  next:
    - step: process_approved_order
```

#### Signal Catch Event (Broadcast to Multiple Executions)

```yaml
- step: wait_for_market_open
  signal:
    name: "market_opened"
    filter:
      market: "{{ workload.market }}"
  next:
    - step: start_trading
```

#### External API to Send Messages/Signals

```bash
# Send message to specific execution
POST /api/message
{
  "name": "approval_received",
  "correlation": {"execution_id": 123, "order_id": "ORD-456"},
  "payload": {"approved_by": "manager@example.com"}
}

# Broadcast signal to all waiting executions
POST /api/signal
{
  "name": "market_opened",
  "filter": {"market": "NYSE"},
  "payload": {"open_time": "2024-01-15T09:30:00Z"}
}
```

### Implementation Requirements

1. **Message queue:** NATS subjects for message/signal delivery
2. **Correlation:** Match incoming messages to waiting executions
3. **Wait state:** Steps in "waiting" state don't consume worker resources
4. **API endpoints:** External systems can send messages/signals

---

## Phase 4: Human Tasks

**Priority:** Medium  
**Status:** Not Implemented  
**Gap:** No user task construct for human-in-the-loop workflows

### Problem Statement

Workflows cannot assign tasks to humans and wait for completion.

### Proposed Enhancement

```yaml
- step: manager_approval
  human_task:
    title: "Approve Purchase Order"
    description: "Review and approve PO #{{ workload.po_number }}"
    assignee:
      role: "finance_manager"
      # Or specific user:
      # user: "{{ workload.manager_email }}"
    form:
      - field: decision
        type: enum
        options: [approve, reject, request_changes]
        required: true
      - field: comments
        type: text
        required: false
    due_date: "{{ (now() + timedelta(days=2)).isoformat() }}"
    escalation:
      after: 48h
      to_role: "finance_director"
  next:
    - when: "{{ result.decision == 'approve' }}"
      then:
        - step: process_order
    - when: "{{ result.decision == 'reject' }}"
      then:
        - step: notify_rejection
    - when: "{{ result.decision == 'request_changes' }}"
      then:
        - step: return_to_requester
```

### Implementation Requirements

1. **Task inbox:** UI/API for users to view assigned tasks
2. **Form rendering:** Dynamic form generation from schema
3. **Assignment logic:** Role-based or direct user assignment
4. **Escalation:** Timer-based reassignment
5. **Audit trail:** Track who completed task and when

---

## Phase 5: Compensation Handlers (Saga Pattern)

**Priority:** Medium  
**Status:** Not Implemented  
**Gap:** No rollback mechanism for failed multi-step transactions

### Problem Statement

When a step fails in a multi-step workflow, there's no automatic way to undo previous successful steps.

### Current Workaround

Manual error handling with explicit rollback logic:

```yaml
- step: process
  case:
    - when: "{{ event.name == 'call.error' }}"
      then:
        next:
          - step: manual_rollback_step_1
```

**Limitation:** Error-prone, doesn't scale with workflow complexity.

### Proposed Enhancement

```yaml
- step: create_order
  tool:
    kind: postgres
    query: "INSERT INTO orders ..."
  compensate:
    tool:
      kind: postgres
      query: "DELETE FROM orders WHERE id = {{ result.order_id }}"
  next:
    - step: reserve_inventory

- step: reserve_inventory
  tool:
    kind: http
    method: POST
    url: "{{ inventory_api }}/reserve"
  compensate:
    tool:
      kind: http
      method: POST
      url: "{{ inventory_api }}/release"
      body:
        reservation_id: "{{ result.reservation_id }}"
  next:
    - step: charge_payment

- step: charge_payment
  tool:
    kind: http
    method: POST
    url: "{{ payment_api }}/charge"
  # If this fails, server automatically runs compensate handlers in reverse order:
  # 1. release inventory
  # 2. delete order
  compensate:
    tool:
      kind: http
      method: POST
      url: "{{ payment_api }}/refund"
  next:
    - step: end
```

### Implementation Requirements

1. **Compensation stack:** Server tracks completed steps with their compensate actions
2. **Automatic rollback:** On failure, execute compensations in reverse order
3. **Compensation state:** Track compensation progress (partial rollback scenarios)
4. **Idempotency:** Compensations should be idempotent

---

## Phase 6: Advanced Event Patterns

**Priority:** Low  
**Status:** Partial  
**Gap:** Limited event-based workflow patterns

### Proposed Enhancements

#### Event Sub-Process (Non-Interrupting)

Run parallel handler when event occurs without stopping main flow:

```yaml
- step: main_processing
  tool: { ... }
  on_event:
    - event: "audit.required"
      non_interrupting: true
      handler:
        - step: log_audit
          tool: { ... }
  next:
    - step: continue
```

#### Event-Based Gateway (Wait for First of Multiple Events)

```yaml
- step: wait_for_response
  event_gateway:
    - message:
        name: "customer_response"
        then: handle_response
    - timer:
        duration: 24h
        then: send_reminder
    - signal:
        name: "order_cancelled"
        then: abort_process
```

---

## Implementation Priority Matrix

| Phase | Feature | Impact | Complexity | Priority |
|-------|---------|--------|------------|----------|
| 1 | Inclusive Gateway (OR) | High | Medium | **P1** |
| 2 | Timer Events | High | Medium | **P1** |
| 3 | Signal/Message Events | Medium | High | **P2** |
| 4 | Human Tasks | Medium | High | **P2** |
| 5 | Compensation Handlers | Medium | Medium | **P2** |
| 6 | Advanced Event Patterns | Low | High | **P3** |

---

## Migration Notes

All enhancements should:
1. **Be backward compatible** - existing playbooks continue to work
2. **Follow V2 DSL conventions** - consistent syntax with existing constructs
3. **Leverage NATS infrastructure** - use JetStream/KV for state management
4. **Emit proper events** - extend event schema for new constructs
5. **Include comprehensive tests** - add to `tests/fixtures/playbooks/`

---

## References

- [BPMN 2.0 Specification](https://www.omg.org/spec/BPMN/2.0/)
- [Workflow Patterns](http://www.workflowpatterns.com/)
- [NoETL DSL Analysis](./dsl_analysis_and_evaluation.md)
- [Saga Pattern](https://microservices.io/patterns/data/saga.html)
