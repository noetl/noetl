# NoETL DSL Design Specification (Step Widgets v2)

## Overview

The NoETL DSL defines workflows as a sequence of typed steps (widgets). Each step type has its own inputs, outputs, and execution semantics. Playbooks are YAML/JSON documents validated against the schema in `docs/playbook-schema.json`.

This revision replaces the previous "run/rule/case" model with explicit step types:
- start — Entry point of a workflow. Must route to the first executable step via `next`.
- end — Terminal step. No `next`. Used broadly.
- workbook — Invokes a named task from the workbook library; use `task:` and `args:` to pass inputs.
- python — Runs inline Python in the step itself.
- http — Makes an HTTP call directly from a step (method, endpoint, headers, params/payload).
- duckdb — Executes DuckDB SQL/script in the step.
- postgres — Executes PostgreSQL SQL/script in the step.
- secrets — Reads a secret from a provider (e.g., Google Secret Manager) and exposes it as `secret_value` (or a custom alias).
- playbooks — Executes all playbooks under a catalog path, forwarding inputs via `args:`; the step result can be passed on to the next step.
- loop — Runs a loop over either a workbook task (for single-step loops) or playbooks (for multi-step subflows).

---

## Key Components

### Playbook
Top-level workflow definition.

Properties:
- apiVersion: DSL schema version (const: `noetl.io/v1`)
- kind: Document kind (const: `Playbook`)
- name: Playbook name
- path: Catalog path for this playbook
- environment: Global variables and config
- context: Runtime variables (e.g., execution ids, state)
- workbook: Library of reusable tasks callable from `workbook` steps
- workflow: Ordered list of steps (widgets)

Example:
```yaml
apiVersion: noetl.io/v1
kind: Playbook
name: UserOnboarding
path: workflows/example/user_onboarding
environment:
  postgres_url: "postgres://user:pass@localhost:5432/app"
context:
  jobId: "{{ uuid() }}"
  state: "init"
workbook:
  - task: get_weather
    type: http
    desc: Weather by city
    method: GET
    endpoint: "https://api.example.com/weather"
```

---

## Steps (Widgets)

Each step has:
- step: Unique step name
- type: One of `start|end|workbook|python|http|duckdb|postgres|secrets|playbooks|loop`
- next: The next step name (string or list of names). Not allowed for `end`. Required for `start`.
- args: (object, optional): Input variables passed to the step BEFORE execution
- vars: (object, optional): Variable extraction block - extracts values from step result AFTER execution
- Inputs/Outputs: Vary by type as defined below.

General execution:
- Steps execute in order by following `next`.
- A step may receive input variables via `args:` (evaluated BEFORE execution).
- A step may extract output variables via `vars:` block (evaluated AFTER execution).
- A step may optionally publish outputs to the playbook context under a variable name (see `as:` below).
- If a step has no `next` and is not `end`, the branch terminates implicitly.

### Variable Lifecycle: BEFORE vs AFTER Execution

NoETL provides different mechanisms for passing variables at different stages of step execution.

#### BEFORE Execution (Input Variables)

**1. Global Variables** - `workload:` section (top-level)
```yaml
workload:
  api_key: "abc123"
  retry_count: 3
  base_url: "{{ payload.environment }}"  # Can use payload from CLI

workflow:
  - step: fetch_data
    tool: http
    endpoint: "{{ workload.base_url }}/api/data"
    headers:
      Authorization: "Bearer {{ workload.api_key }}"
```

**2. Step Input Arguments** - `args:` at step level
```yaml
- step: compute
  tool: python
  args:                                    # ← BEFORE execution, passed to main()
    input_value: 100
    multiplier: "{{ workload.retry_count }}"
    previous_total: "{{ fetch_data.total }}"
  code: |
    def main(input_value, multiplier, previous_total):
      return {"result": input_value * multiplier + previous_total}
```

**3. Next Step Arguments** - `args:` in `next` block
```yaml
- step: decide
  tool: python
  code: |
    def main():
      return {"should_retry": True, "attempt_number": 1}
  next:
    - when: "{{ result.should_retry }}"
      then:
        - step: retry_step
      args:                                # ← BEFORE retry_step execution
        attempt: "{{ result.attempt_number }}"
        max_attempts: 3
```

#### AFTER Execution (Extract from Result)

**1. Vars Block** - `vars:` at step level (extract and store for reuse)
```yaml
- step: fetch_users
  tool: postgres
  query: "SELECT user_id, email, created_at FROM users WHERE active = true LIMIT 5"
  vars:                                    # ← AFTER execution, extracts from result
    first_user_id: "{{ result[0].user_id }}"
    first_email: "{{ result[0].email }}"
    user_count: "{{ result | length }}"
  next:
    - step: send_notification

- step: send_notification
  tool: http
  method: POST
  endpoint: "https://api.example.com/notify"
  payload:
    user_id: "{{ vars.first_user_id }}"   # Access extracted variable
    email: "{{ vars.first_email }}"
    total_users: "{{ vars.user_count }}"
```

