---
sidebar_position: 2
title: DSL Specification
description: Formal specification for NoETL DSL v2 syntax, semantics, and workflow patterns
---

# NoETL Playbook DSL - Formal Specification

**Document type:** Formal Specification  
**API Version:** noetl.io/v2

---

## 1. Conformance and Terminology

The key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are to be interpreted as described in RFC 2119.

### 1.1 Components

- **Server**: Control plane; provides API endpoints; orchestrates and persists events.
- **Worker**: Background worker pool; executes tools; no HTTP endpoints.
- **CLI**: Manages worker pools and server lifecycle.

### 1.2 Core Entities

- Playbook, Workload, Context, Workflow, Step, Tool, Workbook, Loop, Case, Next, Retry, Sink.

---

## 2. Document Model

### 2.1 API Version

This specification describes **Playbook v2**. All v2 playbooks MUST use:

```yaml
apiVersion: noetl.io/v2
```

A conforming server MUST reject playbooks that do not specify `apiVersion: noetl.io/v2`.

### 2.2 Top-Level Keys

A playbook is a YAML mapping with the following top-level keys:

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `apiVersion` | string | Yes | Must be `noetl.io/v2` |
| `kind` | string | Yes | Must be `Playbook` |
| `metadata` | mapping | Yes | Contains `name` (required) and `path` (optional) |
| `workload` | mapping | No | Global variables merged with payload |
| `keychain` | list | No | Credential and token definitions |
| `workbook` | list | No | Named reusable task definitions |
| `workflow` | list | Yes | List of step definitions |

### 2.3 Template Evaluation

1. All templated expressions MUST be valid Jinja2 templates embedded as YAML strings.
2. Template rendering context MUST include (at minimum):
   - `workload` (materialized global variables)
   - `vars` (persisted execution variables)
   - `execution_id` (unique execution identifier)
   - Prior step results (by step name)

---

## 3. Execution Model (Normative)

### 3.1 Execution Request

An execution request MUST provide either:
- `playbook_id`, OR
- (`path`, `version`) identifying a cataloged playbook.

An execution request MAY provide an arbitrary JSON/YAML payload.

### 3.2 Workload Materialization

1. The server MUST load the playbook.
2. The server MUST evaluate the `workload` section (rendering templates).
3. The server MUST merge the execution request payload into the materialized workload.
   - Merge strategy is **deep merge**, where request payload keys override playbook workload keys.
4. The server MUST construct the initial **context** from the merged workload.

### 3.3 Workflow Start

1. The workflow MUST contain a step named `start`.
2. The server MUST emit `WorkflowStarted` and `StepStarted` for `start`.
3. The initial context MUST be passed to the start step.

### 3.4 Step Evaluation Order

Given a step `S`, evaluation MUST occur in the following order:

1. **Bind inputs**: Render and bind `args` parameters (if present).
2. **Loop expansion**: If `loop` is present, create a loop scope and evaluate iteration plan.
3. **Tool execution**: Execute the tool specified in `tool.kind`.
4. **Result binding**: Bind step result into context.
5. **Variable extraction**: If `vars` is present, extract and persist variables.
6. **Routing**:
   - Evaluate `case` if present; otherwise evaluate `next`.
   - If neither exists, the step terminates and control returns to the server.
7. **Sink**: If `sink` is present and its predicate holds, execute sink.

A conforming implementation MUST record events for each phase.

---

## 4. Step Schema

A step is a YAML mapping with the following structure:

```yaml
- step: <step_name>           # Required: unique identifier
  desc: <string?>             # Optional: description
  args: <mapping?>            # Optional: input arguments
  tool:                       # Required: tool configuration
    kind: <tool_kind>         # Required: tool type
    # ... tool-specific fields
  loop: <loop_clause?>        # Optional: iteration control
  vars: <mapping?>            # Optional: variable extraction
  case: <case_clause?>        # Optional: event-driven routing
  next: <next_clause?>        # Optional: default routing
  sink: <sink_clause?>        # Optional: persistence
  retry: <retry_clause?>      # Optional: retry policy
```

### 4.1 Tool Configuration

Every step (except special routing steps) MUST have a `tool` block with a `kind` field:

```yaml
tool:
  kind: python|http|postgres|duckdb|workbook|playbook|secrets|iterator|...
  # Tool-specific configuration
```

### 4.2 Supported Tool Kinds

| Kind | Description |
|------|-------------|
| `python` | Execute inline Python code |
| `http` | HTTP request (GET, POST, etc.) |
| `postgres` | PostgreSQL query execution |
| `duckdb` | DuckDB query execution |
| `workbook` | Reference to named task in workbook |
| `playbook` | Execute sub-playbook by catalog path |
| `secrets` | Fetch secret from provider |
| `iterator` | Loop iteration control |
| `snowflake` | Snowflake query execution |
| `gcs` | Google Cloud Storage operations |
| `container` | Container execution |
| `script` | External script execution |

