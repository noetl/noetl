# Event Processing Flow Diagrams

## Current (Old) Broker Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    Event Arrives                                 │
│            (action_completed, step_result, etc.)                 │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│            evaluate_broker_for_execution()                       │
│  • Check for failures                                            │
│  • Sleep 200ms (why?)                                            │
│  • Check execution status                                        │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                ┌───────────┴──────────────┐
                │                          │
                ▼                          ▼
    ┌─────────────────────┐   ┌──────────────────────────┐
    │ _handle_initial_    │   │ Proactive Completion     │
    │     _dispatch       │   │      Handlers            │
    │                     │   │                          │
    │ • Check if queued   │   │ • check_and_process_     │
    │ • Load playbook     │   │   completed_child_       │
    │ • Find first step   │   │   executions()          │
    │ • Enqueue if empty  │   │                          │
    └─────────────────────┘   │ • check_and_process_     │
                              │   completed_loops()      │
                              │                          │
                              │ • ensure_direct_loops_   │
                              │   finalized()           │
                              │                          │
                              │ • _advance_non_loop_    │
                              │   _steps()              │
                              └──────────┬───────────────┘
                                         │
                        ┌────────────────┴─────────────────┐
                        │                                  │
                        ▼                                  ▼
            ┌──────────────────────┐        ┌──────────────────────┐
            │ Loop Completion      │        │ Child Execution      │
            │ Processing           │        │ Processing           │
            │                      │        │                      │
            │ • Find loops         │        │ • Find child execs   │
            │ • Check status       │        │ • Check completion   │
            │ • Aggregate results  │        │ • Emit per-item evts │
            │ • Emit end_loop      │        │ • Aggregate to parent│
            │ • ~1000 lines code   │        │ • ~300 lines code    │
            └──────────────────────┘        └──────────────────────┘
```

**Problems:**
- Multiple handlers doing overlapping work
- Complex state tracking across functions
- Hard to debug when something doesn't enqueue
- Unclear which handler is responsible for what
- Legacy loop expansion mixed with new worker-based approach

---

## Refactored (New) Broker Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    Event Arrives                                 │
│            (action_completed, step_result, etc.)                 │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│            evaluate_broker_for_execution()                       │
│  • Check for failures → stop if failed                           │
│  • Check if initial state → dispatch first step                  │
│  • Otherwise → process completed steps                           │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                ┌───────────┴──────────────┐
                │                          │
                ▼                          ▼
    ┌─────────────────────┐   ┌──────────────────────────┐
    │ _dispatch_first_    │   │ _process_completed_      │
    │     step()          │   │     steps()              │
    │                     │   │                          │
    │ 1. Load playbook    │   │ 1. Find completed steps  │
    │ 2. Find 'start'     │   │    (no step_completed)   │
    │ 3. Get first action │   │                          │
    │ 4. Emit step_started│   │ 2. For each step:        │
    │ 5. Enqueue task     │   │    • Emit step_completed │
    │                     │   │    • Load playbook       │
    │ Simple & clear      │   │    • Evaluate transitions│
    └─────────────────────┘   └──────────┬───────────────┘
                                         │
                                         ▼
                        ┌───────────────────────────────────┐
                        │ _evaluate_and_enqueue_transitions │
                        │                                   │
                        │ For each transition in step.next: │
                        │                                   │
                        │ 1. Extract condition (when)       │
                        │ 2. Evaluate condition with Jinja2 │
                        │ 3. If true:                       │
                        │    • Check if actionable          │
                        │    • Emit step_started            │
                        │    • Enqueue task                 │
                        │                                   │
                        │ Clean & predictable               │
                        └───────────────────────────────────┘
```

**Benefits:**
- Single clear path from event to action
- Each function has one responsibility
- Easy to trace execution flow
- Simple condition evaluation
- No hidden state or complex tracking

---

## Step Execution Sequence

### Old Broker (Current Bug)

```
Execution Starts
    │
    ├─→ step_started(step1)
    ├─→ action_started(step1)
    ├─→ action_completed(step1)
    ├─→ step_completed(step1)
    │
    └─→ evaluate_broker()
          │
          ├─→ check_child_executions()  ← Maybe enqueues?
          ├─→ check_completed_loops()   ← Maybe enqueues?
          ├─→ ensure_loops_finalized()  ← Maybe enqueues?
          └─→ advance_non_loop_steps()  ← Maybe emits step_completed?
              │
              └─→ ??? (unclear what happens next)
    
    ❌ step2 never gets step_started event
    ❌ Only 1 queue entry instead of 3
```

### New Broker (Fixed)

```
Execution Starts
    │
    ├─→ step_started(step1)
    ├─→ action_started(step1)
    ├─→ action_completed(step1)
    │
    └─→ evaluate_broker()
          │
          └─→ _process_completed_steps()
                │
                ├─→ Emit step_completed(step1)
                ├─→ Load playbook
                ├─→ Find step1.next transitions
                ├─→ Evaluate conditions
                │
                └─→ _evaluate_and_enqueue_transitions()
                      │
                      ├─→ Emit step_started(step2)  ✓
                      └─→ Enqueue task(step2)        ✓
    
    ├─→ action_started(step2)
    ├─→ action_completed(step2)
    │
    └─→ evaluate_broker()
          │
          └─→ _process_completed_steps()
                │
                ├─→ Emit step_completed(step2)
                ├─→ Load playbook
                ├─→ Find step2.next transitions
                │
                └─→ _evaluate_and_enqueue_transitions()
                      │
                      ├─→ Emit step_started(step3)  ✓
                      └─→ Enqueue task(step3)        ✓
    
    ├─→ action_started(step3)
    ├─→ action_completed(step3)
    └─→ Emit step_completed(step3)
    └─→ Emit execution_complete
    
    ✓ All steps execute in sequence
    ✓ Clear event flow
```

