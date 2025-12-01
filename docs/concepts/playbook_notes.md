# Playbook Structure Notes

## Working Examples

- [control_flow_workbook.yaml](../../tests/fixtures/playbooks/control_flow_workbook/control_flow_workbook.yaml)
- [http_duckdb_postgres.yaml](../../tests/fixtures/playbooks/http_duckdb_postgres/http_duckdb_postgres.yaml)
- [playbook_composition.yaml](../../tests/fixtures/playbooks/playbook_composition/playbook_composition.yaml)
- [user_profile_scorer.yaml](../../tests/fixtures/playbooks/playbook_composition/user_profile_scorer.yaml)
- [iterator_save_test.yaml](../../tests/fixtures/playbooks/iterator_save_test.yaml)
- [state_report_generation.yaml](../../tests/fixtures/playbooks/test/state_report_generation.yaml)

## Main Concepts

### 1. Template Rendering
Playbooks use **Jinja2** template rendering to substitute variables and context data throughout the workflow definition.

### 2. Metadata Section
Every playbook must have a metadata section with `name` and `path` attributes:
```yaml
metadata:
  name: playbook_name
  path: catalog/path
```

### 3. Workload Section
The `workload` section defines global variables that are merged with payload input when an execution is registered.

### 4. Workbook Section
The `workbook` section contains named tasks (based on action types) that can be referenced from workflow steps.

### 5. Workflow Section
The `workflow` section defines a list of steps that use the `next` attribute to transition between steps.

### 6. Start Step (Required)
The workflow **must** have a step named `start` - this is the entry point for workflow execution and typically handles initial routing.

### 7. Step Attributes

#### Required Attributes:
- **`step`** - Unique name of the step
- **`tool`** - Defines the action type to perform

#### Optional Attributes:
- **`desc`** - Description of what the step does
- **`args`** - Input arguments/data passed to the action
- **`next`** - Transition rules to subsequent steps
- **`loop`** - Iteration configuration for collections
- **`sink`** - Persistence configuration for results
- **`auth`** - Authentication configuration
- **`retry`** - Retry policy configuration

### 8. Action Tools

#### Available Tools:
- **`workbook`** - References a named task from the workbook section (requires `name` attribute)
- **`python`** - Executes Python code defined in the `code` attribute (must have `def main(input_data):` function that receives `args` data)
- **`playbook`** - Calls another playbook and waits for completion
- **`http`** - Makes HTTP requests
- **`postgres`** - Executes PostgreSQL commands
- **`duckdb`** - Executes DuckDB queries
- **`snowflake`** - Executes Snowflake queries
- And other plugin-based tools

### 9. Loop Attribute

Any action tool can have a `loop` attribute to iterate over collections:

```yaml
- step: process_items
  tool: http
  url: "{{ workload.api_url }}/items/{{ item_id }}"
  method: GET
  loop:
    collection: "{{ workload.items | map(attribute='id') | list }}"
    element: item_id
    mode: sequential
```

**Loop Structure:**
- **`collection`** - Jinja2 expression resolving to an iterable
- **`element`** - Variable name for the current iteration item
- **`mode`** - `sequential` (one at a time) or `async` (parallel execution)

> **Note:** This replaces the deprecated `type: iterator` pattern with nested `task:` blocks.

### 10. Sink Attribute

Tasks can have a `sink` attribute to persist results to storage backends:

```yaml
sink:
  tool: postgres
  auth: "{{ workload.pg_auth }}"
  table: public.my_table
  mode: upsert
  key: id
  args:
    id: "{{ result.data.id }}"
    name: "{{ result.data.name }}"
```

**Sink Options:**
- **`tool`** - Storage backend (postgres, duckdb, http)
- **`auth`** - Credential reference
- **`table`** - Target table name
- **`mode`** - Insert mode (insert, upsert, append)
- **`key`** - Primary key field (for upsert)
- **`args`** - Column mappings with Jinja2 expressions
- **`statement`** - Raw SQL statement (alternative to table/args)

> **Note:** Use `sink` instead of the deprecated `save` attribute.

### 11. Next Attribute (Conditional Routing)

