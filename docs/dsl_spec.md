# NoETL DSL Design Specification (v2)

## Overview

The NoETL DSL is a declarative language designed to define workflows as state machines. It provides a structured way to describe workflows, tasks, and actions, enabling conditional logic, parallel execution, and reusable components. The DSL is implemented in YAML or JSON format and is validated against a JSON schema.

This document outlines the key components of the DSL, their relationships, and the rules governing their execution.

---

## Key Components

### 1. **Playbook**
The top-level definition of a workflow. A playbook contains metadata, environment variables, reusable tasks, and a sequence of steps.

#### Properties:
- **apiVersion**: The version of the DSL schema.
- **kind**: The type of the document (e.g., `Playbook`).
- **name**: The name of the playbook.
- **environment**: A dictionary of global variables and configurations.
- **context**: A dictionary of runtime variables.
- **start**: The entry point of the workflow.
- **tasks**: A list of reusable task definitions.
- **steps**: A list of workflow steps.

---

### 2. **Step**
A step represents a unit of workflow logic. It can execute tasks or actions and define transitions to other steps.

#### Properties:
- **name**: A unique identifier for the step.
- **mode**: Execution mode (`sequential` or `parallel`).
- **when**: A condition to determine if the step should run.
- **run**: A list of tasks or actions to execute.
- **until**: A condition to determine when to stop repeating the step.
- **next**: A list of transitions to other steps.

#### Example:
```yaml
steps:
  - name: VerifyUser
    mode: sequential
    when: "{{ user_id is not None }}"
    run:
      - task: validate_user
    next:
      - when: "{{ user_valid }}"
        run: [FetchData]
      - when: "{{ not user_valid }}"
        run: [HandleError]
```

---

### 3. **Task**
A reusable sequence of actions. Tasks are defined once and referenced by steps.

#### Properties:
- **name**: A unique identifier for the task.
- **run**: A list of actions to execute.

#### Example:
```yaml
tasks:
  - name: validate_user
    run:
      - action: http
        method: GET
        url: "https://api.example.com/validate/{{ user_id }}"
```

---

### 4. **Action**
The smallest execution unit in the workflow. Actions represent specific operations, such as HTTP requests, database queries, or shell commands.

#### Properties:
- **action**: The type of operation (e.g., `http`, `postgres`, `shell`).
- **method**: The specific method or operation to perform.
- **parameters**: Additional parameters required for the action.

#### Example:
```yaml
actions:
  - action: http
    method: POST
    url: "https://api.example.com/data"
    body: "{{ payload }}"
```

---

## Execution Semantics

### Rule-Driven Transitions
Each step defines a `rule` block that determines the control flow. Rules consist of cases, each with a condition and a set of actions or transitions.

#### Key Rules:
1. **Mandatory Rule per Step**: Every step must define a `rule`.
2. **Case Evaluation**: Cases are evaluated in order, and the first matching case is executed.
3. **No Mixed Run Modes**: A case cannot mix transitions and in-place actions.
4. **Explicit Termination**: If no case matches, the workflow branch ends.

---

## Validation Rules

To ensure the integrity of the workflow, the following validation rules are enforced:

1. **Unique Names**: Step and task names must be unique.
2. **Valid References**: All step and task references must exist.
3. **Homogeneous Run Blocks**: Each `run` block must contain either all transitions or all actions.
4. **Complete Rules**: Each step must have at least one valid case in its `rule`.

---

## Example Playbook

```yaml
apiVersion: "v1"
kind: "Playbook"
name: "UserOnboarding"
environment:
  db_connection: "postgres://user:pass@localhost/db"
context:
  user_id: null
start:
  run:
    - step: VerifyUser
tasks:
  - name: validate_user
    run:
      - action: http
        method: GET
        url: "https://api.example.com/validate/{{ user_id }}"
steps:
  - name: VerifyUser
    mode: