---
sidebar_position: 1
title: DSL Specification
description: Complete reference for NoETL DSL syntax, step structure, and workflow patterns
---

# NoETL DSL Design Specification (Step Widgets v2)

## Overview

The NoETL DSL defines workflows as a sequence of steps that coordinate tool execution. **Steps are aggregators** that control how tools execute using attributes like `tool:`, `loop:`, `vars:`, and `case:`. Playbooks are YAML/JSON documents validated against the schema in `docs/playbook-schema.json`.

### Step Structure

Each step is a coordinator with:
- **`tool:`** - Defines what executes (required, except for `start`/`end`)
  - `kind:` - Tool type (python, http, postgres, duckdb, workbook, playbook, etc.)
  - Tool-specific configuration (code, endpoint, script, etc.)
- **`loop:`** - Controls repeated tool execution (optional)
  - `in:` - Collection to iterate over
  - `iterator:` - Variable name for current item
  - `mode:` - Execution mode (sequential/async)
- **`vars:`** - Extracts values from results for persistence (optional)
- **`case:`** - Event-driven conditional routing (optional)
- **`next:`** - Default routing to subsequent steps (optional)

### Available Tool Kinds

- **workbook** — Reference to named task from workbook library
- **python** — Inline Python code execution
- **http** — HTTP request (GET, POST, etc.)
- **postgres** — PostgreSQL SQL/script execution
- **duckdb** — DuckDB SQL/script execution
- **playbook** — Execute sub-playbook by catalog path
- **secrets** — Fetch secret from provider (GCP, AWS, etc.)

### Special Steps

- **start** — Workflow entry point. Conventionally has no tool (just routing with `next:`), though technically can have one
- **end** — Terminal step by convention. Step named "end" typically has no `next:` to indicate workflow completion, but can have a tool for final actions

**Note**: "start" and "end" are naming conventions, not special types. Any step can be an entry point or terminal step based on workflow structure.

---

## Key Components

### Playbook
Top-level workflow definition.

Properties:
- apiVersion: DSL schema version (const: `noetl.io/v1`)
- kind: Document kind (const: `Playbook`)
- name: Playbook name
- path: Catalog path for this playbook
- environment: Global variables and config
- context: Runtime variables (e.g., execution ids, state)
- workbook: Library of reusable tasks callable from `workbook` steps
- workflow: Ordered list of steps (widgets)

Example:
```yaml
apiVersion: noetl.io/v1
kind: Playbook
name: UserOnboarding
path: workflows/example/user_onboarding
environment:
  postgres_url: "postgres://user:pass@localhost:5432/app"
context:
  jobId: "{{ uuid() }}"
  state: "init"
workbook:
  - name: get_weather
    desc: Weather by city
    tool:
      kind: http
      method: GET
      endpoint: "https://api.example.com/weather"
```

---

## Steps (Widgets)

**Steps are aggregators** that coordinate tool execution and control flow. Each step combines:

### Step Attributes

- **step** (string, required): Unique step identifier
- **desc** (string, optional): Human-readable description
- **tool** (object, optional): Tool to execute (not required for `start`/`end`)
  - **kind** (string, required): Tool type - `python`, `http`, `postgres`, `duckdb`, `workbook`, `playbook`, `secrets`
  - Tool-specific configuration fields (varies by kind)
- **loop** (object, optional): Control repeated tool execution
  - **in** (array|string): Collection to iterate over
  - **iterator** (string): Variable name for current item
  - **mode** (string): `sequential` or `async`
- **vars** (object, optional): Variable extraction block - extracts values from step result and stores in `transient` database
- **case** (array, optional): Event-driven conditional routing
  - **when** (string): Jinja2 condition to evaluate
  - **then** (object): Actions when condition matches
    - **next** (array): Steps to route to
    - **set** (object): Ephemeral variables to set
- **next** (string|array, optional): Default routing to subsequent steps. Not allowed for `end`. Required for `start`.

### General Execution Model

- Steps execute in order by following `next` edges
- `tool:` defines what runs (Python code, HTTP call, database query, etc.)
- `loop:` controls repeated execution of the tool over a collection
- `vars:` extracts and persists values after successful execution
- `case:` enables event-driven conditional logic
- If a step has no `next` and is not `end`, the branch terminates implicitly

