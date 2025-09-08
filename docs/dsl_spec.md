# NoETL DSL Design Specification (Step Widgets v2)

## Overview

The NoETL DSL defines workflows as a sequence of typed steps (widgets). Each step type has its own inputs, outputs, and execution semantics. Playbooks are YAML/JSON documents validated against the schema in `docs/playbook-schema.json`.

This revision replaces the previous "run/rule/case" model with explicit step types:
- start — Entry point of a workflow. Must route to the first executable step via `next`.
- end — Terminal step. No `next`. Used broadly.
- workbook — Invokes a named task from the workbook library; use `task:` and `with:` to pass inputs.
- python — Runs inline Python in the step itself.
- http — Makes an HTTP call directly from a step (method, endpoint, headers, params/payload).
- duckdb — Executes DuckDB SQL/script in the step.
- postgres — Executes PostgreSQL SQL/script in the step.
- secrets — Reads a secret from a provider (e.g., Google Secret Manager) and exposes it as `secret_value` (or a custom alias).
- playbooks — Executes all playbooks under a catalog path, forwarding inputs via `with:`; the step result can be passed on to the next step.
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
- Inputs/Outputs: Vary by type as defined below.

General execution:
- Steps execute in order by following `next`.
- A step may optionally publish outputs to the playbook context under a variable name (see `as:` below).
- If a step has no `next` and is not `end`, the branch terminates implicitly.

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
- with (object, optional): Inputs forwarded to the task
- as (string, optional): Variable name to store the task result

Outputs:
- Result of the task, stored under `context[as]` if `as` is provided, else available as step-local `result`

Example:
```yaml
- step: fetch_weather
  type: workbook
  task: get_weather
  with:
    city: "Paris"
  as: weather
  next: end
```

### python
Execute inline Python code.

Inputs:
- code (string, required): Python code to execute
- with (object, optional): Variables to inject into the code context
- as (string, optional): Variable name to store the result

Outputs:
- `result` from the last expression or explicit `return` in the code block; saved under `as` if provided

Example:
```yaml
- step: compute_score
  type: python
  with:
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
  type: duckdb
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