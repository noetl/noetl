---
sidebar_position: 4
title: Workflow Patterns Comparison
description: Analysis of NoETL DSL against Van der Aalst Workflow Patterns with cross-DSL comparison
---

# Workflow Patterns Comparison

This document analyzes the NoETL DSL against the canonical Workflow Patterns identified by Van der Aalst et al., comparing implementation approaches across major workflow DSLs: BPMN 2.0, Argo Workflows, GitHub Actions, and AWS Step Functions.

---

## Overview: Van der Aalst Workflow Patterns

The [Workflow Patterns Initiative](http://www.workflowpatterns.com/) established a taxonomy of patterns that serve as the "litmus test" for workflow engines. Any production-grade engine must support the **Basic Control Flow Patterns** to represent fundamental business logic.

### Pattern Categories

| Category | Patterns | Importance |
|----------|----------|------------|
| **Basic Control Flow** | Sequence, AND-Split, AND-Join, XOR-Split, XOR-Join | Essential (5) |
| **Advanced Branching** | Multi-Choice (OR-Split), Structured Sync Merge, Multi-Merge | Important (3) |
| **Structural** | Arbitrary Cycles, Implicit Termination | Important (2) |
| **Multi-Instance** | MI with/without synchronization, MI with a priori runtime knowledge | Modern requirement |
| **State-Based** | Deferred Choice, Interleaved Parallel Routing, Milestone | Advanced |
| **Cancellation** | Cancel Task, Cancel Case, Cancel Region | Enterprise |

---

## Basic Control Flow Patterns

### Pattern 1: Sequence

> Tasks execute one after another. Task B starts only after Task A completes.

**DSL Requirement:** Linear dependency between activities.

| DSL | Implementation | Example |
|-----|----------------|---------|
| **NoETL** | `next:` with single step | ✅ Native |
| **BPMN** | Sequence Flow arrow | ✅ Native |
| **Argo Workflows** | `dependencies:` array | ✅ Native |
| **GitHub Actions** | `needs:` array | ✅ Native |
| **Step Functions** | `Next:` field | ✅ Native |

#### NoETL Implementation

```yaml
workflow:
  - step: task_a
    tool:
      kind: python
      code: "result = {'value': 42}"
    next:
      - step: task_b

  - step: task_b
    tool:
      kind: python
      args:
        input: "{{ task_a.value }}"
      code: "result = {'processed': input * 2}"
    next:
      - step: end
```

#### Cross-DSL Comparison

<details>
<summary>BPMN 2.0</summary>

```xml
<sequenceFlow id="flow1" sourceRef="task_a" targetRef="task_b"/>
<sequenceFlow id="flow2" sourceRef="task_b" targetRef="end"/>
```
</details>

<details>
<summary>Argo Workflows</summary>

```yaml
templates:
  - name: main
    dag:
      tasks:
        - name: task-a
          template: process-a
        - name: task-b
          dependencies: [task-a]
          template: process-b
```
</details>

<details>
<summary>GitHub Actions</summary>

```yaml
jobs:
  task_a:
    runs-on: ubuntu-latest
    steps:
      - run: echo "Task A"
  task_b:
    needs: task_a
    runs-on: ubuntu-latest
    steps:
      - run: echo "Task B"
```
</details>

<details>
<summary>AWS Step Functions</summary>

```json
{
  "States": {
    "TaskA": {
      "Type": "Task",
      "Next": "TaskB"
    },
    "TaskB": {
      "Type": "Task",
      "End": true
    }
  }
}
```
</details>

---

### Pattern 2: Parallel Split (AND-Split)

> A single thread splits into multiple threads executing simultaneously.

**DSL Requirement:** Fork/parallel gateway triggering multiple outgoing paths at once.

| DSL | Implementation | Example |
|-----|----------------|---------|
| **NoETL** | `next:` with multiple steps | ✅ Native |
| **BPMN** | Parallel Gateway (diamond with +) | ✅ Native |
| **Argo Workflows** | Multiple tasks without dependencies | ✅ Native |
| **GitHub Actions** | Multiple jobs without `needs:` | ✅ Native |
| **Step Functions** | `Parallel` state type | ✅ Native |

#### NoETL Implementation

```yaml
workflow:
  - step: start
    tool:
      kind: python
      code: "result = {'ready': True}"
    next:
      - step: branch_a  # All three execute in parallel
      - step: branch_b
      - step: branch_c

  - step: branch_a
    tool: { kind: http, url: "{{ api_a }}" }
    next:
      - step: join_point

  - step: branch_b
    tool: { kind: http, url: "{{ api_b }}" }
    next:
      - step: join_point

  - step: branch_c
    tool: { kind: http, url: "{{ api_c }}" }
    next:
      - step: join_point
```

**Key insight:** NoETL's `next:` array naturally expresses AND-split without special syntax.

#### Cross-DSL Comparison

<details>
<summary>BPMN 2.0</summary>

```xml
<parallelGateway id="fork" gatewayDirection="Diverging"/>
<sequenceFlow sourceRef="fork" targetRef="branch_a"/>
<sequenceFlow sourceRef="fork" targetRef="branch_b"/>
<sequenceFlow sourceRef="fork" targetRef="branch_c"/>
```
</details>

<details>
<summary>Argo Workflows</summary>

```yaml
dag:
  tasks:
    - name: start
      template: init
    - name: branch-a
      dependencies: [start]
      template: process-a
    - name: branch-b
      dependencies: [start]
      template: process-b
    - name: branch-c
      dependencies: [start]
      template: process-c
```
</details>

<details>
<summary>AWS Step Functions</summary>

```json
{
  "Type": "Parallel",
  "Branches": [
    { "StartAt": "BranchA", "States": {...} },
    { "StartAt": "BranchB", "States": {...} },
    { "StartAt": "BranchC", "States": {...} }
  ],
  "Next": "JoinPoint"
}
```
</details>

---

### Pattern 3: Synchronization (AND-Join)

> Multiple incoming paths must ALL complete before the next task starts.

**DSL Requirement:** Merge mechanism that waits for all prerequisites.

| DSL | Implementation | Complexity |
|-----|----------------|------------|
| **NoETL** | `case:` on `step.enter` checking `vars` | ✅ Explicit |
| **BPMN** | Parallel Gateway (converging) | ✅ Implicit |
| **Argo Workflows** | `dependencies:` listing all predecessors | ✅ Implicit |
| **GitHub Actions** | `needs: [job_a, job_b, job_c]` | ✅ Implicit |
| **Step Functions** | Automatic after `Parallel` state | ✅ Implicit |

#### NoETL Implementation

**Method 1: Explicit AND-Join via `case` conditions**

```yaml
workflow:
  - step: start
    tool: { kind: python, code: "result = {}" }
    next:
      - step: branch_a
      - step: branch_b

  - step: branch_a
    tool: { kind: http, url: "{{ api_a }}" }
    vars:
      branch_a_done: true
    next:
      - step: join_point

  - step: branch_b
    tool: { kind: http, url: "{{ api_b }}" }
    vars:
      branch_b_done: true
    next:
      - step: join_point

  - step: join_point
    case:
      - when: "{{ event.name == 'step.enter' and vars.branch_a_done and vars.branch_b_done }}"
        then:
          next:
            - step: after_join
    # Step waits until all conditions met (re-evaluated on each branch completion)
```

**Method 2: Sub-playbook (implicit synchronization)**

```yaml
- step: parallel_work
  tool:
    kind: playbook
    path: "workflows/parallel_branches"
  # Blocks until sub-playbook's 'end' step completes
  next:
    - step: after_join
```

**Analysis:** NoETL requires explicit `vars` tracking for AND-join within a single playbook. BPMN, Argo, and Step Functions provide implicit synchronization. This is a trade-off: explicit control vs. convenience.

#### Cross-DSL Comparison

<details>
<summary>BPMN 2.0</summary>

```xml
<!-- Converging parallel gateway - waits for ALL incoming flows -->
<parallelGateway id="join" gatewayDirection="Converging"/>
<sequenceFlow sourceRef="branch_a" targetRef="join"/>
<sequenceFlow sourceRef="branch_b" targetRef="join"/>
<sequenceFlow sourceRef="join" targetRef="after_join"/>
```
</details>

<details>
<summary>Argo Workflows</summary>

```yaml
dag:
  tasks:
    - name: after-join
      dependencies: [branch-a, branch-b, branch-c]  # Waits for ALL
      template: process-after
```
</details>

<details>
<summary>GitHub Actions</summary>

```yaml
jobs:
  after_join:
    needs: [branch_a, branch_b, branch_c]  # Waits for ALL
    runs-on: ubuntu-latest
```
</details>

---

### Pattern 4: Exclusive Choice (XOR-Split)

> Based on a condition, exactly ONE of several outgoing paths is chosen.

**DSL Requirement:** If-then-else or switch logic.

| DSL | Implementation | Example |
|-----|----------------|---------|
| **NoETL** | `case:` with `when:` conditions (first match) | ✅ Native |
| **BPMN** | Exclusive Gateway (diamond with X) | ✅ Native |
| **Argo Workflows** | `when:` expressions on tasks | ✅ Native |
| **GitHub Actions** | `if:` conditions on jobs/steps | ✅ Native |
| **Step Functions** | `Choice` state type | ✅ Native |

#### NoETL Implementation

```yaml
- step: evaluate_order
  tool:
    kind: python
    args:
      amount: "{{ workload.order_amount }}"
    code: |
      result = {
        'priority': 'high' if amount > 10000 else 'normal',
        'requires_approval': amount > 50000
      }
  case:
    - when: "{{ result.requires_approval }}"
      then:
        next:
          - step: manager_approval
    - when: "{{ result.priority == 'high' }}"
      then:
        next:
          - step: priority_processing
  next:
    - step: standard_processing  # Default path
```

**Key insight:** NoETL's `case:` evaluates conditions in order; first match wins (XOR semantics). The `next:` at step level serves as the default/fallback path.

#### Cross-DSL Comparison

<details>
<summary>BPMN 2.0</summary>

```xml
<exclusiveGateway id="decision"/>
<sequenceFlow sourceRef="decision" targetRef="approval">
  <conditionExpression>${amount > 50000}</conditionExpression>
</sequenceFlow>
<sequenceFlow sourceRef="decision" targetRef="priority">
  <conditionExpression>${priority == 'high'}</conditionExpression>
</sequenceFlow>
<sequenceFlow sourceRef="decision" targetRef="standard"/>  <!-- default -->
```
</details>

<details>
<summary>Argo Workflows</summary>

```yaml
dag:
  tasks:
    - name: approval
      when: "{{tasks.evaluate.outputs.result}} > 50000"
      template: approval-flow
    - name: priority
      when: "{{tasks.evaluate.outputs.priority}} == 'high'"
      template: priority-flow
    - name: standard
      when: "{{tasks.evaluate.outputs.priority}} == 'normal'"
      template: standard-flow
```
</details>

<details>
<summary>AWS Step Functions</summary>

```json
{
  "Type": "Choice",
  "Choices": [
    {
      "Variable": "$.amount",
      "NumericGreaterThan": 50000,
      "Next": "ManagerApproval"
    },
    {
      "Variable": "$.priority",
      "StringEquals": "high",
      "Next": "PriorityProcessing"
    }
  ],
  "Default": "StandardProcessing"
}
```
</details>

---

### Pattern 5: Simple Merge (XOR-Join)

> Multiple alternative paths converge without synchronization. Any single completion triggers the next step.

**DSL Requirement:** Multiple incoming arrows where ANY completion proceeds.

| DSL | Implementation | Notes |
|-----|----------------|-------|
| **NoETL** | Multiple steps with `next:` to same target | ✅ Implicit |
| **BPMN** | Exclusive Gateway (converging) or direct merge | ✅ Native |
| **Argo Workflows** | Single dependency (any one of OR'd tasks) | ⚠️ Requires `depends:` syntax |
| **GitHub Actions** | Not directly supported | ❌ Workaround needed |
| **Step Functions** | Multiple states with same `Next:` | ✅ Implicit |

#### NoETL Implementation

```yaml
workflow:
  - step: decision
    case:
      - when: "{{ workload.path == 'A' }}"
        then:
          next:
            - step: path_a
    next:
      - step: path_b  # Default

  - step: path_a
    tool: { kind: python, code: "result = {'from': 'A'}" }
    next:
      - step: merge_point  # XOR-Join: whichever path was taken continues

  - step: path_b
    tool: { kind: python, code: "result = {'from': 'B'}" }
    next:
      - step: merge_point  # Same target - first to arrive proceeds

  - step: merge_point
    tool:
      kind: python
      code: "result = {'merged': True}"
    next:
      - step: end
```

**Key insight:** XOR-join is implicit in NoETL. Since only ONE path was activated (from XOR-split), when it reaches the merge point, it simply proceeds. No special construct needed.

---

## Advanced Patterns (Modern Minimum)

### Pattern 6: Multi-Choice (OR-Split / Inclusive Gateway)

> Based on conditions, ONE OR MORE outgoing paths are chosen.

**DSL Requirement:** Evaluate ALL conditions; take ALL paths where condition is TRUE.

| DSL | Implementation | Status |
|-----|----------------|--------|
| **NoETL** | ❌ Not native (workaround: fork + guards) | **Gap - Phase 1** |
| **BPMN** | Inclusive Gateway (diamond with O) | ✅ Native |
| **Argo Workflows** | `when:` on multiple parallel tasks | ✅ Native |
| **GitHub Actions** | `if:` on multiple parallel jobs | ✅ Native |
| **Step Functions** | ❌ Not native (workaround: Parallel + conditions) | Gap |

#### NoETL Current Workaround

```yaml
# Fork unconditionally, then guard each branch
- step: dispatch
  next:
    - step: check_high_value
    - step: check_needs_audit
    - step: check_notify

- step: check_high_value
  case:
    - when: "{{ workload.amount > 10000 }}"
      then:
        next:
          - step: high_value_handler
  next:
    - step: or_join  # Skip if condition false

- step: check_needs_audit
  case:
    - when: "{{ workload.audit_required }}"
      then:
        next:
          - step: audit_logger
  next:
    - step: or_join

# ... and so on
```

#### NoETL Proposed Enhancement (Phase 1)

```yaml
- step: decision
  next:
    mode: inclusive  # Evaluate ALL conditions
    branches:
      - when: "{{ workload.amount > 10000 }}"
        step: high_value_handler
      - when: "{{ workload.audit_required }}"
        step: audit_logger
      - when: "{{ workload.notify_customer }}"
        step: send_notification
    default: skip_all
```

See [DSL Enhancement Phases](./dsl_enhancement_phases.md) for detailed design.

---

### Pattern 7: Multi-Instance (Parallel For-Each)

> Execute a task N times, potentially in parallel.

**DSL Requirement:** Loop over collection with parallel or sequential execution.

| DSL | Implementation | Status |
|-----|----------------|--------|
| **NoETL** | `loop:` with `mode: parallel/sequential` | ✅ Native |
| **BPMN** | Multi-Instance Activity marker | ✅ Native |
| **Argo Workflows** | `withItems:` or `withParam:` | ✅ Native |
| **GitHub Actions** | `strategy.matrix` | ✅ Native |
| **Step Functions** | `Map` state type | ✅ Native |

#### NoETL Implementation

```yaml
- step: process_all_items
  loop:
    in: "{{ workload.items }}"
    iterator: item
    mode: parallel  # Or 'sequential' for one-at-a-time
  tool:
    kind: http
    method: POST
    url: "{{ api_url }}/process"
    body:
      id: "{{ item.id }}"
      data: "{{ item.data }}"
  next:
    - step: aggregate_results
```

#### Cross-DSL Comparison

<details>
<summary>BPMN 2.0</summary>

```xml
<userTask id="processItem" name="Process Item">
  <multiInstanceLoopCharacteristics isSequential="false">
    <loopCardinality>${items.size()}</loopCardinality>
  </multiInstanceLoopCharacteristics>
</userTask>
```
</details>

<details>
<summary>Argo Workflows</summary>

```yaml
- name: process-items
  template: process-single
  withParam: "{{workflow.parameters.items}}"
  arguments:
    parameters:
      - name: item
        value: "{{item}}"
```
</details>

<details>
<summary>GitHub Actions</summary>

```yaml
jobs:
  process:
    strategy:
      matrix:
        item: [item1, item2, item3]
    steps:
      - run: process ${{ matrix.item }}
```
</details>

<details>
<summary>AWS Step Functions</summary>

```json
{
  "Type": "Map",
  "ItemsPath": "$.items",
  "Iterator": {
    "StartAt": "ProcessItem",
    "States": {
      "ProcessItem": { "Type": "Task", "End": true }
    }
  }
}
```
</details>

---

### Pattern 8: Deferred Choice (Event-Based Gateway)

> A choice made not by data, but by external events. "Wait for payment OR cancellation - whichever comes first."

**DSL Requirement:** Wait for first of multiple possible events.

| DSL | Implementation | Status |
|-----|----------------|--------|
| **NoETL** | ⚠️ Polling via `retry:` | **Gap - Phase 3** |
| **BPMN** | Event-Based Gateway | ✅ Native |
| **Argo Workflows** | ❌ Not native | Gap |
| **GitHub Actions** | `workflow_dispatch` + conditions | ⚠️ Partial |
| **Step Functions** | `.waitForTaskToken` + callback | ✅ Native |

#### NoETL Current Workaround

```yaml
# Poll for either event
- step: wait_for_event
  tool:
    kind: http
    url: "{{ api }}/events?order_id={{ order_id }}"
  retry:
    max_attempts: 60
    delay: 10
    when: "{{ result.event_type not in ['payment', 'cancellation'] }}"
  case:
    - when: "{{ result.event_type == 'payment' }}"
      then:
        next:
          - step: process_payment
    - when: "{{ result.event_type == 'cancellation' }}"
      then:
        next:
          - step: handle_cancellation
```

#### NoETL Proposed Enhancement (Phase 3)

```yaml
- step: wait_for_response
  event_gateway:
    - message:
        name: "payment_received"
        correlation: { order_id: "{{ order_id }}" }
        then: process_payment
    - message:
        name: "order_cancelled"
        correlation: { order_id: "{{ order_id }}" }
        then: handle_cancellation
    - timer:
        duration: 24h
        then: escalate_timeout
```

---

### Pattern 9: Arbitrary Cycles

> Loop back to an earlier point without structured While/For loops.

**DSL Requirement:** Backward control flow edges.

| DSL | Implementation | Status |
|-----|----------------|--------|
| **NoETL** | `next:` pointing to earlier step | ✅ Native |
| **BPMN** | Sequence Flow to earlier activity | ✅ Native |
| **Argo Workflows** | ❌ DAG only (no cycles) | Gap |
| **GitHub Actions** | ❌ Not supported | Gap |
| **Step Functions** | `Next:` to earlier state | ✅ Native |

#### NoETL Implementation

```yaml
workflow:
  - step: start
    tool: { kind: python, code: "result = {'counter': 0}" }
    next:
      - step: process

  - step: process
    tool:
      kind: python
      args:
        count: "{{ vars.counter | default(0) }}"
      code: |
        result = {'counter': count + 1, 'done': count >= 10}
    vars:
      counter: "{{ result.counter }}"
    case:
      - when: "{{ not result.done }}"
        then:
          next:
            - step: process  # Backward jump - arbitrary cycle!
    next:
      - step: end  # Exit when done
```

**Key insight:** NoETL's `next:` can point to ANY step, enabling arbitrary cycles. This is more flexible than structured loops and supports complex retry/recovery patterns.

---

## Summary Matrix

### Basic Control Flow Patterns

| Pattern | NoETL | BPMN | Argo | GitHub Actions | Step Functions |
|---------|-------|------|------|----------------|----------------|
| **1. Sequence** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **2. AND-Split** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **3. AND-Join** | ✅* | ✅ | ✅ | ✅ | ✅ |
| **4. XOR-Split** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **5. XOR-Join** | ✅ | ✅ | ✅ | ⚠️ | ✅ |

*NoETL AND-Join requires explicit `vars` tracking or sub-playbook pattern

### Advanced Patterns

| Pattern | NoETL | BPMN | Argo | GitHub Actions | Step Functions |
|---------|-------|------|------|----------------|----------------|
| **6. OR-Split (Inclusive)** | ❌* | ✅ | ✅ | ✅ | ❌ |
| **7. Multi-Instance** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **8. Deferred Choice** | ⚠️ | ✅ | ❌ | ⚠️ | ✅ |
| **9. Arbitrary Cycles** | ✅ | ✅ | ❌ | ❌ | ✅ |

*Planned for [Phase 1](./dsl_enhancement_phases.md)

### NoETL Competitive Position

| Strength | Details |
|----------|---------|
| **Arbitrary Cycles** | Unlike Argo/GitHub Actions, supports backward jumps |
| **Multi-Instance** | Full parallel/sequential loop support |
| **Event-Driven** | `case:` evaluation on `step.enter`, `call.done`, `call.error` |
| **NATS Infrastructure** | JetStream for messaging, KV for state |

| Gap | Mitigation | Phase |
|-----|------------|-------|
| **Inclusive Gateway** | Fork + guards workaround | Phase 1 |
| **Deferred Choice** | Polling via `retry:` | Phase 3 |
| **Timer Events** | External scheduler | Phase 2 |

---

## Conclusion

NoETL DSL covers **all 5 Basic Control Flow Patterns** required for a functional workflow engine:

1. ✅ **Sequence** - `next:` with single step
2. ✅ **AND-Split** - `next:` with multiple steps
3. ✅ **AND-Join** - `case:` on `step.enter` checking `vars`
4. ✅ **XOR-Split** - `case:` with `when:` conditions
5. ✅ **XOR-Join** - Implicit (multiple paths to same step)

For **Advanced Patterns**, NoETL excels at:
- **Arbitrary Cycles** (backward `next:`)
- **Multi-Instance** (`loop:` with modes)

Gaps planned for closure:
- **Inclusive Gateway** → [Phase 1](./dsl_enhancement_phases.md)
- **Deferred Choice** → [Phase 3](./dsl_enhancement_phases.md)
- **Timer Events** → [Phase 2](./dsl_enhancement_phases.md)

---

## References

- [Workflow Patterns](http://www.workflowpatterns.com/) - Van der Aalst et al.
- [BPMN 2.0 Specification](https://www.omg.org/spec/BPMN/2.0/)
- [Argo Workflows Documentation](https://argoproj.github.io/argo-workflows/)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [AWS Step Functions Developer Guide](https://docs.aws.amazon.com/step-functions/latest/dg/)
- [NoETL DSL Enhancement Phases](./dsl_enhancement_phases.md)
- [NoETL DSL Analysis](./dsl_analysis_and_evaluation.md)
