---
sidebar_position: 20
title: DSL Analysis and Evaluation
description: Comprehensive analysis of NoETL DSL for Turing-completeness, BPMN 2.0 coverage, and design recommendations
---

# NoETL DSL Analysis and Evaluation

This document provides a formal analysis of the NoETL Playbook DSL, evaluating its computational completeness, coverage against industry-standard BPMN 2.0, visualization potential, and recommendations for consistency and future-proofing.

---

## 1. DSL Control Flow Model

### 1.1 Core Execution Semantics

The NoETL DSL uses an **event-driven control flow model** where:

1. **Steps** are the primary execution units
2. **`case`** blocks evaluate on every state change
3. **`tool`** executes the step's action
4. **`loop`** repeats tool execution over a collection
5. **`next`** determines routing to subsequent steps
6. **`sink`** persists results to storage

### 1.2 The `case` Block: Central Event Handler

The `case` block is the **central conditional evaluation mechanism**. It is evaluated:

- When execution **enters** the step
- On **every state change** during step execution
- After **tool completion** (success or error)
- After **loop iteration** completion
- After **retry attempt** completion

```yaml
case:
  - when: "{{ event.name == 'step.enter' }}"
    then:
      set:
        ctx:
          initialized: true
  
  - when: "{{ event.name == 'call.done' and response.status_code == 200 }}"
    then:
      sink:
        tool:
          kind: postgres
          table: results
      next:
        - step: success_handler
  
  - when: "{{ event.name == 'call.error' }}"
    then:
      retry:
        max_attempts: 3
        backoff_multiplier: 2.0
```

### 1.3 Step-Level `next` and `sink` as Syntactic Sugar

The `next:` and `sink:` attributes at the step level are **syntactic sugar** for implicit `case` conditions:

```yaml
# SHORTHAND FORM:
- step: fetch_data
  tool:
    kind: http
    url: "{{ api_url }}"
  sink:
    tool:
      kind: postgres
      table: raw_data
  next:
    - step: process_data
```

This is equivalent to:

```yaml
# EXPANDED FORM (implicit else condition):
- step: fetch_data
  tool:
    kind: http
    url: "{{ api_url }}"
  case:
    # ... any explicit when/then conditions ...
    
    # Implicit else condition for step-level sink and next:
    - when: "{{ event.name == 'step.exit' and response is defined }}"
      then:
        sink:
          tool:
            kind: postgres
            table: raw_data
        next:
          - step: process_data
```

**Key point:** If no `case` block is defined, `next` and `sink` are evaluated as the **default/else** condition when the step completes successfully.

### 1.4 Parallel Forking via `next` Lists

The `next:` clause inside `case` → `when` → `then` (or at step level) can specify **multiple steps to fork in parallel**:

```yaml
case:
  - when: "{{ event.name == 'step.exit' }}"
    then:
      next:
        - step: process_branch_a
        - step: process_branch_b
        - step: process_branch_c
```

When `next:` contains multiple steps:
- All listed steps are **launched in parallel**
- Each step receives the current context
- This creates a **fork** in the workflow graph

**Note:** Parallel convergence (join) is handled by the implicit routing to `end` step or explicit routing where multiple paths converge.

### 1.5 Loop: Repeated Tool Execution

The `loop:` attribute **repeats the step's tool execution** over a collection:

```yaml
- step: process_items
  loop:
    in: "{{ workload.items }}"
    iterator: item
    mode: sequential | parallel
  tool:
    kind: python
    args:
      current_item: "{{ item }}"
    code: |
      result = {"processed": current_item["id"]}
```

**Semantics:**
- `loop` calls the step's `tool` **N times** (once per collection element)
- `mode: sequential` - executes iterations one at a time, in order
- `mode: parallel` - executes all iterations concurrently
- The `iterator` variable is bound to the current element in each iteration
- `case` blocks evaluate **per iteration** (can trigger per-iteration sinks)

### 1.6 Retry within Case: Loop-Until Equivalent

The `retry:` inside a `case` → `then` block functions as a **loop with until condition**:

```yaml
case:
  - when: "{{ event.name == 'call.error' and error.status in [429, 500, 502, 503] }}"
    then:
      retry:
        max_attempts: 5
        initial_delay: 1.0
        backoff_multiplier: 2.0
  
  - when: "{{ event.name == 'call.done' and response.data.status == 'pending' }}"
    then:
      retry:
        max_attempts: 100
        initial_delay: 5.0
        stop_when: "{{ response.data.status == 'complete' }}"
```

**Retry in `case` is equivalent to:**
- **Error retry:** Re-execute tool until success or max attempts
- **Success retry (polling):** Re-execute tool until `stop_when` condition is true
- **Pagination:** Re-execute with modified parameters until no more pages

