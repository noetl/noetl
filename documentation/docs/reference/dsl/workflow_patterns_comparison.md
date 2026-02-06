---
sidebar_position: 4
title: Workflow Patterns Comparison
description: Analysis of NoETL DSL against Van der Aalst Workflow Patterns with cross-DSL comparison
---

# Workflow Patterns Comparison

This document analyzes the NoETL DSL against the canonical Workflow Patterns identified by Van der Aalst et al., comparing implementation approaches across major workflow DSLs: BPMN 2.0, Argo Workflows, GitHub Actions, and AWS Step Functions.

**Note:** NoETL examples below use the **Canonical v10** form:
- Routing uses `step.next` as a router object (`next.spec` + `next.arcs[]`)
- Step bodies are ordered task pipelines (`step.tool` as a labeled list)
- Cross-step state uses `ctx` (not legacy `vars`)

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
| **NoETL** | `step.next.arcs[]` (exclusive router) | ✅ Native |
| **BPMN** | Sequence Flow arrow | ✅ Native |
| **Argo Workflows** | `dependencies:` array | ✅ Native |
| **GitHub Actions** | `needs:` array | ✅ Native |
| **Step Functions** | `Next:` field | ✅ Native |

#### NoETL Implementation

```yaml
workflow:
  - step: task_a
    tool:
      - compute:
          kind: python
          code: |
            result = {"value": 42}
          spec:
            policy:
              rules:
                - else:
                    then:
                      do: break
                      set_ctx:
                        value: "{{ outcome.result.value }}"
    next:
      spec: { mode: exclusive }
      arcs:
        - step: task_b
          when: "{{ event.name == 'step.done' }}"

  - step: task_b
    tool:
      - process:
          kind: python
          args:
            input: "{{ ctx.value }}"
          code: |
            result = {"processed": input * 2}
    next:
      spec: { mode: exclusive }
      arcs:
        - step: end
          when: "{{ event.name == 'step.done' }}"

  - step: end
    tool:
      - done:
          kind: noop
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
| **NoETL** | `next.spec.mode: inclusive` with multiple arcs | ✅ Native |
| **BPMN** | Parallel Gateway (diamond with +) | ✅ Native |
| **Argo Workflows** | Multiple tasks without dependencies | ✅ Native |
| **GitHub Actions** | Multiple jobs without `needs:` | ✅ Native |
| **Step Functions** | `Parallel` state type | ✅ Native |

#### NoETL Implementation

```yaml
workflow:
  - step: start
    tool:
      - ready:
          kind: noop
    next:
      spec: { mode: inclusive }
      arcs:
        - step: branch_a  # All three execute in parallel
          when: "{{ event.name == 'step.done' }}"
        - step: branch_b
          when: "{{ event.name == 'step.done' }}"
        - step: branch_c
          when: "{{ event.name == 'step.done' }}"

  - step: branch_a
    tool:
      - call:
          kind: http
          url: "{{ workload.api_a }}"
    next:
      spec: { mode: exclusive }
      arcs:
        - step: join_point
          when: "{{ event.name == 'step.done' }}"

  - step: branch_b
    tool:
      - call:
          kind: http
          url: "{{ workload.api_b }}"
    next:
      spec: { mode: exclusive }
      arcs:
        - step: join_point
          when: "{{ event.name == 'step.done' }}"

  - step: branch_c
    tool:
      - call:
          kind: http
          url: "{{ workload.api_c }}"
    next:
      spec: { mode: exclusive }
      arcs:
        - step: join_point
          when: "{{ event.name == 'step.done' }}"
