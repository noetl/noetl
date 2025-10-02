# NoETL Playbook Structure Guide (Widget-based)

This guide explains the structure and components of NoETL playbooks using the new widget-based steps.

## Overview

NoETL playbooks are YAML files that define workflows for data processing and automation. A playbook consists of several main sections:

- Metadata: Information about the playbook itself
- Workload: Input data and parameters for the workflow
- Workbook: Library of reusable tasks (referenced by workbook steps)
- Workflow: A list of typed steps (widgets)

## Basic Structure

```yaml
# Metadata
version: "1.0.0"
path: "workflows/example/playbooks"
description: "Example playbooks"

# Workload (input data and parameters)
workload:
  param1: "value1"
  param2: "value2"

# Workbook (reusable tasks for `workbook` steps)
workbook:
  - task: get_weather
    type: http
    desc: Weather by city
    method: GET
    endpoint: "https://api.example.com/weather"

# Workflow (typed steps)
workflow:
  - step: start
    type: start
    next: fetch_weather

  - step: fetch_weather
    type: workbook
    task: get_weather
    with:
      city: "Paris"
    as: weather
    next: end

  - step: end
    type: end
```

## Sections

### Metadata
- version/name/path/description remain as before, plus required apiVersion/kind.

### Workload
- Free-form inputs available to steps via templating.

### Workbook
- A library of reusable tasks that can be called from `workbook` steps by `task:` name.

## Workflow (Step Widgets)

Each step:
- step: Unique name
- type: One of start | end | workbook | python | http | duckdb | postgres | secrets | playbooks | loop
- next: Next step name (string) when applicable; not allowed for `end`.
- Each type has its own inputs/outputs; they are not the same structure.

Below are examples for each widget.

### start
```yaml
version: "1.0.0"
path: "workflows/example/playbooks"
description: "Example playbooks of basic functionality"
author: "John Doe"
tags:
  - "example"
  - "basic"
```

### end
```yaml
- step: end
  type: end
```

### workbook
```yaml
- step: fetch_weather
  type: workbook
  task: get_weather
  with:
    city: "{{ workload.city }}"
  as: weather
  next: end
```

### python
```yaml
- step: compute
  type: python
  with:
    a: 2
    b: 3
  code: |
    total = a + b
    return {"sum": total}
  as: math
  next: end
```

### http
```yaml
- step: call_service
  type: http
  method: GET
  endpoint: "https://httpbin.org/get"
  headers:
    X-Trace: "123"
  params:
    user: "{{ workload.user_id }}"
  as: resp
  next: end
```

Tip (exact-match OR): to match any of several exact values (complete match), prefer list membership:

```yaml
- step: choose_file_branch
  next:
    - when: "{{ workload.filename in ['error_log.json', 'event_log.json', 'queue.json'] }}"
      then:
        - step: handle_known_file
    - else:
        - step: handle_other_file
```

See also: [Query Conditions: Exact/Complete Match with OR](query_conditions.md)


### postgres
```yaml
- step: query_pg
  type: postgres
  connection: "{{ environment.postgres_url }}"
  sql: |
    SELECT id, email FROM users LIMIT 5;
  as: users
  next: end
```

### secrets
```yaml
- step: get_secret
  type: secrets
  provider: gcp
  project: my-project
  name: OPENAI_API_KEY
  as: openai_api_key
  next: end
```

### playbooks
```yaml
- step: run_catalog
  type: playbooks
  catalog_path: workflows/daily/jobs
  with:
    job_date: "{{ today() }}"
  parallel: true
  as: results
  next: end
```

### loop
- Mode workbook: iterate calling a workbook `task:` per item
- Mode playbooks: iterate running sub-playbooks for each item

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

- step: loop_catalog
  type: loop
  mode: playbooks
  in: ["2025-09-01", "2025-09-02"]
  iterator: d
  catalog_path: workflows/daily/jobs
  with:
    job_date: "{{ d }}"
  parallel: true
  as: runs
  next: end
```

## Notes
- start must have next; end must not have next.
- Each widget has its own inputs/outputs; do not use a uniform structure.
- Use `as:` to persist a step’s result into context for subsequent steps.
