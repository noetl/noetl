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

#### 1.3.1. Iterator Task (Step-Level Iteration)
```yaml
IteratorTask ::= Map {
  "type": "iterator",
  "collection": JinjaExpression<String|Array>,
  "element": Identifier,
  "task": TaskDefinition,
  "save"?: SaveBlock
}
```
- Iteration is modeled as a dedicated step with `type: iterator`.
- The current element is exposed under the provided `element` name and is also available in the nested task context.
- `collection` must resolve to an array (or a scalar that will be treated as a single-item list).
- The nested `task` executes once per element; its own `save` can persist per-item results; the step-level `save` can persist aggregated results.
- Example of an iterator step:
```yaml
- step: city_loop
  type: iterator
  collection: "{{ workload.cities }}"
  element: city
  task:
    type: http
    endpoint: "{{ workload.base_url }}/forecast"
    params:
      latitude:  "{{ city.lat }}"
      longitude: "{{ city.lon }}"
  next:
    - step: aggregate_alerts
```

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

##### 1.4.1.1. `"run"` Nested Tasks
- Final result is taken from the last executed subtask
- Cannot reference top-level tasks
- A task can define a `"run"` list of inline tasks.
- These are executed in order.
- The final task result in `"run"` is bubbled up to the parent.

### 1.4.2. Supported Task Types
##### 1.4.2.1. Composite Task
```yaml
<task_definition> ::=
  {
    task: <task_name>,
    type: "http" | "python" | "task",
    desc?: <string>,
    with?: { <key>: <quoted_template> },
    when?: <quoted_template>,
    run?: [ <task_definition>+ ],
    <task_type_specific_fields>
  }
```
- A `"task"` with both `"type"` and `"run"` will:
  - Be executed according to its `"type"` if supported (e.g., `"http"`, `"python"`).
  - Otherwise, if `"type": "task"`, it is treated as a composite task and will evaluate each nested task in `"run"` in order.
- `"task"`: A composite task that runs a list of nested tasks.
```yaml
- task: process_city_weather
  type: task
  run:
    - task: get_forecast
    - task: evaluate_weather
```

##### 1.4.2.2. HTTP Task
```yaml
HTTPTask ::= Map {
  "method": "GET" | "POST" | "PUT" | "DELETE",
  "endpoint": JinjaExpression,
  "params"?: ContextMap,
  "payload"?: JinjaExpression | ContextMap,
  "retry"?: Number,
  "retry_delay"?: Number,
  "on_error"?: "continue" | "fail"
}
```

- `"http"`: Executes an HTTP request.
```yaml
- task: get_forecast
  type: http
  method: GET
  endpoint: "{{ base_url }}/forecast"
  params: { ... } 
```

##### 1.4.2.3. Python Task
```yaml
PythonTask ::= Map {
  "code": PythonFunctionString
}
```
- `"python"`: Executes a Python function.
```yaml
- task: evaluate_weather
  type: python
  with: { forecast_data: "..." }
  code: |
    def main(forecast_data):
        return { "alert": True }
```
## 2. Semantics
- Tasks in `"workbook"` are statically declared and cannot be nested referentially.
  - Any `"task"` may contain a `"run"` clause consisting of _inline, locally scoped_ tasks.
  - Tasks defined inside `"run"` __are not globally referable__ (they're not in the top-level `"workbook"`).
  - Nested tasks can themselves define a `"run"`, enabling recursive structures.
- Step `"loop"` executes a chain of transitions per item.
- Conditional `"next"` applies per iteration.
- Aggregation is handled via `"join"` with collected `"join_results"` context.
- Use `"join: end"` to terminate loop branches independently without aggregation.
- `"next"` defines transition logic between steps; conditional routing is based on Jinja2-expressed conditions.

## 3. Execution Flow

- Workflow starts at step with `"step: start"`.
- Each step optionally applies a `"with"` context.
- If `"loop"` is defined, the step is executed per iteration.
- If `"call"` is used, the specified task is invoked.
- Task execution may contain inline `"run"` blocks for nesting.
- Step's tasks' output is captured in the calling context as `"task_name.result"`.
- `"next"` transitions use Jinja-based conditions to route control.
- Execution ends when `"step: end"` is reached.

## 4. Execution Semantics for Tasks and Steps
- __Parallel Execution:__
  - Subtasks defined at the same level under `"run"` are executed in parallel.
  - Multiple steps listed under the same `"next"` transition (e.g., in `"then"`) are also executed in parallel.
- __Sequential Execution:__
  - Nested `"run"` blocks: A subtask that has its own `"run"` block will wait for the outer task to complete, then execute its nested tasks in sequence.

- __Example Interpretation:__
  ```yaml
  run:
    - task: A       # Starts in parallel
    - task: B       # Starts in parallel
      run:
        - task: C   # Executes after B completes (sequential to B) 
  ```
  - `A` and `B` run in parallel.
  - `C` runs after `B` completes, sequentially nested.

## 5. Scope

- `"with"` defines local context for a `"step"` or `"task"`.
- Loop iterator values are injected into context.
- Results from tasks are passed into subsequent steps using `"with"`.
- Nested `"run"` results bubble up to the parent task and into the step context.

## 6. Reserved Names
- `"start"`: entry point of the workflow
- `"end"`: terminates the workflow execution

## 7. Validation Constraints

- Unique `"step"` and `"task"` names.
- Only one task `"call"` per step.
- `"loop"` allowed only in steps.
- `"run"` may be used only inside task definitions.
- Task `"run"` cannot reference top-level tasks.
- Loop handling strictly at the step level.
- Task invocation using `"call"` from steps.
- Context passing with `"with"`.
- Inline nested tasks using `"run"`.
- Step transition routing via `"next"`, `"when"`, `"then"`, `"else"`.

## 8. Result Handling
- `"call"` result is bound to task name.
- `"run"` bubbles last task result up.
- `"join"` receives `"join_results`" as `list`

## 9. Conformance
- Validates playbooks as YAML + Jinja2 expressions.
- Executes task types correctly.
- Supports loop, call, join transitions.
- Maintains context scoping and result propagation.
- Preserves deterministic resolution of top-level task names.

## 10. Playbook Example with Loops and Calls

- [**data/catalog/playbooks/weather_loop_chain_example.yaml**](../catalog/playbooks/weather_loop_chain_commented_example.yaml)

## 11. Execution Model
- Start at step `"start"`
- If `"loop"` exists, execute transitions per item
- Each iteration result is routed by `"next"`
- After loop finishes, transition to the `"join"` step
- The `"join"` step receives `"join_results"` with all iteration outputs
- If `"join: end"` is declared, loop is terminal and non-aggregating
- Each step may `"call"` a task
- Task `"run"` executes nested logic
- End at step `"end"`

## 12. Notes
- Jinja2 expressions inside quoted strings: `"{{ expression }}"`
- Errors not caught unless on_error is specified.
- Deterministic and context-driven model.
- External I/O via typed tasks.
- Aggregation supported using `"join"` (required) or explicitly terminated with `"join: end"`.
- Calls: only one task per step.
- Task invocation is explicit via `"call"`.
- Step-to-step data flow via `"next"`.
- Scopes are template-driven.
- Nested tasks execute in isolation and return to parent task.
- `"run"` allows defining task chains without polluting global scope.