```

**Key insight:** NoETL's `next.spec.mode: inclusive` naturally expresses AND-split without special syntax.

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
| **NoETL** | Step admission gate (`step.spec.policy.admit`) checking `ctx` | ✅ Pattern-based |
| **BPMN** | Parallel Gateway (converging) | ✅ Implicit |
| **Argo Workflows** | `dependencies:` listing all predecessors | ✅ Implicit |
| **GitHub Actions** | `needs: [job_a, job_b, job_c]` | ✅ Implicit |
| **Step Functions** | Automatic after `Parallel` state | ✅ Implicit |

#### NoETL Implementation

**Method 1: Explicit AND-Join via step admission**

```yaml
workflow:
  - step: start
    tool:
      - ready:
          kind: noop
    next:
      spec: { mode: inclusive }
      arcs:
        - step: branch_a
          when: "{{ event.name == 'step.done' }}"
        - step: branch_b
          when: "{{ event.name == 'step.done' }}"

  - step: branch_a
    tool:
      - call:
          kind: http
          url: "{{ workload.api_a }}"
          spec:
            policy:
              rules:
                - when: "{{ outcome.status == 'error' }}"
                  then: { do: fail }
                - else:
                    then:
                      do: break
                      set_ctx: { branch_a_done: true }
    next:
      spec: { mode: exclusive }
      arcs:
        - step: join_point
          when: "{{ event.name == 'step.done' }}"

  - step: branch_b
    tool:
      - call:
          kind: http
          url: "{{ workload.api_b }}"
          spec:
            policy:
              rules:
                - when: "{{ outcome.status == 'error' }}"
                  then: { do: fail }
                - else:
                    then:
                      do: break
                      set_ctx: { branch_b_done: true }
    next:
      spec: { mode: exclusive }
      arcs:
        - step: join_point
          when: "{{ event.name == 'step.done' }}"

  - step: join_point
    spec:
      policy:
        admit:
          rules:
            - when: "{{ ctx.branch_a_done == true and ctx.branch_b_done == true }}"
              then: { allow: true }
            - else:
                then: { allow: false }
    tool:
      - latch:
          kind: noop
    next:
      spec: { mode: exclusive }
      arcs:
        - step: after_join
          when: "{{ event.name == 'step.done' }}"
```

**Note:** AND-join is **pattern-based**. In practice, runtimes typically add token dedupe/latching to ensure `join_point` runs exactly once under concurrent arrivals (for example by requiring/setting a `ctx.join_fired` latch).

**Method 2: Sub-playbook (implicit synchronization)**

```yaml
- step: parallel_work
  tool:
    - run:
        kind: playbook
        path: "workflows/parallel_branches"
  # Blocks until sub-playbook's 'end' step completes
  next:
    spec: { mode: exclusive }
    arcs:
      - step: after_join
        when: "{{ event.name == 'step.done' }}"
```

**Analysis:** NoETL requires explicit state tracking (typically via `ctx`) and admission gating for AND-join within a single playbook. BPMN, Argo, and Step Functions provide implicit synchronization. This is a trade-off: explicit control vs. convenience.

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
| **NoETL** | `next.spec.mode: exclusive` with guarded arcs | ✅ Native |
| **BPMN** | Exclusive Gateway (diamond with X) | ✅ Native |
| **Argo Workflows** | `when:` expressions on tasks | ✅ Native |
| **GitHub Actions** | `if:` conditions on jobs/steps | ✅ Native |
| **Step Functions** | `Choice` state type | ✅ Native |

#### NoETL Implementation

```yaml
- step: evaluate_order
  tool:
    - evaluate:
        kind: python
        args:
          amount: "{{ workload.order_amount }}"
        code: |
          result = {
            "priority": "high" if amount > 10000 else "normal",
            "requires_approval": amount > 50000
          }
        spec:
          policy:
            rules:
              - else:
                  then:
                    do: break
                    set_ctx:
                      priority: "{{ outcome.result.priority }}"
                      requires_approval: "{{ outcome.result.requires_approval }}"
  next:
    spec: { mode: exclusive }
    arcs:
      - step: manager_approval
        when: "{{ event.name == 'step.done' and ctx.requires_approval == true }}"
      - step: priority_processing
        when: "{{ event.name == 'step.done' and ctx.priority == 'high' }}"
      - step: standard_processing  # Default path (fallback)
        when: "{{ event.name == 'step.done' }}"
