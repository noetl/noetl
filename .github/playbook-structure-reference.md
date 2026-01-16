# NoETL Playbook Structure Reference

This document provides a comprehensive reference for NoETL playbook structure based on working examples. Use this as a prompt reference for AI coding agents.

## Working Example Files

Reference these canonical examples when updating documentation:
- `tests/fixtures/playbooks/control_flow_workbook/control_flow_workbook.yaml`
- `tests/fixtures/playbooks/http_duckdb_postgres/http_duckdb_postgres.yaml`
- `tests/fixtures/playbooks/playbook_composition/playbook_composition.yaml`
- `tests/fixtures/playbooks/playbook_composition/user_profile_scorer.yaml`

## Core Concepts

### 1. Template Rendering
- Technically we use **Jinja2 template rendering** to substitute variables and context data
- All string values in playbooks support Jinja2 expressions: `{{ ... }}`
- Available context: `workload.*`, `execution_id`, `<step_name>.data`, iterator variables

### 2. Metadata Section (Required)
Playbook **must** have metadata section with:
```yaml
metadata:
  name: unique_playbook_name      # Required: unique identifier
  path: catalog/path/to/playbook  # Required: catalog registration path
```

### 3. Workload Section
- Section to define **global variables**
- Merged with payload input when request for execution is registered
- Accessible throughout playbook via `{{ workload.variable_name }}`
```yaml
workload:
  temperature_threshold: 25
  cities:
    - name: London
      lat: 51.51
```

### 4. Workbook Section
- Section where we keep **named tasks** (tasks based on action types)
- Tasks can be referenced from workflow section where we define steps
- Each workbook entry has `name` and `type` attributes
- Workbook tasks can have types: `python`, `http`, `postgres`, `duckdb`, `playbook`, `iterator`
- **Cannot** have `type: workbook` (to avoid circular references)

```yaml
workbook:
  - name: compute_flag
    tool: python
    code: |
      def main(temperature_c):
          return {"is_hot": temperature_c >= 25.0}
```

### 5. Workflow Section (Required)
- Has a list of steps that use `next` attribute to define transitions to one or many other steps
- **Must** have a step named `"start"` - it's the entry point for workflow execution
- The `start` step performs routing to other steps

```yaml
workflow:
  - step: start
    desc: "Entry point"
    next:
      - when: "{{ condition }}"
        then:
          - step: next_step
```

## Step Attributes

### 7. Step Name (Required)
- `step` attribute defines the **name of the step**
- Must be unique within the workflow

### 8. Step Description (Optional)
- `desc` attribute provides human-readable description of what step does

### 9. Step Type (Required for non-routing steps)
- `type` attribute defines what type of action the step will perform

## Action Types

### 10-12. Type: workbook
- `type: workbook` references a task from the workbook section
- Step must have `name` attribute to lookup the task in workbook
- Steps can have action types: `workbook`, `python`, `http`, `postgres`, `duckdb`, `playbook`, `iterator`
- **Difference**: Only workflow steps can have `type: workbook`; workbook tasks cannot

```yaml
- step: eval_flag
  type: workbook
  name: compute_flag    # References workbook task
  data:
    temperature_c: "{{ workload.temperature }}"
```

### 13. Type: python
- Executes Python code defined in `code` attribute
- **No `def main()` wrapper** - code executes directly
- Libraries imported via `libs:` section (aliased)
- Variables injected via `args:` section
- Result assigned to `result` variable (not returned)

```yaml
- step: process
  tool:
    kind: python
    libs: {}
    args:
      value: "{{ workload.input }}"
    code: |
      # Pure Python code - no imports, no def main()
      result = {"status": "success", "data": {"result": value * 2}}
```

### 14. Type: playbook
- Step passes data to sub-playbook and waits for execution to complete
- Uses `path` attribute to specify sub-playbook location
- Can specify `return_step` to indicate which step's result to return

```yaml
- step: call_subplaybook
  type: playbook
  path: tests/fixtures/playbooks/user_scorer.yaml
  return_step: finalize_result
  data:
    user_data: "{{ user }}"
```

### 15. Type: iterator
- Executes task for each element of a collection
- Required attributes:
  - `collection`: Jinja2 expression evaluating to iterable (e.g., `"{{ workload.users }}"`)
  - `element`: Variable name for current item (e.g., `user`)
  - `mode`: Execution mode - `sequential` or `async`
  - `task`: Nested task definition

```yaml
- step: process_users
  type: iterator
  collection: "{{ workload.users }}"
  element: user
  mode: sequential
  task:
    type: python
    data:
      user_name: "{{ user.name }}"
    code: |
      def main(user_name):
          return {"processed": user_name}
```

### 16. Save Attribute
- Each task (action type) can have a `save` attribute
- Used to persist result of task execution to storage
- Storage types: `postgres`, `duckdb`, `http`
- Result of task execution is passed to the storage action type

```yaml
sink:
  data:
    id: "{{ execution_id }}:{{ user.name }}"
    result: "{{ this.data | tojson }}"  # 'this' references current task result
  tool: postgres
  auth: pg_local
  table: public.results
  mode: upsert  # append, overwrite, update, upsert
  key: id       # Primary key for upsert
```

