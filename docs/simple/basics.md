# Playbook basics and rules

Core structure
- Header: `apiVersion`, `kind`, and `metadata` (`name`, `path`, optional extras)
- Workload: global defaults merged with the execution payload
- Workflow: ordered steps with routing expressed via `next`
- Workbook: reusable named tasks referenced by `type: workbook`

Naming and references
- Each step must have a unique `step` name within the workflow
- Refer to previous outputs through `{{ step_name.result }}` or iterator aliases (`{{ this }}` inside loops)
- Execution metadata like `execution_id`, `started_at`, etc. is available for templating

Data flow
- `data` under a step evaluates expressions and becomes the argument set for the action type
- Transitions in `next` can also attach `data` so downstream steps receive shaped payloads
- Use `save` to forward results to storage-oriented actions (postgres, duckdb, http, ...)

Contracts
- `assert.expects`: validate required inputs before the action runs
- `assert.returns`: validate output shape after the action completes
- Keep the lists precise to get actionable validation errors

Control flow
- `next` controls routing to subsequent steps
  - direct continuation: `- step: end`
  - conditional: `- when: <expr>`, `then: [ { step: ... } ]`, optional `else`
  - parallel fan-out: multiple entries without `when` get scheduled together
- `type: iterator` performs per-element execution with `collection`, `element`, and an embedded `task`

Idempotency and reruns
- Prefer idempotent SQL (`CREATE TABLE IF NOT EXISTS`, `ON CONFLICT`) and deterministic identifiers (`execution_id`, iterator index)

Templating
- Expressions use Jinja2: `{{ ... }}`
- Apply filters (`| tojson`, `| default(...)`) to control formatting
- Quote strings carefully so YAML parsing and templating both succeed