```

**Key insight:** NoETL's `next.spec.mode: exclusive` evaluates arcs in YAML order; first match wins (XOR semantics). A final unconditional arc provides a default/fallback path.

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
    tool:
      - nop:
          kind: noop
    next:
      spec: { mode: exclusive }
      arcs:
        - step: path_a
          when: "{{ event.name == 'step.done' and workload.path == 'A' }}"
        - step: path_b  # Default
          when: "{{ event.name == 'step.done' }}"

  - step: path_a
    tool:
      - run:
          kind: python
          code: |
            result = {"from": "A"}
    next:
      spec: { mode: exclusive }
      arcs:
        - step: merge_point  # XOR-Join: whichever path was taken continues
          when: "{{ event.name == 'step.done' }}"

  - step: path_b
    tool:
      - run:
          kind: python
          code: |
            result = {"from": "B"}
    next:
      spec: { mode: exclusive }
      arcs:
        - step: merge_point  # Same target - first to arrive proceeds
          when: "{{ event.name == 'step.done' }}"

  - step: merge_point
    tool:
      - run:
          kind: python
          code: |
            result = {"merged": True}
    next:
      spec: { mode: exclusive }
      arcs:
        - step: end
          when: "{{ event.name == 'step.done' }}"
```

**Key insight:** XOR-join is implicit in NoETL. Since only ONE path was activated (from XOR-split), when it reaches the merge point, it simply proceeds. No special construct needed.

---

## Advanced Patterns (Modern Minimum)

### Pattern 6: Multi-Choice (OR-Split / Inclusive Gateway)

> Based on conditions, ONE OR MORE outgoing paths are chosen.

**DSL Requirement:** Evaluate ALL conditions; take ALL paths where condition is TRUE.

| DSL | Implementation | Status |
|-----|----------------|--------|
| **NoETL** | `next.spec.mode: inclusive` with guarded arcs | ✅ Native |
| **BPMN** | Inclusive Gateway (diamond with O) | ✅ Native |
| **Argo Workflows** | `when:` on multiple parallel tasks | ✅ Native |
| **GitHub Actions** | `if:` on multiple parallel jobs | ✅ Native |
| **Step Functions** | ❌ Not native (workaround: Parallel + conditions) | Gap |

#### NoETL Implementation

```yaml
- step: decision
  tool:
    - nop:
        kind: noop
  next:
    spec: { mode: inclusive }
    arcs:
      - step: high_value_handler
        when: "{{ event.name == 'step.done' and workload.amount > 10000 }}"
      - step: audit_logger
        when: "{{ event.name == 'step.done' and workload.audit_required }}"
      - step: send_notification
        when: "{{ event.name == 'step.done' and workload.notify_customer }}"
```
**Note:** This pattern describes the split only. Joining/final aggregation is typically modeled via explicit admission gating (Pattern 3) or a sub-playbook barrier.

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
    spec:
      mode: parallel  # Or 'sequential' for one-at-a-time
  tool:
    - process:
        kind: http
        method: POST
        url: "{{ workload.api_url }}/process"
        body:
          id: "{{ iter.item.id }}"
          data: "{{ iter.item.data }}"
  next:
    spec: { mode: exclusive }
    arcs:
      - step: aggregate_results
        when: "{{ event.name == 'loop.done' }}"
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
| **NoETL** | ⚠️ Polling via task policy (`do: retry`) | Pattern-based |
| **BPMN** | Event-Based Gateway | ✅ Native |
| **Argo Workflows** | ❌ Not native | Gap |
| **GitHub Actions** | `workflow_dispatch` + conditions | ⚠️ Partial |
| **Step Functions** | `.waitForTaskToken` + callback | ✅ Native |

#### NoETL Current Workaround

```yaml
- step: wait_for_event
  tool:
    - poll:
        kind: http
        url: "{{ workload.api }}/events?order_id={{ workload.order_id }}"
        spec:
          policy:
            rules:
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - when: "{{ outcome.result.data.event_type not in ['payment','cancellation'] }}"
                then: { do: retry, attempts: 60, delay: 10 }
              - else:
                  then:
                    do: break
                    set_ctx:
                      event_type: "{{ outcome.result.data.event_type }}"
  next:
    spec: { mode: exclusive }
    arcs:
      - step: process_payment
        when: "{{ event.name == 'step.done' and ctx.event_type == 'payment' }}"
      - step: handle_cancellation
        when: "{{ event.name == 'step.done' and ctx.event_type == 'cancellation' }}"
```

#### NoETL Proposed Enhancement (future)

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
| **NoETL** | `next.arcs[]` pointing to an earlier step | ✅ Native |
| **BPMN** | Sequence Flow to earlier activity | ✅ Native |
| **Argo Workflows** | ❌ DAG only (no cycles) | Gap |
| **GitHub Actions** | ❌ Not supported | Gap |
| **Step Functions** | `Next:` to earlier state | ✅ Native |