---

## 5. Workbook Schema

A workbook entry is a named tool definition:

```yaml
workbook:
  - name: <task_name>         # Required: reference name
    tool:                     # Required: tool configuration
      kind: <tool_kind>
      # ... tool-specific fields
    sink: <sink_clause?>      # Optional: persistence after task
```

**Example:**

```yaml
workbook:
  - name: fetch_weather
    tool:
      kind: http
      method: GET
      url: "https://api.weather.com/forecast"
      params:
        city: "{{ city }}"
```

---

## 6. Loop Clause (Normative)

### 6.1 Syntax

```yaml
loop:
  in: "{{ <jinja_expression> }}"  # Collection to iterate
  iterator: <identifier>           # Variable name for each item
  mode: sequential|parallel|async  # Execution mode (default: sequential)
```

### 6.2 Semantics

- `in` MUST evaluate to a list/array.
- For each element `e`, the implementation MUST create an iteration scope where:
  - `iterator` binds to `e`
  - `loop_index` is available as the iteration index
- Sequential mode MUST preserve iteration order.
- Parallel/async mode MAY reorder completion, but MUST preserve stable iteration identifiers.

### 6.3 Example

```yaml
- step: process_items
  loop:
    in: "{{ workload.items }}"
    iterator: item
    mode: sequential
  tool:
    kind: python
    args:
      current_item: "{{ item }}"
    code: |
      print(f"Processing: {current_item}")
      result = {"processed": current_item}
  next:
    - step: aggregate
```

---

## 7. Retry Clause (Normative)

### 7.1 Syntax

```yaml
retry:
  max_attempts: <int>
  initial_delay: <number>         # Seconds
  backoff_multiplier: <number>    # For exponential backoff
  retry_when: "{{ <predicate> }}" # Condition to trigger retry
  stop_when: "{{ <predicate> }}"  # Condition to stop retrying
```

### 7.2 Semantics

- If `stop_when` is present, the system MUST re-execute the tool until:
  - `stop_when` evaluates to true, OR
  - max attempts is reached.
- If `retry_when` is present, retries MUST occur only when the predicate evaluates to true.

### 7.3 Template Context for Retry

In retry evaluation, these variables are available:
- `attempt` - Current attempt number
- `max_attempts` - Maximum attempts configured
- `status_code` - HTTP status code (for HTTP tools)
- `error` - Error message if present
- `success` - Boolean success flag
- `result` / `data` - Last attempt's result

---

## 8. Case Clause (Normative)

### 8.1 Syntax

```yaml
case:
  - when: "{{ <predicate> }}"
    then:
      next:
        - step: <next_step>
          args: <mapping?>
      sink: <sink_clause?>
      set: <set_clause?>
```

### 8.2 Semantics

- `case` is evaluated top-down.
- The first true `when` wins.
- `then` block contains actions to execute when condition matches.
- If no `case` matches, `next` field (if present) provides fallback routing.

### 8.3 Template Context for Case

In `case.when` conditions:
- `event` - Event object with `event.name` (e.g., 'step.exit', 'call.done', 'call.error')
- `response` - Full step response envelope

In `case.then` actions (sink, set):
- `result` - Unwrapped step result data
- `this` - Full result envelope (status, data, error, meta)

### 8.4 Example

```yaml
- step: fetch_data
  tool:
    kind: http
    method: GET
    url: "{{ workload.api_url }}"
  case:
    - when: "{{ event.name == 'call.done' and response.status_code == 200 }}"
      then:
        next:
          - step: process_data
    - when: "{{ event.name == 'call.error' }}"
      then:
        next:
          - step: handle_error
  next:
    - step: default_handler  # Fallback if no case matches
```

---

## 9. Next Clause (Normative)

`next` provides default routing when no `case` rule matches.

### 9.1 Syntax

```yaml
# Simple string
next: step_name

# List of steps (parallel routing)
next:
  - step: step_a
  - step: step_b

# Steps with args
next:
  - step: next_step
    args:
      key: "{{ value }}"
```

### 9.2 V2 Restrictions

In v2, `next` MUST NOT contain `when/then/else` clauses. Conditional routing MUST use `case`.

**Invalid (v1 pattern - rejected in v2):**
```yaml
next:
  - when: "{{ condition }}"
    then:
      - step: branch_a
  - step: default
```

**Valid (v2 pattern):**
```yaml
case:
  - when: "{{ condition }}"
    then:
      next:
        - step: branch_a
next:
  - step: default
```

---

## 10. Sink Clause (Normative)

