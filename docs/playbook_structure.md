# NoETL Playbook Structure Guide

NoETL playbooks are YAML manifests that the platform renders with Jinja2 before executing. Every string value can interpolate data from the runtime context (`workload`, payload inputs, iterator state, previous step results, and execution metadata). This document summarises the canonical structure using the maintained fixtures:

- `tests/fixtures/playbooks/control_flow_workbook/control_flow_workbook.yaml`
- `tests/fixtures/playbooks/http_duckdb_postgres/http_duckdb_postgres.yaml`
- `tests/fixtures/playbooks/playbook_composition/playbook_composition.yaml`
- `tests/fixtures/playbooks/playbook_composition/user_profile_scorer.yaml`

## Core Sections

### metadata (required)
Contains descriptive information that uniquely identifies the playbook in the catalog.

```yaml
metadata:
  name: control_flow_workbook
  path: tests/fixtures/playbooks/control_flow_workbook
  version: "1.0.0"           # optional
  description: "Control-flow routing example"
```

### workload (required)
Declares global variables merged with the payload supplied at execution time. The merge is deep so you can override nested keys in the request body.

```yaml
workload:
  message: "HTTP -> DuckDB -> Postgres pipeline"
  base_url: https://api.open-meteo.com/v1
  cities:
    - name: London
      lat: 51.51
      lon: -0.13
```

### workbook (optional, recommended)
A library of reusable, named action definitions. Workflow steps use `type: workbook` plus a `name` to reference these entries. Workbook tasks can use any action type except `workbook` (to avoid recursion).

```yaml
workbook:
  - name: compute_flag
    type: python
    code: |
      def main(temperature_c):
          is_hot = float(temperature_c) >= 25.0
          msg = "hot" if is_hot else "cold"
          return {"is_hot": is_hot, "message": msg}
```

### workflow (required)
An ordered list of steps. Exactly one step must be named `start` (entry point) and one step must be named `end` (terminal aggregation).

Each step supports the following attributes:

- `step` (**required**): unique identifier inside the workflow.
- `desc` (optional): documentation string.
- `type`: action to execute (`workbook`, `python`, `http`, `postgres`, `duckdb`, `playbook`, `iterator`, etc.).
- `name`: when `type: workbook`, identifies the workbook task to invoke.
- `data`: object rendered with Jinja2 and passed as inputs to the action.
- `auth`: optional authentication/credential reference (string alias or object).
- `save`: optional post-processing block that forwards action results to another storage-oriented action.
- `next`: routing rules to subsequent steps.

`start` acts as a router. It typically omits a `type` and only defines `next` transitions.

`end` is required in every workflow so orchestrators know when to finish, publish results upstream, and unwind nested playbook calls.

## Routing with `next`

Steps define routing rules with the `next` list. Each item can be:

1. A direct transition (`step` plus optional `data`).
2. A conditional branch with `when` and `then` (list of targets).
3. A fallback branch using `else`.

Targets in `then`/`else` can also include `data` to pass different payloads forward.

```yaml
- step: start
  desc: Start Weather Analysis Workflow
  next:
    - when: "{{ workload.state == 'ready' }}"
      then:
        - step: city_loop
    - else:
        - step: end

- step: city_loop
  type: iterator
  collection: "{{ workload.cities }}"
  element: city
  task:
    task: fetch_and_store_weather
    type: workbook
    name: fetch_weather
  next:
    - data:
        alerts: "{{ city_loop.results }}"
      step: aggregate_alerts
```

## Action Types

### type: workbook
Routes to a named workbook task. The step may attach additional `data` specific to the invocation.

```yaml
- step: eval_flag
  type: workbook
  name: compute_flag
  data:
    temperature_c: "{{ workload.temperature_c }}"
  next:
    - when: "{{ result.is_hot }}"
      step: hot_path
    - else:
      - step: cold_path
```

### type: python
Executes inline Python code that must expose a `def main(input_data):` entry point. The arguments correspond to keys defined in `data`.

```yaml
- step: calculate_threshold
  type: python
  data:
    readings: "{{ workload.readings }}"
  code: |
    def main(readings):
        avg = sum(readings) / len(readings)
        return {"average": avg}
```

### type: playbook
Composes another playbook. Execution waits for the child to finish. Use `return_step` in the child to aggregate what the parent should receive.

```yaml
- step: score_user
  type: playbook
  path: tests/fixtures/playbooks/playbook_composition/user_profile_scorer.yaml
  data:
    user_data: "{{ user }}"
  save:
    storage: postgres
    auth: pg_k8s
    table: public.user_profile_results
    data:
      id: "{{ execution_id }}:{{ user.name }}"
      profile_score: "{{ result.profile_score }}"
```

### type: iterator
Iterates over a collection. The iterator executes the nested `task` for every element and can run sequentially or in parallel.

```yaml
- step: process_users
  type: iterator
  collection: "{{ workload.users }}"
  element: user
  mode: sequential
  task:
    task: process_user
    type: playbook
    path: tests/fixtures/playbooks/playbook_composition/user_profile_scorer.yaml
    data:
      user_data: "{{ user }}"
```

## Persisting and Returning Results

Any action type can declare a `save` block to fan the step output into another action (e.g., Postgres, DuckDB, HTTP). Actions also return their result into the workflow context. Subsequent steps reference those values via `{{ step_name.result }}` (or iterator aliases such as `{{ this }}` inside loops).

```yaml
save:
  storage: postgres
  auth: pg_local
  table: public.weather_http_raw
  mode: upsert
  key: id
  data:
    id: "{{ execution_id }}:{{ city.name }}"
    payload: "{{ result.payload }}"
```

## Authentication (`auth`)

Steps and workbook tasks can attach an `auth` block. It can be a shorthand credential alias or a structured object, depending on the plugin. The execution engine injects the resolved credentials before running the action.

```yaml
- step: ensure_pg_table
  type: postgres
  auth: pg_local
  command: |
    CREATE TABLE IF NOT EXISTS public.weather_http_raw (...);
```

## Summary Checklist

1. Use Jinja2 templating for dynamic values and runtime context substitution.
2. Declare a `metadata` block with at least `name` and `path`.
3. Describe global defaults in `workload`; they merge with the execution payload.
4. Capture reusable actions in `workbook` and invoke them through workflow steps.
5. Model the execution graph in `workflow` with a `start` router and a terminal `end` step.
6. Give every step a meaningful `type`; `workbook` steps must include `name`.
7. Use `next` with `when`/`then`/`else` to branch and forward data.
8. Add `save` blocks to persist outputs and `auth` to point at credentials.
9. Ensure `end` aggregates or returns data needed by parent playbooks.