#### NoETL Implementation

```yaml
workflow:
  - step: start
    tool:
      - init:
          kind: python
          code: |
            result = {"counter": 0, "done": False}
          spec:
            policy:
              rules:
                - else:
                    then:
                      do: break
                      set_ctx:
                        counter: "{{ outcome.result.counter }}"
                        done: "{{ outcome.result.done }}"
    next:
      spec: { mode: exclusive }
      arcs:
        - step: process
          when: "{{ event.name == 'step.done' }}"

  - step: process
    tool:
      - tick:
          kind: python
          args:
            count: "{{ ctx.counter | default(0) }}"
          code: |
            next_count = int(count) + 1
            result = {"counter": next_count, "done": next_count >= 10}
          spec:
            policy:
              rules:
                - else:
                    then:
                      do: break
                      set_ctx:
                        counter: "{{ outcome.result.counter }}"
                        done: "{{ outcome.result.done }}"
    next:
      spec: { mode: exclusive }
      arcs:
        - step: process  # Backward edge - arbitrary cycle
          when: "{{ event.name == 'step.done' and ctx.done != true }}"
        - step: end  # Exit when done
          when: "{{ event.name == 'step.done' and ctx.done == true }}"

  - step: end
    tool:
      - done:
          kind: noop
```

**Key insight:** NoETL's `next.arcs[]` can point to ANY step, enabling arbitrary cycles. This is more flexible than structured loops and supports complex retry/recovery patterns.

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

*NoETL AND-Join typically requires explicit `ctx` tracking + admission gating (or a sub-playbook barrier)

### Advanced Patterns

| Pattern | NoETL | BPMN | Argo | GitHub Actions | Step Functions |
|---------|-------|------|------|----------------|----------------|
| **6. OR-Split (Inclusive)** | ✅ | ✅ | ✅ | ✅ | ❌ |
| **7. Multi-Instance** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **8. Deferred Choice** | ⚠️ | ✅ | ❌ | ⚠️ | ✅ |
| **9. Arbitrary Cycles** | ✅ | ✅ | ❌ | ❌ | ✅ |

### NoETL Competitive Position

| Strength | Details |
|----------|---------|
| **Arbitrary Cycles** | Unlike Argo/GitHub Actions, supports backward jumps |
| **Multi-Instance** | Full parallel/sequential loop support |
| **Event-Driven** | Server routing on boundary events (`step.done`/`step.failed`/`loop.done`) plus task policies |
| **NATS Infrastructure** | JetStream for messaging, KV for state |

| Gap | Mitigation |
|-----|------------|
| **Deferred Choice** | Polling via task policy (`do: retry`) |
| **Timer Events** | External scheduler |

---

## Conclusion

NoETL DSL covers **all 5 Basic Control Flow Patterns** required for a functional workflow engine:

1. ✅ **Sequence** - `next.arcs[]` with a single target
2. ✅ **AND-Split** - `next.spec.mode: inclusive` with multiple arcs
3. ✅ **AND-Join** - admission gating (`step.spec.policy.admit`) checking `ctx` (pattern-based)
4. ✅ **XOR-Split** - `next.spec.mode: exclusive` with guarded arcs
5. ✅ **XOR-Join** - Implicit (multiple paths to same step)

For **Advanced Patterns**, NoETL excels at:
- **Arbitrary Cycles** (backward `next.arcs[]`)
- **Multi-Instance** (`loop:` with modes)
- **OR-Split** (`next.spec.mode: inclusive`)

Remaining gaps are mostly around **event-based waiting** (deferred choice) and **timers/signals**, which are typically implemented via polling patterns or external schedulers until native primitives are added.

---

## References

- [Workflow Patterns](http://www.workflowpatterns.com/) - Van der Aalst et al.
- [BPMN 2.0 Specification](https://www.omg.org/spec/BPMN/2.0/)
- [Argo Workflows Documentation](https://argoproj.github.io/argo-workflows/)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [AWS Step Functions Developer Guide](https://docs.aws.amazon.com/step-functions/latest/dg/)
- [NoETL DSL Analysis](./dsl_analysis_and_evaluation.md)