### Variable Extraction with `vars:` Block

**Purpose**: Extract and persist values from step execution results for use in subsequent steps.

**Syntax**:
```yaml
- step: step_name
  tool:
    kind: <tool_kind>   # python, http, postgres, etc.
    # ... tool configuration ...
  vars:
    variable_name: "{{ result.field }}"
    another_var: "{{ result.nested.value }}"
```

**Behavior**:
- Executes AFTER step completes successfully
- Templates use `{{ result.field }}` to access current step's result
- Variables stored in `noetl.transient` database table with `var_type='step_result'`
- Accessible in all subsequent steps via `{{ vars.variable_name }}`
- Also accessible via REST API: `GET /api/vars/{execution_id}/{var_name}`

**Template Namespaces**:
- `{{ result.field }}` - Current step's result (only in vars block)
- `{{ vars.var_name }}` - Previously extracted variables
- `{{ workload.field }}` - Global playbook variables
- `{{ step_name.field }}` - Previous step results
- `{{ execution_id }}` - System execution ID

**Example - Extract from Database Query**:
```yaml
- step: fetch_user
  tool:
    kind: postgres
    script: "SELECT user_id, email, status FROM users WHERE id = 1"
  vars:
    user_id: "{{ result[0].user_id }}"
    email: "{{ result[0].email }}"
    is_active: "{{ result[0].status == 'active' }}"
  next: send_notification

- step: send_notification
  tool:
    kind: http
    method: POST
    endpoint: "https://api.example.com/notify"
    body:
      user_id: "{{ vars.user_id }}"
      email: "{{ vars.email }}"
      active: "{{ vars.is_active }}"
  next: end
```

**Example - Extract from Python Result**:
```yaml
- step: calculate
  tool:
    kind: python
    code: |
      def main():
        return {"total": 100, "average": 25.5, "count": 4}
  vars:
    total_amount: "{{ result.total }}"
    avg_value: "{{ result.average }}"
    record_count: "{{ result.count }}"
  next: log_results
```

**Storage Details**:
- Table: `noetl.transient`
- Primary Key: `(execution_id, var_name)`
- Columns: `var_type`, `var_value` (JSONB), `source_step`, `created_at`, `accessed_at`, `access_count`
- Automatic cleanup when execution completes

**REST API Access**:
```bash
# Get all variables for execution
GET /api/vars/{execution_id}

# Get specific variable (increments access_count)
GET /api/vars/{execution_id}/{var_name}

# Set variables programmatically
POST /api/vars/{execution_id}
Content-Type: application/json
{
  "variables": {"my_var": "value"},
  "var_type": "user_defined"
}
```

See `vars_block_quick_reference.md` for more patterns and examples.

---

## Argument Passing with `args:` Attribute

### Overview

The `args:` attribute is used to pass data between steps, into tools, and when routing to next steps. **It can appear at three different levels**, each with distinct purposes:

1. **Step Level** (`- step: name` / `args:`) - Provides input data to the step's tool
2. **Tool Level** (`tool:` / `args:`) - Direct arguments for tool configuration (less common, typically at step level)
3. **Next Level** (`next:` / `- step: name` / `args:`) - Passes specific data when routing to a step

### Scope and Purpose by Level

| Level | Location | Purpose | Available Context |
|-------|----------|---------|-------------------|
| **Step** | Sibling to `tool:` | Inject data into tool execution (e.g., Python function params, HTTP request data) | All: `workload`, `vars`, prior step results, `execution_id` |
| **Tool** | Inside `tool:` block | Tool-specific configuration arguments (alternative to step-level) | Same as step level |
| **Next** | Inside routing target in `next:` or `case.then.next` | Pass data to specific next step(s) during routing | Same as step level |

---

### Step-Level `args:`

**Purpose**: Provide input data that the tool will receive during execution. This is the most common usage.

**Location**: Sibling to `tool:`, same indentation level

**Behavior**:
- Values are Jinja2-templated at step execution time
- Tool receives args as input parameters (e.g., Python function arguments, template variables)
- Accessible within tool code as variables

