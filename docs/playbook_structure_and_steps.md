# Playbook Structure

## Header

Every playbook starts with a fixed header and three logical sections. All strings can use Jinja2 templating.

```yaml
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: example_playbook
  path: examples/example_playbook
workload: {}
workflow: []
workbook: []
```

## Workload

`workload` is an object that stores global defaults. It is merged with the payload submitted when the playbook execution is registered. Use it for constants, feature toggles, or default inputs.

```yaml
workload:
  pg_host: "{{ env.POSTGRES_HOST | default('localhost') }}"
  cities:
    - name: "London"
      lat: 51.51
      lon: -0.13
    - name: "Paris"
      lat: 48.85
      lon: 2.35
```

## Workflow

`workflow` is an ordered list of steps. Each step:

- has a unique `step` name.
- declares a `type` that matches an action implementation (`workbook`, `python`, `http`, `duckdb`, `postgres`, `playbook`, `iterator`, `secrets`, etc.).
- can define `data`, `auth`, `save`, and `next` attributes.

### Routing

Use `next` to move between steps. Each entry in `next` can be a direct transition or a conditional block.

```yaml
- step: start
  next:
    - when: "{{ workload.state == 'ready' }}"
      then:
        - step: fetch_data
    - else:
        - step: end
```

### Passing Data Forward

Use `args` to pass data to actions. Attach it to either the step itself (inputs to the action) or to the `next` target (payload override for the downstream step).

```yaml
- step: aggregate_alerts
  tool: workbook
  name: consolidate_alerts
  next:
    - args:
        alerts: "{{ city_loop.results }}"
      step: persist_alerts
```

## Workbook

`workbook` hosts reusable actions referenced from steps. Every entry requires `name` and `tool` and may include tool-specific settings (`code`, `endpoint`, `command`, etc.). Workbook tasks can use the same action tools as steps except `workbook`.

```yaml
workbook:
  - name: fetch_weather
    tool: http
    method: GET
    endpoint: "{{ workload.base_url }}/forecast"
    params:
      latitude: "{{ city.lat }}"
      longitude: "{{ city.lon }}"
```

## Step Types Overview

- **start** – Entry router. Defines only `next` transitions.
- **end** – Terminal aggregator. Optionally collates results or triggers `save` logic.
- **workbook** – Invokes a named workbook action (requires `name` and `tool: workbook`).
- **python** – Runs inline Python via `def main(...)` using variables from `args`.
- **http** – Calls an HTTP endpoint (method, endpoint, headers, payload).
- **duckdb / postgres** – Execute SQL or scripts in the respective engines.
- **secrets** – Resolve secrets into the workflow context.
- **playbook** – Calls a child playbook and waits for completion.
- **iterator** – Loops through a collection using a nested `task` definition.

## Python Step

```yaml
- step: score_user
  tool: python
  args:
    payload: "{{ workload.user }}"
  code: |
    def main(payload):
        return {"score": payload.get("metric", 0)}
  next:
    - step: end
```

## DuckDB Step

```yaml
- step: aggregate_metrics
  tool: duckdb
  command: |
    INSTALL postgres; LOAD postgres;
    ATTACH '{{ workload.pg_conn }}' AS pgdb (TYPE POSTGRES);
    CREATE TABLE IF NOT EXISTS metrics AS
    SELECT * FROM pgdb.public.source_metrics;
  sink:
    tool: duckdb
    path: "{{ workload.output_db }}"
  next:
    - step: end
```

## Iterator Step

```yaml
- step: process_users
  tool: iterator
  collection: "{{ workload.users }}"
  element: user
  mode: sequential
  task:
    task: process_user
    tool: playbook
    path: tests/fixtures/playbooks/playbook_composition/user_profile_scorer.yaml
    args:
      user_data: "{{ user }}"
```

## Save Blocks

To persist results, attach a `save` block. It dispatches the step output to another storage action type (e.g., Postgres, DuckDB, HTTP).

**Important**: Save operates as a single transaction - if the save operation fails, the entire action type reports failure.

### New Structure (Recommended)

```yaml
sink:
  type: postgres
  data:
    id: "{{ execution_id }}:{{ city.name }}:{{ http_loop.result_index }}"
    execution_id: "{{ execution_id }}"
    city: "{{ city.name }}"
    payload: "{{ (this.data | tojson) if this is defined and this.data is defined else '' }}"
  auth: "{{ workload.pg_auth }}"
  table: public.weather_http_raw
  mode: upsert
  key: id
```

### Legacy Structure (Still Supported)

```yaml
sink:
  tool: postgres
  auth: pg_local
  table: public.weather_http_raw
  mode: upsert
  key: id
  data:
    id: "{{ execution_id }}:{{ city.name }}"
    payload: "{{ result.payload }}"
```

### Key Points

- The `save` block defines a single storage object with `type` (or `storage` for legacy)
- Save failures cause the entire action type to fail, ensuring data consistency
- Use `this.data` to reference the current action's result in template expressions
- Supported storage types: `postgres`, `duckdb`, `http`, `python`

## Checklist

1. Define `metadata` with `name` and `path`.
2. Populate `workload` with defaults; expect runtime payloads to merge into it.
3. (Optionally) create `workbook` tasks for reusable actions.
4. Model `workflow` with a `start` router, actionable steps, and an `end` aggregator.
5. Give every step a `type`, and provide `name` when targeting the workbook.
6. Use `next` with `when`/`then`/`else` to branch and forward `data`.
7. Add `save` whenever a step needs to hand its output to storage.