**2. Direct Step Access** - `{{ step_name.field }}` (no extraction needed)
```yaml
- step: calculate
  tool: python
  code: |
    def main():
      return {"total": 100, "count": 5}
  next:
    - step: report

- step: report
  tool: python
  args:
    total: "{{ calculate.total }}"                      # Direct access
    average: "{{ calculate.total / calculate.count }}"  # Can compute inline
```

**Template Namespace Summary**:
- `{{ workload.field }}` - Global variables (BEFORE: defined in workload section)
- `{{ args.field }}` - Step input arguments (BEFORE: passed via args)
- `{{ result.field }}` - Current step result (AFTER: use in vars block)
- `{{ vars.var_name }}` - Extracted variables (AFTER: use in subsequent steps)
- `{{ step_name.field }}` - Previous step result (AFTER: direct access)
- `{{ execution_id }}` - System variable (available anytime)
- `{{ payload.field }}` - CLI payload (available anytime)

**Example**:
```yaml
- step: fetch_users
  tool: postgres
  query: "SELECT user_id, email, created_at FROM users WHERE active = true LIMIT 5"
  vars:
    first_user_id: "{{ result[0].user_id }}"
    first_email: "{{ result[0].email }}"
    user_count: "{{ result | length }}"
  next:
  - step: send_notification

- step: send_notification
  tool: http
  method: POST
  endpoint: "https://api.example.com/notify"
  payload:
    user_id: "{{ vars.first_user_id }}"
    email: "{{ vars.first_email }}"
    total_users: "{{ vars.user_count }}"
```
---

## Step Types

### start
Entry point that routes to the first executable step.

Inputs: none
Outputs: none
Required: `next`

Example:
```yaml
- step: start
  type: start
  next: fetch_user
```

### end
Terminal step.

Inputs: none
Outputs: none
Constraints: Must not define `next`.

Example:
```yaml
- step: end
  type: end
```

### workbook
Invoke a named task from the workbook library.

Inputs:
- task (string, required): Name of a task defined under `workbook` at top-level
- args (object, optional): Inputs forwarded to the task
- as (string, optional): Variable name to store the task result

Outputs:
- Result of the task, stored under `context[as]` if `as` is provided, else available as step-local `result`

Example:
```yaml
- step: fetch_weather
  tool: workbook
  task: get_weather
  args:
    city: "Paris"
  as: weather
  next: end
```

### python
Execute inline Python code.

Inputs:
- code (string, required): Python code to execute
- args (object, optional): Variables to inject into the code context
- as (string, optional): Variable name to store the result

Outputs:
- `result` from the last expression or explicit `return` in the code block; saved under `as` if provided

Example:
```yaml
- step: compute_score
  tool: python
  args:
    a: 5
    b: 7
  code: |
    total = a + b
    return {"sum": total, "ok": True}
  as: score
  next: end
```

### http
Perform an HTTP request.

Inputs:
- method (enum: GET, POST, PUT, DELETE, PATCH) required
- endpoint (string, required)
- headers (object, optional)
- params (object, optional)
- body (object|string, optional)
- timeout (number, optional, seconds)
- verify (boolean, optional)
- as (string, optional)

Outputs:
- `status`, `headers`, `body`, `json` (if parseable). If `as` is provided, the whole response object is saved under that name.

Example:
```yaml
- step: call_api
  type: http
  method: GET
  endpoint: "https://api.example.com/users/{{ user_id }}"
  headers:
    Authorization: "Bearer {{ env.API_TOKEN }}"
  as: user_response
  next: end
```

### duckdb
Run DuckDB SQL/script.

Inputs:
- script (string, required): SQL or script
- files (array[string], optional): External file paths
- as (string, optional)

Outputs:
- Query result set (if any), saved under `as` if provided

Example:
```yaml
- step: duck_transform
  tool: duckdb
  script: |
    CREATE OR REPLACE TABLE t AS SELECT 1 AS id;
    SELECT * FROM t;
  as: table_rows
  next: end
```

### postgres
Run PostgreSQL SQL/script.

Inputs:
- sql (string, required)
- connection (string, optional): DSN/URL; OR provide discrete fields below
- db_host, db_port, db_user, db_password, db_name, db_schema (optional)
- as (string, optional)

Outputs:
- Query result set (if any) or `rowcount`; saved under `as` if provided

Example:
```yaml
- step: load_users
  type: postgres
  connection: "{{ environment.postgres_url }}"
  sql: |
    SELECT id, email FROM users LIMIT 10;
  as: users
  next: end
```

### secrets
Read a secret from a provider.

Inputs:
- provider (enum: gcp, aws, azure, vault, env)
- name (string, required): Secret identifier
- project (string, optional)
- version (string|number, optional)
- as (string, optional, default logical value: `secret_value`)

Outputs:
- Secret material as a string; saved under `as` (default `secret_value`)

Example:
```yaml
- step: get_openai_key
  type: secrets
  provider: gcp
  project: my-gcp-project
  name: OPENAI_API_KEY
  as: openai_api_key
  next: end
```

### playbooks
Execute all playbooks under a catalog path.

Inputs:
- catalog_path (string, required): Path/prefix in the catalog
- with (object, optional): Inputs to forward to each playbook
- parallel (boolean, optional): Execute sub-playbooks in parallel
- as (string, optional)

