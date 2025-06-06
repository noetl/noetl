# NoETL DSL Playbook Specification

## 1. Abstract Syntax
- This document defines the abstract syntax and semantics of the NoETL DSL. 
- The language structure is based on YAML and Jinja2 templates and models workflow logic using structured control flow, task invocation, context inheritance, and result evaluation.

### 1.1. Playbook Root Structure
```yaml
Playbook ::= {
  apiVersion: "noetl.io/v1",
  kind: "Playbook",
  name: <string>,
  path: <string>,
  workload: <object>,
  workflow: [<step_definition>+],
  workbook: [<task_definition>+]
```
- `"apiVersion"` and `"kind"` must be present.
- `"name"` and `"path"` must uniquely identify the playbook.

### 1.2. Workload (Static Task Library)
- Declares globally available input data (like API URLs, parameters, and input datasets).
- This data is immutable during runtime and referenced via Jinja2 templates
```yaml
Workload ::= Map<String, Value>
Value ::= String | Number | Boolean | Array<Value> | Map<String, Value>
```

### 1.3. Workflow (StepList and Step represent transitions of state machine)
```yaml
StepList ::= [ Step+ ]

Step ::= Map {
  "step": Identifier,
  "desc"?: String,
  "loop"?: LoopBlock,
  "with"?: ContextMap,
  "call"?: CallBlock,
  "next"?: TransitionList
}
```

#### 1.3.1. LoopBlock (Step-Level Loop)
```yaml
LoopBlock ::= Map {
  "in": JinjaExpression<String>,
  "iterator": Identifier
}
```
- `"loop"` is only allowed at the __step__ level.
- Executes a subgraph of step transitions per element in a list.
- The current element is accessible via the `"iterator"` name.  
- Example of a loop block:
  ```yaml
  loop:
    in: "{{ workload.cities }}"
    iterator: city
  ```
Each iteration receives:
- city injected into `with`
- Additional `with` context merged from the step definition

#### 1.3.2. CallBlock `"call"` from Step 
Defines Task Execution Semantics
```yaml
CallBlock ::= TaskInvocation
```
A `"call"` in a step:
- Refers to a single task defined in `workbook`
- Passes `with` context to the task
- Stores result in `task_name.result`

#### 1.3.3. TaskInvocation
```yaml
TaskInvocation ::= Map {
  "task": Identifier,
  "with"?: ContextMap
}
```
#### 1.3.4. TransitionList (Step Transition `"next"` Block)
```yaml
TransitionList ::= [ Transition+ ]
Transition ::= Map {
  "when"?: JinjaExpression<Boolean>,
  "then": [ StepReference+ ]
}
StepReference ::= Map {
  "step": Identifier,
  "with"?: ContextMap
}
```
- Transitions may be conditional using `"when"`.  
Example of a transition block:
```yaml
next:
  - when: <jinja_condition>
    then:
      - step: <step_name>
        with?: {...}
  - else:
      - step: <step_name>
        with?: {...}
```
- The `"next"` section defines control flow routing.
- `"when"` evaluates a condition using Jinja2.
- If `"when"` is missing, the clause is treated as `"else"`.
- A fallback `"else"` clause can be represented by omitting `"when"`.

#### 1.3.5. ContextMap
```yaml
ContextMap ::= Map<String, JinjaExpression>
```

### 1.4. Workbook TaskList (Static Task Library)
```yaml
TaskList ::= [ Task+ ]
Task ::= Map {
  "task": Identifier,
  "type": "task" | "http" | "python",
  "with"?: ContextMap,
  "run"?: TaskList,
  ... // type-specific fields
}
```
- The `"workbook"` is a statically defined list of named tasks. 
- Tasks are referable by name in the top-level scope only.  
```yaml
<task_library> ::= [ <task_definition>+ ]

```

#### 1.4.1. Global Tasks 
Tasks are defined at the top level and callable only by `call` in a step.
```yaml
- task: <task_name>
  type: "task" | "http" | "python"
  run?: [ <nested_task>+ ].
```

##### 1.4.1.1. `"run"` Nested Tasks (`"run"`) Inside Task
- Used to build composite tasks with local nested task logic
- Final result is taken from the last executed subtask
- A task can define a `"run"` list of inline tasks.
- These are executed in order or parallel (depending on executor).
- Tasks inside `"run"` __cannot__ reference other top-level tasks.
- The final task result in `"run"` is bubbled up to the parent.

