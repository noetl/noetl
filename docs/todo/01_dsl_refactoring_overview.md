# DSL Refactoring Overview

**Status:** Planning  
**Date:** November 6, 2025  
**Objective:** Refactor NoETL DSL to a cleaner, more expressive 4-key canonical surface

---

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

---

## 2. Loop (Step-Level Controller)

Control iteration at the step level with `loop`:

```yaml
loop:
  collection: <Jinja iterable>   # Required: iterable expression
  element: <loop_var>            # Required: variable name (available as {{ <loop_var> }})
  mode: sequential|parallel      # Optional: execution mode (default: sequential)
  until: <Jinja bool>            # Optional: early exit condition
```

**Semantics:** "Loop over `<collection>` as `<element>`"

**Example:**
```yaml
loop:
  collection: "{{ workload.users }}"
  element: user
  mode: parallel
  until: "{{ user.age > 100 }}"
```

The `element` variable becomes available in the tool's context as `{{ user }}`.

---

## 3. Tool (Actionable Unit)

The `tool` defines what action to execute. It runs **once per call** or **once per loop item**.

```yaml
tool:
  kind: <plugin_id>              # Plugin identifier (http | postgres | python | duckdb | playbook | workbook | …)
  spec: { ... }                  # Per-plugin contract (validates by kind)
  args: { ... }                  # Inputs for the plugin (callee)
  result:                        # What to do with the plugin's output
    as: <context_key>?           # Store shaped result into context
    pick: <jinja_expr>?          # Transform `this` → `out`; default `out = this`
    sink:                        # List (fan-out to many destinations)
      - <sink_id>:
          # Sink-specific config
          # (postgres/duckdb/http/s3/gcs/file/kafka/…)
    collect:                     # Only relevant if loop is present
      into: <context_key>        # Accumulator name in context
      mode: list|map             # Default: list
      key: <jinja_expr>?         # Required if mode=map
```

### 3.1 Per-Kind Spec Examples

**Playbook:**
```yaml
tool:
  kind: playbook
  spec:
    path: playbooks/user_scorer
    entry_step: start           # Optional
    return_step: finalize       # Optional
```

**Workbook:**
```yaml
tool:
  kind: workbook
  spec:
    name: compute_score         # Reference to workbook action
```

**HTTP:**
```yaml
tool:
  kind: http
  spec:
    method: GET
    endpoint: "{{ api }}/users/{{ user_id }}"
    headers:
      Authorization: "Bearer {{ token }}"
    params:
      limit: 10
    payload:
      query: "{{ search_term }}"
```

**Postgres:**
```yaml
tool:
  kind: postgres
  spec:
    query: "SELECT * FROM users WHERE id = %(user_id)s"
    auth: pg_local              # Optional credential reference
    params:
      user_id: "{{ workload.user_id }}"
```

**Python:**
```yaml
tool:
  kind: python
  spec:
    code: |
      def main(user_data):
          return {"score": user_data["rating"] * 10}
```

Or with module reference:
```yaml
tool:
  kind: python
  spec:
    module: scoring.calculator
    callable: compute_user_score
```

**DuckDB:**
```yaml
tool:
  kind: duckdb
  spec:
    query: "SELECT * FROM read_csv('{{ file_path }}')"
    file: "{{ workload.csv_path }}"  # Optional: DuckDB file path
```

---

## 4. Routing with `next`

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
    result:
      as: user_profile
      sink:
        - postgres:
            table: public.user_profiles
            mode: upsert
            key: id
            args:
              id: "{{ user_profile.id }}"
              score: "{{ user_profile.score }}"
```

**Explanation:**
- `start` fans out to both `fetch_user` and `score_user` (parallel execution)
- Both steps call `join` when complete
- `join` waits via `when` until both prerequisites are done and successful
- `join` combines results and sinks to PostgreSQL

---

### 8.2 Loop + Reduce

Parallel iteration with collection and aggregation:

```yaml
- step: proc_users
  desc: "Loop over users as 'user'"
  loop:
    collection: "{{ workload.users }}"
    element: user
    mode: parallel
  tool:
    kind: playbook
    spec:
      path: playbooks/user_profile_scorer
    args:
      user_data: "{{ user }}"
    result:
      pick: "{{ {'name': user.name, 'score': this.profile_score or 0.0} }}"
      as: last_score
      collect:
        into: all_scores
        mode: list
      sink:
        - postgres:
            table: public.user_profile_results
            mode: upsert
            key: id
            args:
              id: "{{ execution_id }}:{{ out.name }}"
              score: "{{ out.score }}"
  next:
    - step: summarize

- step: summarize
  when: "{{ loop_done('proc_users') }}"
  tool:
    kind: workbook
    spec:
      name: summarize_scores
    args:
      scores: "{{ all_scores }}"
    result:
      as: scores_summary
```

**Explanation:**
- `proc_users` loops over `workload.users` in parallel
- Each iteration calls the `user_profile_scorer` sub-playbook
- Results are:
  - Transformed via `pick` (extract name and score)
  - Stored as `last_score` (per iteration)
  - Collected into `all_scores` list
  - Sinked to PostgreSQL (per iteration)
- `summarize` waits for loop completion via `loop_done('proc_users')`
- `summarize` processes all collected scores

---

## Next Steps

This document defines the **final DSL surface**. Next portions will cover:

1. **Migration Strategy**: How to transition from current DSL to new surface
2. **Implementation Plan**: Core engine changes, validator updates, plugin adaptations
3. **Backward Compatibility**: Handling legacy playbooks during transition
4. **Testing Strategy**: Validation suite for new DSL

---

**Ready for next portion of the refactoring plan.**
