# NoETL DSL Playbook Specification

## 1. Abstract Syntax
- This document defines the abstract syntax and semantics of the NoETL DSL. 
- The language structure is based on YAML and Jinja2 templates and models workflow logic using structured control flow, task invocation, context inheritance, and result evaluation.

### 1.1. Playbook Root Structure
```yaml
Playbook ::=
  "apiVersion": "noetl.io/v1",
  "kind": "Playbook",
  "name": String,
  "path": String,
  "workload": Workload,
  "workflow": StepList,
  "workbook": TaskList
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
  "join"?: Identifier,
  "with"?: ContextMap,
  "call"?: CallBlock,
  "run"?: TaskInvocationList,
  "next"?: TransitionList
}
```

#### 1.3.1. LoopBlock (Step-Level Loop)
```yaml
LoopBlock ::= Map {
  "in": JinjaExpression<String>,
  "iterator": Identifier,
  "join": Identifier
}
```
- `"loop"` is only allowed at the __step__ level.
- Executes a subgraph of step transitions per element in a list.
- The current element is accessible via the `"iterator"` name.  
- `"join"` is __required__ and specifies the aggregation step to transition to after all iterations.
- Use `"join: end"` to indicate terminal non-aggregating loops.
- Example of a loop block:
```yaml
loop:
  in: "{{ workload.cities }}"
  iterator: city
  join: aggregate_alerts
```
Each iteration receives:
- city injected into `with`
- Additional `with` context merged from the step definition

#### 1.3.2. Join Logic (Aggregation after Loop) 
```yaml
Join ::= Identifier
```
- `"join"` signals the engine to wait for all branches (iterations) to finish and pass collected results to the referenced step.
- The target `"join"` step receives an aggregated list of results in `"join_results"`.
- To indicate no aggregation is required, set `"join: end`" in the `"loop"`.
- Example:
```yaml 
- step: aggregate_alerts
  join: city_loop
  with:
    alerts: "{{ join_results }}"
```

#### 1.3.3. CallBlock `"call"` from Step 
Defines Task Execution Semantics
```yaml
CallBlock ::= Map {
  "task": Identifier,
  "with"?: ContextMap
}
```
A `"call"` in a step:
- Refers to a single task defined in `workbook`
- Passes `with` context to the task
- Stores result in `task_name.result`

#### 1.3.4. TaskInvocationList
```yaml
TaskInvocationList ::= [ TaskInvocation+ ]
TaskInvocation ::= Map {
  "task": Identifier,
  "with"?: ContextMap
}
```
#### 1.3.5. TransitionList (Step Transition `"next"` Block)
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

#### 1.3.6. ContextMap
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

#### 1.4.1. Global Tasks 
Tasks are defined at the top level and callable only by `call` in a step.
```yaml
- task: <task_name>
  type: "task" | "http" | "python"
  run?: [ <nested_task>+ ]
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
    type: "http" | "python" | "loop" | "task",
    desc?: <string>,
    with?: { <key>: <quoted_template> },
    when?: <quoted_template>,
    run?: [ <task_definition>+ ],
    <task_type_specific_fields>
  }
```
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