### 1.4.2. Supported Task Types
##### 1.4.2.1. Composite Task Fields
```yaml
<task_definition> ::=
  {
    task: <task_name>,
    type: "http" | "python" | "loop" | "task",
    desc?: <string>,
    with?: { <key>: <quoted_template> },
    when?: <quoted_template>,
    run?: [ <task_definition>+ ],
    <task_type_specific_fields>
  }
```
- The `"task"` type serves as a __composite container__ for executing a nested list of tasks in order. It may be used in both top-level and nested `"run"`.
- A `"task"` with both `"type"` and `"run"` will:
  - Be executed according to its `"type"` if supported (e.g., `"http"`, `"python"`, `"loop"`).
  - Otherwise, if `"type": "task"`, it is treated as a composite task and will evaluate each nested task in `"run"` in order.
- `"task"`: A composite task that runs a list of nested tasks.
```yaml
- task: process_city_weather
  type: task
  run:
    - task: get_forecast
    - task: evaluate_weather
```

##### 1.4.2.2. HTTP Task Fields
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

##### 1.4.2.3. Python Task Fields
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
  - A `"task"` with both `"type"` and `"run"` will:
    - Be executed according to its `"type"` if supported.
    - Or be treated as a composite if `"type": "task"`.
- `"loop"` is a valid task type; it internally runs one or more other tasks, using `"in"` and `"iterator"` field.
- Templated expressions (Jinja2) must be wrapped in `{{ ... }}` and appear only in string fields.
- `"run"` in a workflow `"step"` triggers execution of one or more tasks, optionally passing `"with"` context.
- `"next"` defines transition logic between steps; conditional routing is based on Jinja2-expressed conditions.
- `"with"` in steps and tasks injects dynamic input scoped to execution context.
### 2.1. Execution Flow

- Workflow starts at step with `"step: start"`.
- Each step optionally applies a `"with"` context.
- If `"loop"` is defined, the step is executed per iteration.
- If `"call"` is used, the specified task is invoked.
- Task execution may contain inline `"run"` blocks for nesting.
- Task output is captured in the calling context as `"task_name.result"`.
- `"next"` transitions use Jinja-based conditions to route control.
- Execution ends when `"step: end"` is reached.

### 2.2. Scope

- `"with"` defines local context for a `"step"` or `"task"`.
- Loop iterator values are injected into context.
- Results from tasks are accessible in subsequent steps.
- Nested `"run"` results bubble up to the parent task and into the workflow context.

## 3. Reserved Names
- `"start"`: entry point of the workflow
- `"end"`: terminates the workflow execution

## 4. Validation Constraints

- Each step must have a unique `"step"` name.
- Each top-level `"task"` must have a unique "task"` name.
- Only one `"call"` is allowed per step.
- `"loop"` is allowed only in steps, not in tasks.
- `"run"` may be used only inside task definitions.
- `"task"` under `"run"` may not reference top-level tasks.
- Loop handling strictly at the step level
- Task invocation using `"call"` from steps
- Context passing with `"with"`
- Inline nested tasks using `"run"`
- The result is bubbling from nested tasks to parent tasks to workflow steps
- Transition logic using `"next"`, `"when"`, `"then"`, `"else"`

## 5. Result Handling
- Result of a `"call"` is bound to the task name
- Nested `"run"` results bubble up to their parent
- Step `"with"` can access any available context, including `"previous_task.result.key"` within the step

## 6. Conformance
An implementation is conformant if:  
- It validates playbooks as YAML + Jinja2 expressions.
- It executes tasks respecting `"type"` semantics.
- It performs transitions as specified in `"workflow"`.
- It maintains scoped `"context"` and `"result"` hierarchies.
- It preserves deterministic resolution of top-level task names.

## 6. Playbook Example with Loops and Calls

- [**data/catalog/playbooks/weather_loop_chain_example.yaml**](../data/catalog/playbooks/weather_loop_chain_example.yaml)

## 7. Execution Model
- The playbook starts at the `"step": "start"`.
- Each step executes its `"call"` (if defined).
- Step results are available via `"with"` and can affect routing in `"next"`.
- Step loop iterate and aggregate results per item into a list.
- Errors may be handled via transitions to `"error_handler"` steps.
- The workflow ends at the `"step": "end"` or when no further steps are defined.

## 8. Notes
- Jinja2 expressions must be inside quoted strings: `"{{ expression }}"`
- Errors are not caught implicitly unless on_error is specified.
- The language is deterministic and context-driven.
- External I/O is only supported via tasks of type http, python, etc.
- Loops: step-level only
- Calls: only 1 task per step
- Task invocation is explicit via `"call"`
- Step-to-step data flow via `"with"`
- Scopes are template-driven
- Nested tasks execute in isolation and return to parent task
- `"run"` allows defining task chains without polluting global scope