Steps can have conditional routing using the `next` attribute:

```yaml
- step: start
  desc: Start Weather Analysis Workflow
  next:
    - when: '{{ workload.state == ''ready'' }}'
      then:
        - step: city_loop
    - else:
        - step: end
```

You can also pass arguments to the next step:

```yaml
next:
  - args:
      alerts: '{{ city_loop.results }}'
    step: aggregate_alerts
```

### 12. Authentication

Action tools support authentication via:
- **`auth`** - Single credential reference: `auth: "{{ workload.pg_auth }}"`

### 13. Result Access

Actions return results accessible via step name references:
- **`{{ step_name.data }}`** - Access results from previous steps
- **`{{ result.data }}`** - Access current step result (within retry conditions or sink blocks)

> **Note:** `{{ this.data }}` is deprecated; use `{{ result.data }}` instead.

### 14. End Step (Required)

A step named `end` must be defined to finalize playbook execution, aggregate results, and optionally pass data back to parent playbooks.

## Context Reference Patterns

| Pattern | Description | Usage Context |
|---------|-------------|---------------|
| `{{ workload.variable }}` | Global workload variables | Anywhere in playbook |
| `{{ step_name.data }}` | Results from previous steps | In subsequent steps |
| `{{ result.data }}` | Current step result | Within retry/sink blocks |
| `{{ execution_id }}` | Current execution ID | Anywhere in playbook |
| `{{ element_name }}` | Loop iteration variable | Within loop context |

## Complete Loop Example

Here's a complete example showing loop, retry, and sink configuration:

```yaml
- step: fetch_patients
  desc: Fetch data for each patient with retry and persistence
  tool: http
  url: "{{ workload.api_url }}/patients/{{ patient_id }}"
  method: GET
  loop:
    collection: "{{ load_ids.data.command_0.rows | map(attribute='patient_id') | list }}"
    element: patient_id
    mode: sequential
  headers:
    Authorization: "Bearer {{ token(workload.google_auth) }}"
  retry:
    max_attempts: 10
    initial_delay: 2.0
    backoff_multiplier: 2.0
    max_delay: 60.0
    jitter: true
    retry_when: "{{ result.data.status_code != 200 and result.data.status_code != 404 }}"
    stop_when: "{{ result.data.status_code in [400, 401, 403] }}"
  sink:
    tool: postgres
    auth: "{{ workload.pg_auth }}"
    statement: |
      INSERT INTO public.patients (patient_id, payload)
      VALUES ({{ patient_id }}, '{{ result.data | tojson }}'::jsonb)
      ON CONFLICT (patient_id) DO UPDATE SET
        payload = EXCLUDED.payload,
        fetched_at = now()
  next:
    - step: process_results
```

## Key DSL Changes (since v1.2.2)

### Iterator Pattern Migration
**Old pattern:**
```yaml
- step: process_items
  type: iterator
  collection: "{{ workload.users }}"
  element: user
  mode: sequential
  task:
    type: http
    url: "{{ workload.api_url }}/{{ user }}"
```

**New pattern:**
```yaml
- step: process_items
  tool: http
  url: "{{ workload.api_url }}/{{ user }}"
  loop:
    collection: "{{ workload.users }}"
    element: user
    mode: sequential
```

### Save/Sink Migration
**Old pattern:**
```yaml
save:
  storage: postgres
  auth: "{{ workload.pg_auth }}"
  table: public.my_table
```

**New pattern:**
```yaml
sink:
  tool: postgres
  auth: "{{ workload.pg_auth }}"
  table: public.my_table
```

### Context Reference Updates
- **Old:** `{{ this.data }}` → **New:** `{{ result.data }}` (within same step)
- **Previous steps:** Use `{{ step_name.data }}`

### Tool vs Type
- **Preferred:** `tool: postgres`
- **Legacy:** `type: postgres` (still supported for backward compatibility)

### Retry Conditions
Use `result.data` for current step result in `retry_when` and `stop_when` expressions:
```yaml
retry:
  retry_when: "{{ result.data.status_code != 200 }}"
  stop_when: "{{ result.data.status_code in [400, 401, 403] }}"
```
