# Playbook basics and rules

Core structure
- Header: apiVersion, kind, metadata (name, path)
- Workload: input values for this run (YAML types)
- Workflow: ordered steps with control flow via `next`
- Workbook: reusable named tasks referenced by `type: workbook`

Naming and references
- Each step must have a unique `step` name within the workflow
- Refer to results with `<step_name>.data`
- Global execution fields: `execution_id`, `started_at`, etc. may be available

Data flow
- `data:` under a step evaluates expressions and becomes arguments/inputs
- Step output becomes `this.data` during that step and `<step>.data` afterwards
- Use `save` to persist outputs to variables or external storages

Asserts (contracts)
- `assert.expects`: validate required inputs before the step runs
- `assert.returns`: validate presence of output fields after the step
- Prefer small, precise lists to get clear error messages

Control flow
- `next:` controls routing to subsequent steps
  - single continuation: one entry under `next`
  - conditional: list of `{ when, step }`
  - parallel fan-out: multiple entries without `when`
- `type: iterator` provides per-item fan-out and aggregation

Idempotency and reruns
- Prefer CREATE TABLE IF NOT EXISTS and ON CONFLICT for DB steps
- Use deterministic ids (e.g., `execution_id`, index) for per-item writes

Templating
- Expressions are Jinja-like: `{{ ... }}`
- Use filters like `| tojson` when embedding complex values into SQL or JSON bodies
- Quote strings carefully to avoid YAML parsing issues