### 17. Next Attribute (Step Navigation)
- Each step (and **only** steps in workflow) can have `next` attribute
- `next` can contain:
  - `when`: Jinja2 condition expression
  - `then`: Array of step names to jump to when condition is true
  - `else`: Array of step names for else branch
  - `data`: Data to pass to next steps (overrides default step result)

**Conditional routing:**
```yaml
- step: start
  desc: Start Weather Analysis Workflow
  next:
    - when: '{{ workload.state == "ready" }}'
      then:
        - step: city_loop
    - else:
        - step: end
```

**Passing data to next step:**
```yaml
next:
  - data:
      alerts: '{{ city_loop.results }}'
    step: aggregate_alerts
```

**Multiple next steps (parallel execution):**
```yaml
next:
  - step: task_a
  - step: task_b
```

### 18. Auth Attribute
Action types can have `auth` attribute for authentication:

**Simple credential reference:**
```yaml
auth: pg_local  # String reference to credential key
```

**Unified auth dictionary (multiple credentials):**
```yaml
auth:
  pg_db:
    source: credential
    type: postgres
    key: pg_local
  gcs_secret:
    source: credential
    type: hmac
    key: gcs_hmac_local
    scope: gs://{{ workload.gcs_bucket }}
```

Auth types: `postgres`, `duckdb`, `hmac`, `bearer`

### 19. Action Results and Data Flow
- Actions can return results
- Use `save` attribute to persist data to storage
- Action result becomes available for other steps by reference: `{{ step_name.data }}`
- Within the same step's save block, use `{{ this.data }}` to reference current result
- Iterator results available as: `{{ iterator_step.results }}` (array of results)
- Workbook task results: `{{ step_name.data.field_name }}`

**Example - Accessing step results:**
```yaml
- step: compute_score
  tool:
    kind: python
    libs: {}
    args: {}
    code: |
      # Pure Python code - no imports, no def main()
      result = {"status": "success", "data": {"score": 85, "grade": "A"}}

- step: use_result
  tool:
    kind: python
    libs: {}
    args:
      previous_score: "{{ compute_score.data.score }}"  # Access: 85
    code: |
      # Pure Python code - variables from args are available
      result = {"status": "success", "data": {"doubled": previous_score * 2}}
```

### 20. End Step
- Step named `"end"` should be defined to properly complete playbook execution
- Allows aggregation of playbook execution results
- Can save final results based on conditions
- Can pass results back to parent playbook (in playbook composition)

```yaml
- step: end
  desc: "Complete execution"
  tool: python
  data:
    final_results: "{{ aggregate_step.data }}"
  code: |
    def main(final_results):
        print(f"Pipeline completed: {final_results}")
        return {"status": "completed", "results": final_results}
```

## Complete Minimal Example

```yaml
apiVersion: noetl.io/v1
kind: Playbook

metadata:
  name: minimal_example
  path: tests/fixtures/playbooks/hello_world/hello_world

workload:
  threshold: 25

workbook:
  - name: check_threshold
    tool: python
    code: |
      def main(value):
          return {"passed": value > 25}

workflow:
  - step: start
    desc: "Begin workflow"
    next:
      - step: check_value

  - step: check_value
    type: workbook
    name: check_threshold
    data:
      value: "{{ workload.threshold }}"
    next:
      - when: "{{ result.passed }}"
        then:
          - step: success_path
      - else:
          - step: end

  - step: success_path
    tool:
      kind: python
      libs: {}
      args: {}
      code: |
        # Pure Python code - no imports, no def main()
        result = {"status": "success", "data": {"message": "Threshold passed"}}
    sink:
      tool:
        kind: postgres
        auth: pg_local
        table: results
        mode: append
      args:
        message: "{{ this.data.message }}"
    next:
      - step: end

  - step: end
    desc: "Finish"
```

## Key Rules Summary

1. ✅ Use Jinja2 for all variable substitution
2. ✅ `metadata` section with `name` and `path` is required
3. ✅ `workload` defines global variables merged with execution payload
4. ✅ `workbook` contains named reusable tasks referenced by name
5. ✅ `workflow` is required and must have `start` step
6. ✅ Each step has unique `step` name
7. ✅ Steps use `tool:` with `kind:` to specify action type
8. ✅ `tool: {kind: workbook, name: ...}` references workbook tasks
9. ✅ `tool: {kind: python, libs: {}, args: {}, code: ...}` for Python - no def main()
10. ✅ `tool: {kind: playbook, path: ...}` for sub-playbook composition
11. ✅ `tool: {kind: iterator, ...}` loops with `collection`, `element`, `mode`
12. ✅ `sink` attribute persists results to storage backends
13. ✅ `next` attribute controls flow with `when`/`then`/`else`
14. ✅ `auth` provides credential configuration under `tool:`
15. ✅ Access results via `{{ step_name.data }}`
16. ✅ Define `end` step for proper completion

## Reference Documentation

Always update these files when playbook structure changes:
- `.github/ai-instructions.md` - AI agent development guide
- `docs/playbook_schema.json` - JSON Schema validation
- `docs/playbook_structure.md` - Comprehensive structure guide
- `docs/simple/` - Simple documentation directory