---

## 2. Turing-Completeness Analysis

### 2.1 Requirements for Turing-Completeness

A language is Turing-complete if it can simulate a Turing machine, requiring:

1. **Conditional branching** (if-then-else / goto)
2. **Unbounded iteration** (loops)
3. **Read/write to unbounded storage**

### 2.2 NoETL DSL Assessment

| Requirement | Supported | Implementation |
|-------------|-----------|----------------|
| **Conditional branching (if-then)** | ✅ Yes | `case: when:` blocks with Jinja2 predicates |
| **Goto/jump** | ✅ Yes | `next:` clauses route to arbitrary named steps |
| **Unbounded iteration** | ⚠️ Bounded | `loop:` and `retry:` have `max_attempts` limits |
| **Read/write storage** | ✅ Yes | `vars:` persistence, `sink:` to databases |
| **Arbitrary computation** | ✅ Yes | `tool: kind: python` executes arbitrary Python code |

### 2.3 If-Then-Goto Equivalence

The DSL provides full if-then-else-goto through `case` blocks:

```yaml
# IF condition THEN goto step_a ELSE goto step_b
case:
  - when: "{{ condition }}"
    then:
      next:
        - step: step_a
next:
  - step: step_b  # Implicit else (fallback)
```

### 2.4 Loop Equivalence

Loops are supported through:

1. **Collection iteration** (`loop:`)
2. **Conditional retry** (`retry:` with `stop_when`)
3. **Backward jumps** (`next:` pointing to earlier steps)
4. **Recursive sub-playbooks** (`tool: kind: playbook`)

```yaml
# While-loop equivalent via backward jump:
- step: loop_body
  tool: { ... }
  case:
    - when: "{{ continue_condition }}"
      then:
        next:
          - step: loop_body  # Jump back (loop)
  next:
    - step: after_loop  # Exit loop
```

### 2.5 Verdict: Effectively Turing-Complete

The NoETL DSL achieves **practical Turing-completeness** through:
- Conditional branching via `case`
- Arbitrary jumps via `next`
- Bounded loops via `loop` and `retry`
- Unbounded computation via backward jumps and recursive playbooks
- State storage via `vars` and `sink`

**Caveat:** `max_attempts` limits are a practical safeguard; theoretically unbounded computation is possible via step recursion.

---

## 3. BPMN 2.0 Coverage Analysis

### 3.1 Feature Comparison Matrix

| BPMN 2.0 Feature | NoETL DSL Status | Implementation |
|------------------|------------------|----------------|
| **Sequential execution** | ✅ Full | `next:` with single step |
| **Parallel execution (fork)** | ✅ Full | `next:` with multiple steps |
| **Parallel join** | ⚠️ Implicit | Convergence at common step (typically `end`) |
| **Exclusive gateway (XOR)** | ✅ Full | `case:` with multiple `when:` (first match wins) |
| **Inclusive gateway (OR)** | ❌ Missing | No mechanism for multiple conditional branches |
| **Sequential loops** | ✅ Full | `loop: mode: sequential` |
| **Parallel loops (multi-instance)** | ✅ Full | `loop: mode: parallel` |
| **Conditional branching** | ✅ Full | `case: when: then:` |
| **Context/data passing** | ✅ Full | `args:`, `vars:`, `workload` |
| **Human tasks** | ❌ Missing | No user task construct |
| **Timer events** | ❌ Missing | No timer start/intermediate events |
| **Signal/message events** | ⚠️ Partial | Polling via retry; no true wait-for-event |
| **Error boundary events** | ✅ Full | `case:` with `event.name == 'call.error'` |
| **Compensation handlers** | ❌ Missing | No rollback mechanism |
| **Subprocess (embedded)** | ✅ Full | `tool: kind: playbook` |
| **Call activity (reusable)** | ✅ Full | `workbook` tasks and sub-playbooks |

### 3.2 Sequential Execution

**Fully supported** via `next:` with a single step:

```yaml
- step: step_a
  tool: { kind: python, code: "..." }
  next:
    - step: step_b

- step: step_b
  tool: { kind: http, ... }
  next:
    - step: step_c
```

### 3.3 Parallel Execution (Fork)

**Fully supported** via `next:` with multiple steps:

```yaml
- step: start
  tool: { kind: python, code: "result = {'ready': True}" }
  next:
    - step: branch_a    # All three start in parallel
    - step: branch_b
    - step: branch_c
```

This creates a **fork** where all listed steps execute concurrently.

### 3.4 Parallel Join (Synchronization)

**Implicit support** through convergence at a common step:

```yaml
- step: branch_a
  tool: { ... }
  next:
    - step: join_point

- step: branch_b
  tool: { ... }
  next:
    - step: join_point

- step: join_point
  tool: { ... }  # Waits for all incoming branches
```

