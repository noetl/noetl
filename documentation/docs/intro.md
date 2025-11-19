---
sidebar_position: 1
---

# DSL

## 1. Final DSL Surface (Authoring Contract)

### 1.1 Canonical Step Keys (Exactly 4 Characters)

Every step in a workflow is defined by exactly **4 core keys**:

```yaml
step: <string>        # Unique step identifier
desc: <string>        # Human-readable description
when: <jinja>         # Gate condition (default: true)
bind: <object>        # Extra context bindings (optional)
loop: <object>        # Iteration controller (optional)
tool: <object>        # Actionable unit (required unless pure router)
next: <array>         # Ordered list of edges
```

**Key Principles:**
- **Exactly 4 chars**: `step`, `desc`, `when`, `bind`, `loop`, `tool`, `next`
- **step**: Unique ID for the step (string)
- **desc**: Human description (string)
- **when**: Gate to run this step when called (Jinja expression, default `true`)
- **bind**: Extra context bindings (object, optional)
- **loop**: Iteration controller (object, optional)
- **tool**: Actionable unit to run (object, required unless step is a pure router)
- **next**: Ordered list of edges `{ step: <id>, when?: <jinja> }` (array)

## Tool (Actionable Unit)

The `tool` defines what action to execute. It runs **once per call** or **once per loop item**.

```yaml
tool:
  kind: <plugin_id>              # Plugin identifier (http | postgres | python | duckdb | playbook | …)
```

## Routing with `next`

Define step transitions with conditional routing:

```yaml
next:
  - when: "<Jinja condition>"   # Optional guard (if/elif)
    step: <target_step_id>
  - step: <else_target>         # Final else (no `when`)
```

**Evaluation Order:**
- Edges are evaluated **in order**
- First matching edge is taken (based on `when` condition)
- If none match → no successor (workflow may stall or complete)

**Example:**
```yaml
next:
  - when: "{{ score > 80 }}"
    step: high_score_path
  - when: "{{ score > 50 }}"
    step: medium_score_path
  - step: low_score_path       # Default fallback
```

---

## 5. Start & Calling Model (Petri-Net Style)

### 5.1 Initial State

- Only a special **start step** is enabled initially (router or no-op)
- Steps run **only when called** by a predecessor via `next`

### 5.2 Step Execution Flow

1. On each call, the engine evaluates the target step's **step-level `when`**
2. If `false`, the call is **parked (pending)**. Subsequent calls re-evaluate until it becomes `true`
3. When `true`, the step executes **once (idempotent)**; later calls are ignored

### 5.3 Execution Semantics

```
start → call(step_a) → evaluate when → park if false
                                     → execute if true (once only)
                                     → subsequent calls ignored
```

---

## 6. Engine Status Namespace + Helpers

### 6.1 Read-Only Status Context

Engine writes read-only status under `step.<id>.status.*` in context:

```yaml
step.<id>.status:
  done: bool              # Step has completed
  ok: bool|null           # Step completed successfully (null if not done)
  running: bool           # Step is currently executing
  started_at: timestamp   # Execution start time
  finished_at: timestamp|null  # Execution end time (null if not done)
  error: string|null      # Error message (null if no error)
  # For loop steps:
  total: int              # Total iterations
  completed: int          # Completed iterations
  succeeded: int          # Successful iterations
  failed: int             # Failed iterations
```

### 6.2 Jinja Global Helpers

Helper functions available in Jinja templates:

```python
done(step_id)           # Returns: bool - step has completed
ok(step_id)             # Returns: bool - step completed successfully
fail(step_id)           # Returns: bool - step failed
running(step_id)        # Returns: bool - step is currently running

loop_done(step_id)      # Returns: bool - loop step fully drained
all_done(list_of_ids)   # Returns: bool - all steps in list completed
any_done(list_of_ids)   # Returns: bool - any step in list completed
```

**Usage Example:**
```yaml
when: "{{ done('fetch_user') and ok('score_user') }}"
```

### 6.3 Reserved Namespace

**IMPORTANT:** `step` is **reserved and read-only**.

The validator **must reject** attempts to:
- Bind to `step` via `bind`
- Write to `step` via `result.as`

---

## 7. Execution Order Inside a Step

When a step is called, execution follows this order:

1. **Evaluate `when`** → Must be truthy to run
2. **Apply `bind`** (if any) to the context
3. **If `loop`**: 
   - Iterate over `collection` (sequential or parallel)
   - Inject `element` into context for each item
   - Run `tool` per item
4. **Else**: Run `tool` once
5. **`tool.result` handling**:
   - `raw = this` (plugin's return value)
   - `out = pick ? eval(pick) : raw`
   - If `as`: set `context[as] = out`
   - If `collect`: append/merge `out` into `context[collect.into]` (per loop)
   - For each `sink` item: emit `out` to that sink
6. **Evaluate `next` edges** (if any) and call the chosen successor

---

## 8. Authoring Examples

### 8.1 Fan-Out → AND-Join (No Dependencies, Pure `when`)

Parallel execution with synchronization at join point:

```yaml
- step: start
  next:
    - step: fetch_user
    - step: score_user

- step: fetch_user
  tool:
    kind: http
    spec:
      method: GET
      endpoint: "{{ api }}/users/{{ workload.user_id }}"
    result:
      as: user_raw
  next:
    - step: join

- step: score_user
  tool:
    kind: playbook
    spec:
      path: playbooks/user_scorer
    args:
      user: "{{ user_raw }}"
    result:
      as: user_score
  next:
    - step: join

- step: join
  when: "{{ done('fetch_user') and ok('score_user') }}"
  tool:
    kind: python
    spec:
      code: |
        def main(context, results):
            u = context["user_raw"]
            s = context["user_score"]
            return {
                "id": u["id"],
                "score": s["value"]
            }
```

**Explanation:**
- `start` fans out to both `fetch_user` and `score_user` (parallel execution)
- Both steps call `join` when complete
- `join` waits via `when` until both prerequisites are done and successful
- `join` combines results and sinks to PostgreSQL