Outputs:
- Array of child playbook results; saved under `as` if provided

Example:
```yaml
- step: run_batch
  type: playbooks
  catalog_path: workflows/batch/jobs
  with:
    job_date: "{{ today() }}"
  parallel: true
  as: batch_results
  next: end
```

### loop
Iterate over a collection, running either a workbook task per item or a sub-playbook per item.

Variant A (workbook task per item):

Inputs:
- mode: workbook
- in (array|string, required): Collection/expression to iterate over
- iterator (string, required): Item variable name
- task (string, required): Workbook task name
- with (object, optional): Inputs (may reference `{{ iterator }}`)
- as (string, optional): Aggregate results variable

Variant B (playbooks per item):

Inputs:
- mode: playbooks
- in (array|string, required)
- iterator (string, required)
- catalog_path (string, required)
- with (object, optional)
- parallel (boolean, optional)
- as (string, optional)

Outputs:
- Array of per-iteration results; saved under `as` if provided

Examples:
```yaml
- step: loop_task
  type: loop
  mode: workbook
  in: "{{ workload.user_ids }}"
  iterator: uid
  task: get_user
  with:
    id: "{{ uid }}"
  as: users
  next: end

- step: loop_playbooks
  type: loop
  mode: playbooks
  in: ["2025-09-01", "2025-09-02"]
  iterator: d
  catalog_path: workflows/daily/jobs
  with:
    job_date: "{{ d }}"
  parallel: true
  as: daily_runs
  next: end
```

---

## Template Context and Result References

### Global Template Namespace

NoETL uses Jinja2 templating throughout playbooks. The following namespaces are available in template expressions:

**Core Namespaces**:
- `{{ workload.field }}` - Global workflow variables defined in `workload:` section
- `{{ vars.var_name }}` - Stored variables extracted via `vars` blocks in previous steps
- `{{ step_name.field }}` - Results from completed steps (direct access)
- `{{ execution_id }}` - Current execution identifier

**Special Context**:
- `{{ result.field }}` - Current step's result (available in `vars` block for value extraction)

### Step Result References in Workflow

During workflow execution, completed step results are available in subsequent steps via Jinja2 templates:
- `{{ step_name }}` or `{{ step_name.result }}` - Full result object (envelope with `status`, `data`, `error`, `meta`)
- `{{ step_name.data }}` - Direct access to the data payload when step returns envelope structure
- `{{ step_name.field }}` - Simplified access to fields (server normalizes by extracting `.data` when present)

**Recommended Pattern**: Use `{{ step_name.field }}` for direct access - the server automatically normalizes results.

Example:
```yaml
- step: fetch_data
  tool: python
  code: |
    def main():
      return {"count": 42, "name": "test"}
  vars:
    # Extract variables using result namespace
    item_count: "{{ result.count }}"
    item_name: "{{ result.name }}"
  next: process

- step: process
  tool: python
  code: |
    def main(count, name):
      print(f"Processing {name} with count {count}")
  args:
    # Access extracted variables
    count: "{{ vars.item_count }}"
    name: "{{ vars.item_name }}"
    # Or access previous step directly
    direct_count: "{{ fetch_data.count }}"
```

### Sink Template Context (Result Unwrapping)

When a `sink:` block executes, the worker provides a **special context** where result envelopes are unwrapped for convenience:

**Available variables in sink templates:**
- **`result`** or **`data`**: Unwrapped step result data (the contents of the `data` field from the envelope)
- **`this`**: Full result envelope with `status`, `data`, `error`, `meta` fields
- **`workload`**: Global workflow variables
- **`execution_id`**: Current execution identifier
- Prior step results by name

**Important**: Use `{{ result }}` not `{{ result.data }}` in sink blocks, as the worker has already unwrapped the envelope.

✅ **Correct sink usage:**
```yaml
- step: generate
  tool: python
  code: |
    def main():
      return {"status": "success", "data": {"value": 123, "message": "hello"}}
  sink:
    tool: postgres
    table: outputs
    args:
      value: "{{ result.value }}"          # Direct field access
      message: "{{ result.message }}"      # Not result.data.message
      full_data: "{{ result }}"            # Full unwrapped data object
      status_check: "{{ this.status }}"    # Envelope metadata
```

❌ **Incorrect - double nesting:**
```yaml
sink:
  args:
    value: "{{ result.data.value }}"  # WRONG: result is already unwrapped
```

---

## Validation Summary

- `start` must define `next`.
- `end` must not define `next`.
- Each step type only accepts its own inputs/outputs as specified above.
- `next` may be a string or an array of step names. If omitted (and not `end`), the branch ends.
- Step names must be unique. References in `next` must exist.

---

## Minimal End-to-End Example

```yaml
apiVersion: noetl.io/v1
kind: Playbook
name: Minimal
path: workflows/examples/minimal
workflow:
  - step: start
    type: start
    next: ping

  - step: ping
    type: http
    method: GET
    endpoint: https://httpbin.org/get
    as: resp
    next: end

  - step: end
    type: end
```