**Example - Python Tool with Step Args**:
```yaml
- step: calculate_discount
  args:
    original_price: "{{ fetch_product.price }}"
    discount_rate: "{{ vars.discount_rate }}"
    customer_tier: "{{ vars.customer_tier }}"
  tool:
    kind: python
    code: |
      def main(original_price, discount_rate, customer_tier):
        multiplier = 1.0 if customer_tier == 'gold' else 0.8
        discount = original_price * discount_rate * multiplier
        return {"discount": discount, "final_price": original_price - discount}
  next: apply_discount
```

**Example - HTTP Tool with Step Args**:
```yaml
- step: send_notification
  args:
    user_id: "{{ vars.user_id }}"
    message: "{{ vars.notification_message }}"
    priority: "high"
  tool:
    kind: http
    method: POST
    endpoint: "https://api.example.com/notifications"
    body:
      user_id: "{{ user_id }}"      # References step args
      message: "{{ message }}"
      priority: "{{ priority }}"
  next: end
```

**Example - Workbook Tool with Step Args**:
```yaml
- step: process_user
  args:
    user_data: "{{ current_user }}"
    processing_mode: "standard"
  tool:
    kind: workbook
    name: user_processor
    args:
      user: "{{ user_data }}"       # Can reference step args
      mode: "{{ processing_mode }}"
  next: save_result
```

---

### Tool-Level `args:`

**Purpose**: Alternative location for tool-specific arguments. Less common; step-level `args:` is preferred.

**Location**: Inside `tool:` block, sibling to `kind:`

**Behavior**:
- Similar to step-level args but scoped to tool configuration
- Useful when step has multiple concerns (e.g., args for tool vs. args for routing)

**Example - Tool Args (Alternative Pattern)**:
```yaml
- step: compute_score
  tool:
    kind: python
    code: |
      def main(a, b):
        return {"sum": a + b}
    args:
      a: 5
      b: 7
  next: end
```

**Note**: Step-level `args:` is generally preferred for clarity and consistency.

---

### Next-Level `args:` (Routing with Data)

**Purpose**: Pass specific data to target step(s) during routing. Allows dynamic parameterization based on control flow.

**Location**: Inside `next:` array items or `case.then.next` array items

**Behavior**:
- Templated at routing time (when branching occurs)
- Target step receives these args as if they were step-level args
- Overrides or supplements step's own `args:` definition
- Useful for passing event-specific data or conditional values

**Example - Next Args in case.then.next**:
```yaml
- step: start
  tool:
    kind: python
    code: |
      def main():
        return {"status": "initialized"}
  case:
    - when: "{{ event.name == 'step.exit' }}"
      then:
        next:
          - step: process_data
            args:
              message: "{{ workload.message }}"
              timestamp: "{{ result.timestamp }}"

- step: process_data
  args:
    message: "default message"    # Can be overridden by routing args
  tool:
    kind: python
    code: |
      def main(message, timestamp=None):
        print(f"Processing: {message} at {timestamp}")
        return {"processed": True}
  next: end
```

**Example - Next Args in Loop with Playbook**:
```yaml
- step: process_users
  loop:
    in: "{{ workload.users }}"
    iterator: user
  tool:
    kind: playbook
    path: workflows/user_processor
    args:
      user_data: "{{ user }}"
      execution_context: "{{ execution_id }}"
  next: summarize
```

**Example - Conditional Routing with Different Args**:
```yaml
- step: evaluate_score
  tool:
    kind: python
    code: |
      def main():
        score = calculate_score()
        return {"score": score}
  case:
    - when: "{{ result.score > 80 }}"
      then:
        next:
          - step: high_score_handler
            args:
              score: "{{ result.score }}"
              level: "gold"
    - when: "{{ result.score > 50 }}"
      then:
        next:
          - step: medium_score_handler
            args:
              score: "{{ result.score }}"
              level: "silver"
  next:
    - step: low_score_handler
      args:
        score: "{{ result.score }}"
        level: "bronze"
```

---

### Args in Sink Blocks

**Purpose**: Provide data to sink tools (database writes, event logs, etc.) after step execution.

**Location**: Inside `case.then.sink` or step-level `sink:`