**Note:** The server tracks parallel execution paths and the join step executes when all incoming paths complete.

### 3.5 Loops with Sequential Execution

**Fully supported:**

```yaml
- step: process_items
  loop:
    in: "{{ workload.records }}"
    iterator: record
    mode: sequential
  tool:
    kind: python
    args:
      item: "{{ record }}"
    code: |
      result = {"processed_id": item["id"]}
```

### 3.6 Parallel Loops (Multi-Instance)

**Fully supported:**

```yaml
- step: parallel_fetch
  loop:
    in: "{{ workload.urls }}"
    iterator: url
    mode: parallel
  tool:
    kind: http
    method: GET
    url: "{{ url }}"
```

### 3.7 Conditional Jump (If-Then-Goto)

**Fully supported** via `case:` blocks:

```yaml
case:
  - when: "{{ response.data.type == 'premium' }}"
    then:
      next:
        - step: premium_handler
  
  - when: "{{ response.data.type == 'standard' }}"
    then:
      next:
        - step: standard_handler

next:
  - step: default_handler  # Else/fallback
```

### 3.8 Carrying Context Between Tasks

**Fully supported** via multiple mechanisms:

```yaml
# 1. Via args (step-to-step)
- step: step_a
  tool: { ... }
  next:
    - step: step_b
      args:
        input_data: "{{ step_a.result }}"

# 2. Via vars (persisted across steps)
- step: fetch_user
  tool: { kind: postgres, query: "SELECT * FROM users LIMIT 1" }
  vars:
    user_id: "{{ result[0].id }}"
    email: "{{ result[0].email }}"

- step: send_email
  tool:
    kind: http
    body:
      to: "{{ vars.email }}"
      user_id: "{{ vars.user_id }}"

# 3. Via workload (global scope)
workload:
  api_key: "{{ env.API_KEY }}"
  batch_size: 100
```

### 3.9 Human Interaction Tasks

**Not currently supported.** Missing constructs for:
- User task (wait for human action/approval)
- Manual task (external to workflow engine)

**Workaround:** Use external webhook + polling pattern.

### 3.10 Waiting for External Events

**Partially supported** via polling:

```yaml
- step: poll_for_completion
  tool:
    kind: http
    url: "{{ api_url }}/status/{{ job_id }}"
  case:
    - when: "{{ event.name == 'call.done' and response.data.status == 'pending' }}"
      then:
        retry:
          max_attempts: 100
          initial_delay: 5.0
          backoff_multiplier: 1.1
    
    - when: "{{ event.name == 'call.done' and response.data.status == 'complete' }}"
      then:
        next:
          - step: process_result
```

**Missing:** True event-wait construct that pauses execution until external signal.

### 3.11 Timer Tasks

**Not currently supported.** Missing:
- Timer start event (scheduled workflow trigger)
- Timer intermediate event (delay/sleep)
- Timer boundary event (timeout on activity)

---

## 4. Visualization Capability

### 4.1 Graph Structure

The DSL naturally maps to a directed graph:

| DSL Element | Graph Representation |
|-------------|---------------------|
| `step` | Node |
| `next:` (single) | Edge |
| `next:` (multiple) | Fork (multiple outgoing edges) |
| `case: when:` | Conditional edge (labeled) |
| `loop:` | Self-loop marker on node |
| `retry:` | Self-loop marker on node |
| `tool: kind: playbook` | Subgraph reference |

### 4.2 Visualization Strengths

- ✅ **Named nodes:** Each step has unique `step:` identifier
- ✅ **Explicit edges:** `next:` defines clear transitions
- ✅ **Conditional labels:** `when:` conditions can label edges
- ✅ **Hierarchical:** Sub-playbooks create nested graphs
- ✅ **Implicit routing visible:** Steps without `next:` route to `end`

### 4.3 Visualization Example

```
                    ┌──────────────┐
                    │    start     │
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
                    │  fetch_data  │
                    │    [HTTP]    │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              │ (parallel) │            │
              ▼            ▼            ▼
       ┌──────────┐ ┌──────────┐ ┌──────────┐
       │ branch_a │ │ branch_b │ │ branch_c │
       │ [Python] │ │ [Python] │ │ [Python] │
       └────┬─────┘ └────┬─────┘ └────┬─────┘
            │            │            │
            └────────────┼────────────┘
                         │ (join)
                         ▼
                  ┌──────────────┐
                  │   aggregate  │
                  │  [Postgres]  │
                  └──────┬───────┘
                         │
                         ▼
                  ┌──────────────┐
                  │     end      │
                  └──────────────┘
```

---

## 5. Design Recommendations