---

## Iterator Handling

### Old Approach (Server-Side Expansion)

```
Iterator Step in Playbook
    │
    └─→ Broker detects type='iterator'
          │
          └─→ _handle_loop_step()
                │
                ├─→ Evaluate collection on server
                ├─→ Enumerate items on server
                ├─→ For each item:
                │     ├─→ Expand nested task
                │     ├─→ Enqueue separate job
                │     └─→ Track state in loop_iteration events
                │
                └─→ Monitor completion
                      │
                      ├─→ check_completed_loops()
                      ├─→ Aggregate results
                      └─→ Emit end_loop

Problem: Server doing worker's job
Problem: Complex state tracking
Problem: ~1000 lines of legacy code
```

### New Approach (Worker-Side Execution)

```
Iterator Step in Playbook
    │
    └─→ Broker sees type='iterator'
          │
          └─→ Enqueue ONE task with iterator config
                │
                └─→ Worker picks up task
                      │
                      ├─→ iterator plugin executes
                      │     │
                      │     ├─→ Evaluate collection
                      │     ├─→ For each item:
                      │     │     ├─→ Emit iteration_started
                      │     │     ├─→ Execute nested task
                      │     │     ├─→ Execute save (if present)
                      │     │     └─→ Emit iteration_completed
                      │     │
                      │     └─→ Emit action_completed
                      │
                      └─→ Broker sees action_completed
                            │
                            └─→ Continue to next step
    
    ✓ Server just routes, doesn't expand
    ✓ Worker handles all iteration logic
    ✓ Clean separation of concerns
    ✓ ~150 lines of focused code
```

**Special Case: Iterator with Child Playbooks**

```
Iterator calling playbooks (type: playbook)
    │
    └─→ Worker executes iterator
          │
          ├─→ For each item:
          │     ├─→ Emit iteration_started (with child_execution_id)
          │     ├─→ Spawn child playbook execution
          │     └─→ Continue to next
          │
          └─→ Emit action_completed
    
    └─→ check_iterator_child_completions()
          │
          ├─→ Find iterators with child executions
          ├─→ Check if all children completed
          ├─→ Aggregate child results
          └─→ Emit iterator_completed
    
    ✓ Server only tracks child completion
    ✓ Doesn't expand or enumerate
    ✓ Simple aggregation logic
```

---

## Transition Evaluation

### Example Playbook

```yaml
workflow:
  - step: check_weather
    type: http
    url: https://api.weather.com/current
    next:
      - when: "{{ check_weather.data.temp > 80 }}"
        step: send_alert
        data:
          temp: "{{ check_weather.data.temp }}"
          
      - when: "{{ check_weather.data.temp <= 80 }}"
        step: log_normal
```

### Evaluation Flow

```
action_completed(check_weather)
    │
    └─→ _process_completed_steps()
          │
          ├─→ Load playbook
          ├─→ Get check_weather step definition
          ├─→ Build evaluation context:
          │     {
          │       workload: {...},
          │       check_weather: {
          │         data: {temp: 85, ...}
          │       }
          │     }
          │
          └─→ For each transition in step.next:
                │
                ├─→ Transition 1:
                │     when: "{{ check_weather.data.temp > 80 }}"
                │     │
                │     ├─→ Evaluate: 85 > 80 = true ✓
                │     ├─→ Emit step_started(send_alert)
                │     └─→ Enqueue send_alert with data={temp: 85}
                │
                └─→ Transition 2:
                      when: "{{ check_weather.data.temp <= 80 }}"
                      │
                      └─→ Evaluate: 85 <= 80 = false ✗
                          (skip this transition)
    
    Result: Only send_alert executes
```

---

## Key Architectural Changes

### Before: Server-Centric

```
            Server (Heavy)
                 │
    ┌────────────┼────────────┐
    │            │            │
    ▼            ▼            ▼
 Expand      Track        Aggregate
 Loops       State        Results
    │            │            │
    └────────────┴────────────┘
                 │
                 ▼
            Enqueue Jobs
                 │
                 ▼
            Workers (Light)
```

### After: Worker-Centric

```
        Server (Light)
             │
    ┌────────┴────────┐
    │                 │
    ▼                 ▼
 Analyze          Evaluate
 Events         Transitions
    │                 │
    └────────┬────────┘
             │
             ▼
        Enqueue Jobs
             │
             ▼
        Workers (Heavy)
             │
    ┌────────┼────────┐
    │        │        │
    ▼        ▼        ▼
 Execute  Iterate  Aggregate
 Actions   Loops   Results
```

**Benefits:**
- Server scales better (less work per request)
- Workers do the heavy lifting (collection evaluation, iteration)
- Clear separation: Server = routing, Worker = execution
- Easier to add more workers for scale

---

## Summary

| Aspect | Old Broker | New Broker |
|--------|-----------|-----------|
| **Complexity** | High (multiple handlers) | Low (single path) |
| **Code Lines** | ~1700 lines | ~1000 lines |
| **Responsibilities** | Too many (expand, track, aggregate) | One (route based on events) |
| **Iterator Handling** | Server-side expansion | Worker-side execution |
| **Debuggability** | Hard (multiple code paths) | Easy (clear flow) |
| **Maintainability** | Difficult (legacy code) | Good (clean structure) |
| **Performance** | Slower (server overhead) | Faster (worker does work) |
| **Bug Fix** | Unclear where to look | Obvious in transition eval |

The refactoring simplifies the broker to its core purpose: **analyze events, evaluate transitions, enqueue next steps**. Everything else happens on workers where it belongs.