**Behavior**:
- Templated after step completes
- Has access to `result` (unwrapped step data), `this` (envelope), prior step results

**Example - Sink Args**:
```yaml
- step: fetch_user
  tool:
    kind: http
    method: GET
    endpoint: "https://api.example.com/users/{{ user_id }}"
  case:
    - when: "{{ event.name == 'call.done' and response is defined }}"
      then:
        sink:
          tool:
            kind: postgres
          auth: pg_prod
          table: public.user_cache
          args:
            id: "{{ execution_id }}:{{ result.user_id }}"
            user_id: "{{ result.user_id }}"
            email: "{{ result.email }}"
            fetched_at: "{{ this.meta.timestamp }}"
        next:
          - step: end
```

---

### Template Context for Args

> **Important**: Template variables differ by context. See [Template Variable Reference: `response` vs `result`](#template-variable-reference-response-vs-result) for comprehensive guidance on when to use `response`, `result`, or raw fields like `status_code`.

All `args:` blocks have access to the standard template namespaces:

- **`{{ workload.field }}`** - Global playbook variables
- **`{{ vars.var_name }}`** - Extracted variables from vars: blocks
- **`{{ step_name.field }}`** - Previous step results
- **`{{ execution_id }}`** - Current execution identifier
- **`{{ result.field }}`** - Current step result (in case.then contexts)
- **`{{ iterator }}`** - Current loop item (within loop iterations)

---

### Best Practices

1. **Prefer Step-Level Args**: Place `args:` at step level for clarity, not inside `tool:`
2. **Use Next Args for Dynamic Routing**: When different paths need different data
3. **Explicit Over Implicit**: Be explicit about data flow; don't rely on ambient context
4. **Template Defensively**: Use default values or conditional checks for optional args
   ```yaml
   args:
     value: "{{ result.value | default(0) }}"
   ```
5. **Document Data Flow**: Use comments to clarify complex arg passing
   ```yaml
   - step: process
     args:
       # Comes from previous fetch_data step
       dataset: "{{ fetch_data.results }}"
       # Global configuration
       batch_size: "{{ workload.batch_size }}"
   ```

---

See `vars_block_quick_reference.md` for more patterns and examples.

### start
Workflow entry point that routes to the first executable step. Conventionally has no `tool:` (just routing), but can optionally include one.

Typical Attributes:
- **desc** (string, optional): Description
- **next** (string|array, required): Step(s) to execute first
- **tool** (object, optional): Optional tool to execute on entry

Example (routing only):
```yaml
- step: start
  desc: Entry point for user onboarding workflow
  next: fetch_user
```

Example (with tool):
```yaml
- step: start
  desc: Initialize workflow state
  tool:
    kind: python
    code: |
      def main():
        return {"initialized": True, "timestamp": datetime.now().isoformat()}
  next: fetch_user
```

### end
Terminal step indicating workflow completion. By convention, step named "end" has no `next:` to mark the endpoint, but can include a `tool:` for final actions.

Typical Attributes:
- **desc** (string, optional): Description
- **tool** (object, optional): Optional tool for final processing
- **next** (typically omitted): No next steps to mark termination

Example (marker only):
```yaml
- step: end
  desc: Workflow completed successfully
```

Example (with final action):
```yaml
- step: end
  desc: Log completion and cleanup
  tool:
    kind: python
    code: |
      def main():
        return {"status": "completed", "timestamp": datetime.now().isoformat()}
```

### workbook
Reference a named task from the workbook library.

Tool Configuration (`tool:`):
- **kind**: `workbook` (required)
- **name** (string, required): Name of task defined under playbook's `workbook:` section
- **args** (object, optional): Inputs forwarded to the task
- **as** (string, optional): Variable name to store the task result

Outputs:
- Result of the task, stored under `context[as]` if `as` is provided, else available as step-local `result`

Example:
```yaml
- step: fetch_weather
  tool:
    kind: workbook
    name: get_weather
    args:
      city: "Paris"
    as: weather
  next: end
```

### python
Execute inline Python code.

Tool Configuration (`tool:`):
- **kind**: `python` (required)
- **code** (string, required): Python code to execute (typically with `def main():` function)
- **args** (object, optional): Variables to inject into the code context
- **as** (string, optional): Variable name to store the result

Outputs:
- `result` from the last expression or explicit `return` in the code block; saved under `as` if provided

Example:
```yaml
- step: compute_score
  tool:
    kind: python
    code: |
      def main(a, b):
        total = a + b
        return {"sum": total, "ok": True}
    args:
      a: 5
      b: 7
    as: score
  next: end
```

### http
Perform an HTTP request.

Tool Configuration (`tool:`):
- **kind**: `http` (required)
- **method** (enum: GET, POST, PUT, DELETE, PATCH) required
- **endpoint** (string, required)
- **headers** (object, optional)
- **params** (object, optional)
- **body** (object|string, optional)
- **timeout** (number, optional, seconds)
- **verify** (boolean, optional)
- **as** (string, optional)

Outputs:
- `status`, `headers`, `body`, `json` (if parseable). If `as` is provided, the whole response object is saved under that name.

Example:
```yaml
- step: call_api
  tool:
    kind: http
    method: GET
    endpoint: "https://api.example.com/users/{{ user_id }}"
    headers:
      Authorization: "Bearer {{ env.API_TOKEN }}"
    as: user_response
  next: end
```

### duckdb
Run DuckDB SQL/script.

Tool Configuration (`tool:`):
- **kind**: `duckdb` (required)
- **script** (string, required): SQL or script to execute
- **files** (array[string], optional): External file paths to load
- **as** (string, optional)

Outputs:
- Query result set (if any), saved under `as` if provided

Example:
```yaml
- step: duck_transform
  tool:
    kind: duckdb
    script: |
      CREATE OR REPLACE TABLE t AS SELECT 1 AS id;
      SELECT * FROM t;
    as: table_rows
  next: end
```

### postgres
Run PostgreSQL SQL/script.

Tool Configuration (`tool:`):
- **kind**: `postgres` (required)
- **sql** (string, required): SQL query or script to execute
- **connection** (string, optional): DSN/URL connection string
- **db_host, db_port, db_user, db_password, db_name, db_schema** (optional): Discrete connection fields
- **as** (string, optional)

Outputs:
- Query result set (if any) or `rowcount`; saved under `as` if provided

Example:
```yaml
- step: load_users
  tool:
    kind: postgres
    connection: "{{ environment.postgres_url }}"
    sql: |
      SELECT id, email FROM users LIMIT 10;
    as: users
  next: end
```

### secrets
Read a secret from a provider.

Tool Configuration (`tool:`):
- **kind**: `secrets` (required)
- **provider** (enum: gcp, aws, azure, vault, env) required
- **name** (string, required): Secret identifier
- **project** (string, optional): Provider-specific project/account ID
- **version** (string|number, optional): Secret version to retrieve
- **as** (string, optional, default logical value: `secret_value`)

Outputs:
- Secret material as a string; saved under `as` (default `secret_value`)

Example:
```yaml
- step: get_openai_key
  tool:
    kind: secrets
    provider: gcp
    project: my-gcp-project
    name: OPENAI_API_KEY
    as: openai_api_key
  next: end
```

### playbook
Execute a sub-playbook by catalog path.

Tool Configuration (`tool:`):
- **kind**: `playbook` (required)
- **path** (string, required): Catalog path to the playbook
- **args** (object, optional): Inputs to forward to the sub-playbook
- **return_step** (string, optional): Specific step result to return from sub-playbook
- **as** (string, optional): Variable name to store result

Outputs:
- Result from the executed sub-playbook; saved under `as` if provided

Example:
```yaml
- step: run_etl
  tool:
    kind: playbook
    path: workflows/etl/user_transform
    args:
      job_date: "{{ today() }}"
      batch_size: 1000
    as: etl_result
  next: validate_results
```

---

## Loop Control Attribute

### loop:
The `loop:` attribute controls repeated execution of a step's tool over a collection. **It is not a step type**, but a step-level attribute that modifies how the tool executes.

**Structure**:
```yaml
- step: step_name
  tool:
    kind: <tool_kind>     # Any tool: python, http, postgres, etc.
    # ... tool configuration
  loop:                   # Controls repeated execution
    in: "{{ collection }}"
    iterator: item_name
    mode: sequential      # or async
```

**Attributes**:
- **in** (array|string, required): Collection to iterate over (can be Jinja2 expression)
- **iterator** (string, required): Variable name for the current item in each iteration
- **mode** (string, optional): Execution mode
  - `sequential` - Items processed one at a time (default)
  - `async` - Items processed concurrently

**Behavior**:
1. Tool executes once per item in the collection
2. Current item available as `{{ iterator_name }}` in tool configuration
3. Results collected into array accessible in next steps
4. Works with any tool kind: python, http, postgres, workbook, playbook, etc.

**Example - Loop with HTTP Tool**:
```yaml
- step: fetch_user_data
  loop:
    in: "{{ workload.user_ids }}"
    iterator: user_id
    mode: sequential
  tool:
    kind: http
    method: GET
    endpoint: "https://api.example.com/users/{{ user_id }}"
  next: process_results
```

**Example - Loop with Python Tool**:
```yaml
- step: process_items
  loop:
    in: "{{ workload.items }}"
    iterator: item
    mode: async
  tool:
    kind: python
    code: |
      def main(item):
        return {"id": item["id"], "processed": True}
    args:
      item: "{{ item }}"
  vars:
    processed_count: "{{ result | length }}"
  next: end
```

**Example - Loop with Workbook Tool**:
```yaml
- step: batch_transform
  loop:
    in: "{{ workload.batch_dates }}"
    iterator: date
  tool:
    kind: workbook
    name: daily_transform
    args:
      job_date: "{{ date }}"
  next: aggregate_results
```

**Example - Loop with Playbook Tool**:
```yaml
- step: run_daily_jobs
  loop:
    in: ["2025-01-01", "2025-01-02", "2025-01-03"]
    iterator: day
    mode: async
  tool:
    kind: playbook
    path: workflows/daily/jobs
    args:
      job_date: "{{ day }}"
  next: validate_all
```

**Accessing Loop Results**:
```yaml
- step: summarize
  tool:
    kind: python
    code: |
      def main(results):
        return {"total": len(results), "success": sum(1 for r in results if r.get("ok"))}
    args:
      results: "{{ fetch_user_data }}"  # Array of all loop iteration results
```

---

## Template Context and Result References

### Available Template Namespaces

During workflow execution, multiple namespaces are available in Jinja2 templates:

**1. Global/Static Namespaces**:
- `{{ workload.field }}` - Global variables from playbook `workload:` section (immutable)
- `{{ execution_id }}` - System execution identifier
- `{{ payload.field }}` - CLI --payload values

**2. Dynamic Step Results** (available after step execution):
- `{{ step_name }}` or `{{ step_name.result }}` - Full result object from previous step
- `{{ step_name.data }}` - Data payload (when step returns envelope structure)
- `{{ step_name.data.field }}` - Specific field access

**3. Extracted Variables** (via `vars:` block):
- `{{ vars.var_name }}` - Persistent variables extracted from step results
- Stored in `transient` database table
- Accessible via REST API: `/api/vars/{execution_id}`
- Example:
  ```yaml
  - step: fetch_data
    tool:
      kind: postgres
      script: "SELECT id, name FROM users"
    vars:
      first_id: "{{ result[0].id }}"
      first_name: "{{ result[0].name }}"
  
  - step: use_vars
    tool:
      kind: python
      code: |
        def main(first_id, first_name):
          print(f"ID: {first_id}, Name: {first_name}")
      args:
        first_id: "{{ vars.first_id }}"
        first_name: "{{ vars.first_name }}"
  ```

**4. Context-Specific** (only in certain locations):
- `{{ result.field }}` - Current step's result (only in `vars:` block)
- `{{ args.field }}` - Input arguments (only within step execution code)
- `{{ iterator }}` - Loop item variable (only within loop iterations)

### Step Result References in Workflow

During workflow execution, completed step results are available in subsequent steps via Jinja2 templates:
- `&#123;&#123; step_name &#125;&#125;` or `&#123;&#123; step_name.result &#125;&#125;` - Full result object (envelope with `status`, `data`, `error`, `meta`)
- `&#123;&#123; step_name.data &#125;&#125;` - Direct access to the data payload when step returns envelope structure
- `&#123;&#123; step_name.data.field &#125;&#125;` - Access specific fields within the data payload

**Important**: The server normalizes step results by extracting `.data` when present, so:
- `{{ step_name.field }}` usually works directly without needing `.data` prefix
- Use `{{ step_name.data.field }}` only if the step explicitly returns an envelope

### Variable Persistence Comparison

| Mechanism | Scope | Persistence | Access Pattern | Use Case |
|-----------|-------|-------------|----------------|----------|
| `workload:` | Global | Immutable after start | `{{ workload.field }}` | Static configuration |
| Step results | Execution | In-memory only | `{{ step_name.field }}` | Passing data between adjacent steps |
| `vars:` block | Execution | Database (`transient`) | `{{ vars.var_name }}` or REST API | Extracted values for reuse |
| `context:` | Global | Runtime mutable | `{{ context.field }}` | Runtime state (deprecated - use `vars:`) |

**Recommendation**: Use `vars:` block for extracting and persisting values that need to be:
- Reused across multiple steps
- Accessed via REST API externally
- Tracked for debugging (access count, timestamps)
- Survived in case of orchestrator restarts

Example:
```yaml
- step: fetch_data
  tool:
    kind: python
    code: |
      def main():
        return {"status": "success", "data": {"count": 42, "name": "test"}}
  next: process

- step: process
  tool:
    kind: python
    code: |
      def main(count, name):
        print(f"Processing {name} with count {count}")
    args:
      count: "{{ fetch_data.data.count }}"
      name: "{{ fetch_data.data.name }}"
```

### Sink Template Context (Result Unwrapping)

When a `sink:` block executes, the worker provides a **special context** where result envelopes are unwrapped for convenience:

**Available variables in sink templates:**
- **`result`** or **`data`**: Unwrapped step result data (the contents of the `data` field from the envelope)
- **`this`**: Full result envelope with `status`, `data`, `error`, `meta` fields
- **`workload`**: Global workflow variables
- **`execution_id`**: Current execution identifier
- Prior step results by name

**Important**: Use `&#123;&#123; result &#125;&#125;` not `&#123;&#123; result.data &#125;&#125;` in sink blocks, as the worker has already unwrapped the envelope.

✅ **Correct sink usage:**
```yaml
- step: generate
  tool:
    kind: python
    code: |
      def main():
        return {"status": "success", "data": {"value": 123, "message": "hello"}}
  sink:
    tool: postgres
    table: outputs
    args:
      value: "{{ result.value }}"          # Direct field access
      message: "{{ result.message }}"      # Not result.data.message
      full_data: "{{ result }}"            # Full unwrapped data object
      status_check: "{{ this.status }}"    # Envelope metadata
```

❌ **Incorrect - double nesting:**
```yaml
sink:
  args:
    value: "{{ result.data.value }}"  # WRONG: result is already unwrapped
```

---

## Template Variable Reference: `response` vs `result`

NoETL has multiple execution contexts, each with different available variables. Understanding when to use `response` vs `result` is critical for correct playbook authoring.

### Context 1: Event Conditions (`case: when:`)

**Available variables:**
- `event` - Event object with `event.name` (e.g., 'call.done', 'step.exit', 'call.error')
- `response` - Full step response/result envelope (includes status_code, data, error, etc.)

**Use case:** Checking event types and response status to decide routing

**Example:**
```yaml
case:
  - when: "{{ event.name == 'call.done' and response.status_code == 200 }}"
    then:
      next:
        - step: success_handler
  - when: "{{ event.name == 'call.error' }}"
    then:
      next:
        - step: error_handler
```

### Context 2: Action Blocks (`case: then:` - for `sink:`, `set:`)

**Available variables:**
- `result` - **Unwrapped** step result data (direct access to fields, no `.data` nesting)
- `this` - Full result envelope (status, data, error, meta)
- `workload`, `vars`, `execution_id`, prior step results

**Use case:** Accessing step output data in sink operations or variable assignments

**Example:**
```yaml
case:
  - when: "{{ event.name == 'call.done' and response.status_code == 200 }}"
    then:
      sink:
        tool:
          kind: postgres
          statement: |
            INSERT INTO users VALUES ('{{ result.user_id }}', '{{ result.name }}');
            -- ✅ Use result.field (unwrapped)
            -- ❌ NOT response.data.field
      set:
        user_count: "{{ result.count }}"  # ✅ Use result
```

### Context 3: Retry Evaluation (`retry_when:`, `stop_when:`)

**Available variables:**
- `attempt`, `max_attempts` - Retry iteration info
- `error` - Error message string (null if no error)
- `status_code` - HTTP status code (for HTTP steps)
- `success` - Boolean success flag (for DB steps)
- `result` / `data` - Last attempt's returned data

**Use case:** Deciding whether to retry based on HTTP status codes or errors

**Example:**
```yaml
tool:
  kind: http
  method: GET
  url: "https://api.example.com/data"
retry:
  max_attempts: 3
  initial_delay: 0.5
  backoff_multiplier: 2.0
  retry_when: "{{ status_code >= 500 }}"  # ✅ Direct access to status_code
  stop_when: "{{ status_code == 200 }}"   # ✅ Not response.status_code
```

### Context 4: Pagination Retry (`case: then: retry:`)

**Available variables:**
- `response` - Step response (for accessing pagination metadata)

**Use case:** Configuring next retry iteration with updated parameters

**Example:**
```yaml
case:
  - when: "{{ event.name == 'call.done' and response.data.paging.hasMore }}"
    then:
      retry:
        params:
          page: "{{ (response.data.paging.page | int) + 1 }}"  # ✅ Use response here
          pageSize: "{{ response.data.paging.pageSize }}"
```

### Quick Reference Table

| Context | Location | Use `response` | Use `result` | Use raw fields |
|---------|----------|----------------|--------------|----------------|
| **Event condition** | `case: when:` | ✅ Yes | ❌ No | ❌ No |
| **Sink/Set actions** | `case: then: sink:` | ❌ No | ✅ Yes | ❌ No |
| **Retry config** | `case: then: retry:` | ✅ Yes | ❌ No | ❌ No |
| **Retry evaluation** | `retry_when:`, `stop_when:` | ❌ No | ✅ Limited | ✅ Yes (status_code, error) |
| **Vars extraction** | `vars:` | ❌ No | ✅ Yes | ❌ No |

### Common Mistakes

❌ **Wrong - Using `response` in sink:**
```yaml
case:
  - when: "{{ event.name == 'call.done' }}"
    then:
      sink:
        tool:
          kind: postgres
          statement: "INSERT INTO users VALUES ('{{ response.data.id }}');"  # WRONG
```

✅ **Correct - Using `result` in sink:**
```yaml
case:
  - when: "{{ event.name == 'call.done' }}"
    then:
      sink:
        tool:
          kind: postgres
          statement: "INSERT INTO users VALUES ('{{ result.id }}');"  # CORRECT
```

❌ **Wrong - Using `response.status_code` in retry:**
```yaml
retry:
  retry_when: "{{ response.status_code >= 500 }}"  # WRONG
```

✅ **Correct - Using `status_code` directly in retry:**
```yaml
retry:
  retry_when: "{{ status_code >= 500 }}"  # CORRECT
```

---

## Validation Summary

- Steps named `start` typically define `next` to route to first executable step
- Steps named `end` typically omit `next` to mark workflow termination
- Each tool kind only accepts its specific configuration fields as documented
- `next` may be a string or an array of step names. If omitted, the branch ends at that step
- Step names must be unique within a workflow. References in `next` must point to existing steps
- `loop:` attribute requires both `in` and `iterator` fields
- `vars:` block templates can only access `{{ result }}` (current step result)
- Tool `kind:` must be one of: workbook, python, http, postgres, duckdb, playbook, secrets

---

## Minimal End-to-End Example

```yaml
apiVersion: noetl.io/v1
kind: Playbook
name: Minimal
path: workflows/examples/minimal
workflow:
  - step: start
    desc: Entry point
    next: ping

  - step: ping
    tool:
      kind: http
      method: GET
      endpoint: https://httpbin.org/get
      as: resp
    next: end

  - step: end
    desc: Workflow complete
```