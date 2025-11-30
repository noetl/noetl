# Core Concept

1. A playbook is a YAML declaration of a workflow.
2. The server exposes APIs used by the UI, CLI, and workers.
3. Worker pools lease work from the queue and execute playbook actions.

## Playbook Sections

Each playbook contains four logical sections:

- **metadata** – identifies the playbook (`name`, `path`, and optional `version`, `description`).
- **workload** – global variables merged with the payload supplied when you register or execute the playbook.
- **workbook** – a namespace of named actions. Steps reference these entries with `tool: workbook` and `name: <task>`.
- **workflow** – the ordered list of steps, transitions, and branching logic.

All values support Jinja2 templating so you can substitute workload variables, payload data, iterator state, or previous results.

## Step Behaviour

1. Steps live inside the `workflow` array and must have a unique `step` name.
2. Every step declares a `tool`. Supported options include `workbook`, `python`, `http`, `duckdb`, `postgres`, and `playbook` (plus any plugin-specific tools).  
   - `tool: playbook` schedules another playbook for execution (with `path` and optional `return_step`).
   - `tool: workbook` combined with `name` references a workbook task and runs its action definition.
   - Other action tools (`python`, `http`, `duckdb`, `postgres`, `secrets`, etc.) execute inline using the attributes provided on the step.
3. Iteration is modelled with a `loop` block on the step. Provide `collection`, `element`, and optional `mode` attributes. The engine runs the step once per element and can accumulate results.
4. Each step can expose a `next` list. Use `when`/`then`/`else` blocks to route execution and attach optional `data` payloads for downstream steps.
5. Steps (and workbook tasks) can include a `sink` block to funnel their results into storage-oriented actions such as Postgres, DuckDB, or HTTP.
6. Steps may declare `auth` to reference credentials resolved by the execution engine.
7. Every workflow must include a `start` step (entry router) and an `end` step to aggregate results or return them to the caller.

## Core Concept V2

NoETL is a lightweight, event-driven workflow engine. You describe intent in playbooks and NoETL evaluates steps, manages transitions, and records state so you can replay or resume executions.

### Typical Flow

1. **Author** – Write a playbook: define `metadata`, declare defaults in `workload`, add reusable actions to `workbook`, and model the step graph in `workflow`.
2. **Execute** – Run it from CLI or API, optionally providing a payload that overrides parts of `workload`.
3. **Observe** – Workers execute steps, emit events, and persist results. You inspect logs, metrics, and saved outputs.