```yaml
sink:
  tool:
    kind: postgres|duckdb|http|...
  table: <table_name>
  args: <mapping>
  when: "{{ <predicate> }}"   # Optional condition
```

### 10.1 Semantics

- The sink MUST run after the step's main tool (unless otherwise specified).
- If `when` is present and evaluates to false, the sink MUST be skipped.
- Sink execution MUST be recorded in the event log.

---

## 11. Variables (vars) Block

### 11.1 Syntax

```yaml
vars:
  variable_name: "{{ result.field }}"
  another_var: "{{ result.nested.value }}"
```

### 11.2 Semantics

- Executes AFTER step completes successfully
- Templates use `{{ result.field }}` to access current step's result
- Variables are stored in `noetl.transient` database table
- Accessible in subsequent steps via `{{ vars.variable_name }}`

### 11.3 Example

```yaml
- step: fetch_user
  tool:
    kind: postgres
    query: "SELECT user_id, email FROM users WHERE id = 1"
  vars:
    user_id: "{{ result[0].user_id }}"
    email: "{{ result[0].email }}"
  next:
    - step: send_notification

- step: send_notification
  tool:
    kind: http
    method: POST
    url: "https://api.example.com/notify"
    body:
      user_id: "{{ vars.user_id }}"
      email: "{{ vars.email }}"
```

---

## 12. Event Model (Normative)

### 12.1 Event Envelope

A conforming event MUST include:

- `event_id` (string; unique)
- `event_type` (string; canonical name)
- `execution_id` (string)
- `timestamp` (RFC3339)
- `entity_type` (playbook|workflow|step|tool|loop|sink|retry|case)
- `entity_id` (string)
- `status` (in_progress|success|error|skipped)
- `payload` (object; inputs/outputs/metadata)

### 12.2 Canonical Event Types

- `playbook.execution.requested`
- `playbook.request.evaluated`
- `playbook.started`
- `workflow.started`
- `step.started` / `step.finished`
- `tool.started` / `tool.processed`
- `case.started` / `case.evaluated`
- `next.evaluated`
- `loop.started` / `loop.iteration.started` / `loop.iteration.finished` / `loop.finished`
- `retry.started` / `retry.processed`
- `sink.started` / `sink.processed`
- `workflow.finished`
- `playbook.processed`

---

## 13. Control Plane vs Data Plane

### 13.1 Server-Emitted Events

The server MUST emit:
- Playbook request and validation events
- Workflow and step scheduling events
- Routing decisions (case/next evaluation)
- Finalization events

### 13.2 Worker-Emitted Events

Workers MUST emit:
- Tool lifecycle events (`tool.started`, `tool.processed`)
- Retry attempt events for tool re-execution
- Sink events if sinks execute on the worker
- Loop iteration events if the worker is the iteration executor

Workers MUST report events to the server for persistence.

---

## Appendix A: Complete Playbook Example

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: user_onboarding
  path: workflows/onboarding/user

workload:
  api_url: "https://api.example.com"
  notification_enabled: true

workbook:
  - name: send_welcome_email
    tool:
      kind: http
      method: POST
      url: "{{ workload.api_url }}/email"
      body:
        template: "welcome"
        to: "{{ email }}"

workflow:
  - step: start
    tool:
      kind: python
      auth: {}
      libs: {}
      args: {}
      code: |
        result = {"status": "initialized"}
    case:
      - when: "{{ event.name == 'step.exit' }}"
        then:
          next:
            - step: fetch_user

  - step: fetch_user
    tool:
      kind: postgres
      query: "SELECT * FROM users WHERE id = {{ workload.user_id }}"
    vars:
      user_email: "{{ result[0].email }}"
      user_name: "{{ result[0].name }}"
    case:
      - when: "{{ event.name == 'step.exit' and response is defined }}"
        then:
          next:
            - step: send_welcome

  - step: send_welcome
    tool:
      kind: workbook
      name: send_welcome_email
      args:
        email: "{{ vars.user_email }}"
    case:
      - when: "{{ event.name == 'step.exit' }}"
        then:
          next:
            - step: end

  - step: end
    tool:
      kind: python
      auth: {}
      libs: {}
      args: {}
      code: |
        result = {"status": "completed", "message": "User onboarding complete"}
```

---

## Appendix B: Template Variable Reference

| Context | Location | Available Variables |
|---------|----------|---------------------|
| Event condition | `case: when:` | `event`, `response` |
| Action blocks | `case: then: sink:` | `result` (unwrapped), `this` (envelope) |
| Retry config | `case: then: retry:` | `response` |
| Retry evaluation | `retry_when:`, `stop_when:` | `status_code`, `error`, `attempt`, `result` |
| Vars extraction | `vars:` | `result` |
| Step args | `args:` | `workload`, `vars`, prior step results |