### 5.1 Consistency Improvements

| Area | Current State | Recommendation |
|------|---------------|----------------|
| **Conditional routing** | v2 requires `case:` | ✅ Good - maintain strict separation |
| **Step-level shortcuts** | `next:`, `sink:` as sugar | Document as implicit `else` condition |
| **Event naming** | `step.exit`, `call.done`, etc. | Standardize and document all event names |

### 5.2 Unambiguity Improvements

| Issue | Recommendation |
|-------|----------------|
| **Result naming** | Document `result`, `response`, `this`, `event` contexts clearly |
| **Loop vs iterator** | Clarify `loop:` (step attribute) vs `iterator` (tool kind) |
| **Case evaluation timing** | Document all trigger conditions explicitly |

### 5.3 Human Readability

**Shorthand syntax for common patterns:**

```yaml
# Current verbose form:
- step: process
  tool:
    kind: python
    auth: {}
    libs: {}
    args: {}
    code: |
      result = {"done": True}

# Proposed shorthand (future):
- step: process
  python: |
    result = {"done": True}
```

### 5.4 Future-Proofing: Recommended Additions

Before freezing the DSL, consider adding:

#### 5.4.1 Timer Events

```yaml
- step: scheduled_task
  timer:
    duration: "5m"  # ISO 8601 duration
  tool: { ... }

# Or as boundary event (timeout):
- step: long_task
  tool: { ... }
  timeout: "30m"
  on_timeout:
    next:
      - step: timeout_handler
```

#### 5.4.2 Wait for External Event

```yaml
- step: await_payment
  await:
    event: "payment.{{ execution_id }}"
    timeout: "24h"
  case:
    - when: "{{ event.data.status == 'paid' }}"
      then:
        next:
          - step: payment_received
  on_timeout:
    next:
      - step: payment_timeout
```

#### 5.4.3 Human Task

```yaml
- step: approval_request
  user_task:
    form: approval_form
    assignee: "{{ workload.manager_email }}"
    timeout: "48h"
  case:
    - when: "{{ response.decision == 'approved' }}"
      then:
        next:
          - step: approved_flow
    - when: "{{ response.decision == 'rejected' }}"
      then:
        next:
          - step: rejected_flow
```

#### 5.4.4 Explicit Join Gateway

```yaml
- step: wait_for_all
  join:
    steps:
      - branch_a
      - branch_b
      - branch_c
    mode: all  # or 'first' or 'n_of_m'
  next:
    - step: after_join
```

---

## 6. Event Model Reference

### 6.1 Events that Trigger `case` Evaluation

| Event Name | Trigger Condition |
|------------|------------------|
| `step.enter` | Execution enters the step |
| `step.exit` | Step completes (success or failure) |
| `call.done` | Tool execution completed successfully |
| `call.error` | Tool execution failed with error |
| `loop.iteration.done` | Single loop iteration completed |
| `loop.done` | All loop iterations completed |
| `retry.attempt` | Retry attempt completed |

### 6.2 Template Context by Location

| Location | Available Variables |
|----------|---------------------|
| `case: when:` | `event`, `response`, `error`, `workload`, `vars` |
| `case: then: sink:` | `result` (unwrapped), `this` (envelope), `workload`, `vars` |
| `case: then: next: args:` | `result`, `response`, `workload`, `vars`, step results |
| `retry:` conditions | `response`, `error`, `attempt`, `_retry.index` |
| `vars:` extraction | `result` (current step result) |
| `loop:` context | `iterator_name` (bound element), `loop_index` |

---

## 7. Summary

### 7.1 Strengths

- ✅ **Turing-complete** via conditional branching, loops, and state storage
- ✅ **Event-driven** with reactive `case` evaluation
- ✅ **Parallel execution** via `next:` lists and `loop: mode: parallel`
- ✅ **Rich context passing** via `args`, `vars`, and `workload`
- ✅ **Composable** via sub-playbooks and workbook tasks
- ✅ **Visualizable** as directed graph with clear semantics

### 7.2 BPMN 2.0 Coverage

- **Covered:** Sequential, parallel (fork), loops, conditional branching, error handling, subprocesses
- **Partial:** Parallel join (implicit), event waiting (polling only)
- **Missing:** Timer events, human tasks, compensation, inclusive gateway

### 7.3 Design Quality

- **Consistency:** Good - v2 enforces `case` for conditional routing
- **Unambiguity:** Good - clear separation of concerns
- **Readability:** Moderate - some verbosity in tool blocks
- **Machine-parseable:** Excellent - standard YAML with clear schema

The NoETL DSL is well-suited for **automated data workflows and MLOps orchestration**, covering approximately **80-85%** of BPMN 2.0 patterns relevant to this domain.
