# NoETL Playbook Specification

## 1. General Structure
```yaml
Playbook ::= {
  apiVersion: "noetl.io/v1",
  kind: "Playbook",
  name: <string>,
  path: <string>,
  workload: <workload_definition>,
  workbook: <task_library>,
  workflow: <workflow_definition>
}
```
## 2. Workload Definition
The `"workload"` is a user-defined map of input values. It may include:  
- static values (string, number, boolean),
- structured objects or lists,
- Jinja2 template expressions (must be quoted strings).
```yaml
<workload_definition> ::= { <key>: <value> }+
<value> ::= <string> | <number> | <boolean> | <quoted_template> | <object> | <array>
```

## 3. Workbook (Static Task Library)
The `"workbook"` is a statically defined list of named tasks. Tasks are referable by name in the top-level scope only.  
```yaml
<task_library> ::= [ <task_definition>+ ]

```

### 3.1 Task Definition
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

#### 3.1.1 Task (type: task)
```yaml
<task_block_fields> ::= {
  type: "task",
  run: [ <task_definition>+ ]
}
```
- A __task__ `"type": "task"` defines a composite execution unit consisting of a list of nested tasks in `"run"`.
- Tasks within `"run"` are executed sequentially, in the local scope of the parent task.
- These nested tasks are __not globally referable__  they exist only in the context of their parent.
- Each nested task __must have__ a unique name within the parent `"run"` __scope__.


#### 3.1.2 Task (type: loop)
```yaml
<loop_task_fields> ::= {
  type: "loop",
  in: <quoted_template>,
  iterator: <identifier>,
  run: [ <task_definition>+ ]
}
```
- Loop task iterates over a collection and injects each item into the inner task(s) under the name given by `"iterator"`.  
- Each iteration evaluates `"run"` using a context extended with `"{ <iterator>: item }"`.

#### 3.1.3 Task (type: http)
```yaml
<http_task_fields> ::= {
  type: "http",
  method: "GET" | "POST" | "PUT" | "DELETE",
  desc?: <string>,
  endpoint: <quoted_template>,
  params?: { <key>: <quoted_template> },
  payload?: <quoted_template> | { <key>: <quoted_template> },
  retry?: <integer>,
  retry_delay?: <integer>,
  on_error?: "continue" | "fail",
  when?: <quoted_template>,
  with?: { <key>: <quoted_template> }
}
```

#### 3.1.4 Task (type: python)
```yaml
<python_task_fields> ::= {
  type: "python",
  desc?: <string>,
  code: <python_function_code>,
  with?: { <key>: <quoted_template> },
  when?: <quoted_template>
}
```
Python code must define a `"main(input)"` function.



## 4. Workflow Definition
The `"workflow"` is a list of sequential and conditional `"step"` list, each of which may `"run"` tasks and transition to the `"next"` step(s).
```yaml
<workflow_definition> ::= [ <step_definition>+ ]
```

### 4.1 Step Definition
```yaml
<step_definition> ::= {
  step: <step_name>,
  desc?: <string>,
  run?: [ <task_invocation>+ ],
  with?: { <key>: <quoted_template> },
  next?: [ <transition>+ ]
}
```
### 4.2 Task Invocation in Workflow
```yaml
<task_invocation> ::= {
  task: <task_name>,
  with?: { <key>: <quoted_template> }
}
```
Each `"task"` must match a `"task"` from the top-level `"workbook"`.

### 4.3 Step Transitions
```yaml
<transition> ::= {
  when?: <quoted_template>,
  then: [ <step_reference>+ ]
}
<step_reference> ::= { step: <step_name>, with?: { <key>: <quoted_template> } }
```  
- Transitions may be conditional using `"when"`.
- A fallback `"else"` clause is represented by omitting `"when"`.

## 5. Semantics
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

## 6. Execution Model
1. The playbook starts at the `"step": "start"`.
2. Each step executes its `"run"` block (if defined).
3. Step results are available via `"with"` and can affect routing in `"next"`.
4. Loop tasks iterate and aggregate results per item into a list.
5. Errors may be handled via transitions to `"error_handler"` steps.
6. Execution ends at `"step": "end"`.

## 7. Conformance
An implementation is conformant if:  
- It validates playbooks as YAML + Jinja2 expressions.
- It executes tasks respecting `"type"` semantics.
- It performs transitions as specified in `"workflow"`.
- It maintains scoped `"context"` and `"result"` hierarchies.
- It preserves deterministic resolution of top-level task names.