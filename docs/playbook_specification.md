# NoETL DSL Playbook Specification (Widget-based)

This specification defines the NoETL DSL using typed step widgets. Each widget has distinct inputs/outputs and execution semantics. Control flow is defined with simple `next` pointers between steps.

## 1. Playbook Root Structure
```yaml
Playbook ::=
  apiVersion: "noetl.io/v1"
  kind: "Playbook"
  name: String
  path: String
  environment?: Map<String, Any>
  context?: Map<String, Any>
  workbook?: TaskList     # Library of reusable tasks for `workbook` steps
  workflow: StepList      # Sequence/graph of typed steps (widgets)
```

## 2. Workflow (Step Widgets)
```yaml
StepList ::= [ Step+ ]

Step ::= Map {
  step: Identifier,
  type: "start" | "end" | "workbook" | "python" | "http" | "duckdb" | "postgres" | "secrets" | "playbooks" | "loop",
  next?: Identifier | [Identifier+],    # Not allowed for `end`. Required for `start`.
  ...type-specific fields
}
```

Execution semantics:
- Start at the step with `type: start` (must define `next`).
- Follow `next` edges; missing `next` ends the branch implicitly.
- `type: end` is terminal and must not define `next`.
- Each widget accepts only its own fields; structures are not uniform.
- Widgets may publish results into context via `as:`.

### 2.1 start
Inputs: none
Outputs: none
Constraints: Must define `next`.
```yaml
- step: start
  type: start
  next: fetch
```

### 2.2 end
Inputs: none
Outputs: none
Constraints: Must not define `next`.
```yaml
- step: end
  type: end
```

### 2.3 workbook
Invokes a named task from the top-level `workbook` library.
```yaml
- step: fetch
  type: workbook
  task: get_weather            # required
  with?: Map                    # optional inputs
  as?: Identifier               # optional variable to store result
  next?: Identifier
```
Result: Task result saved under `as` if provided, else available as step-local `result`.

### 2.4 python
Executes inline Python code.
```yaml
- step: compute
  type: python
  with?: Map
  code: |                      # required
    total = a + b
    return {"sum": total}
  as?: Identifier
  next?: Identifier
```
Result: Last expression or explicit `return` value; saved under `as` if provided.

### 2.5 http
Makes an HTTP call directly from a step.
```yaml
- step: get_user
  type: http
  method: GET|POST|PUT|DELETE|PATCH  # required
  endpoint: String                   # required
  headers?: Map
  params?: Map
  body?: Any
  timeout?: Number
  verify?: Boolean
  as?: Identifier
  next?: Identifier
```
Result: Response object with `status`, `headers`, `body`, and parsed `json` (if available); saved under `as` if provided.

### 2.6 duckdb
Executes DuckDB SQL/script.
```yaml
- step: transform
  type: duckdb
  script: String | MultilineSQL  # required
  files?: [String]
  as?: Identifier
  next?: Identifier
```
Result: Result set (if any); saved under `as` if provided.

### 2.7 postgres
Executes PostgreSQL SQL/script.
```yaml
- step: query
  type: postgres
  sql: String | MultilineSQL     # required
  connection?: String            # DSN/URL
  db_host?: String
  db_port?: Number
  db_user?: String
  db_password?: String
  db_name?: String
  db_schema?: String
  as?: Identifier
  next?: Identifier
```
Result: Result set (if any) or `rowcount`; saved under `as` if provided.

### 2.8 secrets
Reads a secret from a provider and exposes it in context.
```yaml
- step: get_key
  type: secrets
  provider: gcp|aws|azure|vault|env  # required
  name: String                       # required
  project?: String
  version?: String|Number
  as?: Identifier                    # default: secret_value
  next?: Identifier
```
Result: Secret string saved under `as` (default `secret_value`).

### 2.9 playbooks
Executes all playbooks under a catalog path.
```yaml
- step: run_catalog
  type: playbooks
  catalog_path: String     # required
  with?: Map
  parallel?: Boolean
  as?: Identifier
  next?: Identifier
```
Result: Array of child playbook results; saved under `as` if provided.

### 2.10 loop
Iterates over a collection and either calls a workbook task per item or runs sub-playbooks per item.

Variant A (workbook):
```yaml
- step: loop_task
  type: loop
  mode: workbook           # required
  in: Array|Expression     # required
  iterator: Identifier     # required
  task: String             # required (workbook task name)
  with?: Map               # may reference iterator variable
  as?: Identifier          # aggregate results
  next?: Identifier
```

Variant B (playbooks):
```yaml
- step: loop_playbooks
  type: loop
  mode: playbooks
  in: Array|Expression
  iterator: Identifier
  catalog_path: String
  with?: Map
  parallel?: Boolean
  as?: Identifier
  next?: Identifier
```

Result: Array of per-iteration results; saved under `as` if provided.

## 3. Workbook (Task Library)
```yaml
TaskList ::= [ Task+ ]
Task ::= Map {
  task: Identifier,
  type: "python" | "http" | "runner" | "duckdb" | "postgres" | "secrets",
  desc?: String,
  code?: String,            # for python
  method?: String,          # for http
  endpoint?: String,        # for http
  params?: Map,             # for http
  sql?: String,             # for postgres
  script?: String,          # for duckdb
  ...
}
```
Tasks are reusable units referenced by `workbook` steps via `task:`.

## 4. Validation Constraints
- `start` must have `next`.
- `end` must not have `next`.
- Step names must be unique; all `next` references must exist.
- Each step type accepts only its defined fields; mixing unrelated fields is invalid.
- `loop.mode` must be `workbook` or `playbooks` and include required fields per mode.

## 5. Minimal Example
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
