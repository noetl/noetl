# Workbook (reusable tasks)

Optional block for named tasks reusable across workflows.

What it is
- A list of named actions with the same shape as workflow steps (type, data, auth, code/command/sql, assert, save)
- Invoked from workflow steps via `type: workbook` and a `name` reference

Required keys
- `workbook`: array of task objects
- Each task: `name`, `type` (any action type except `workbook`), plus fields required by that action

Invocation from workflow
- Create a workflow step with `type: workbook`
- Provide `name: <task>` so the engine resolves the workbook entry
- Pass `data` just like any other step to override inputs on that invocation

Patterns
- Small Python utilities (validation, transformations)
- Parameterised SQL snippets (Postgres, DuckDB)
- Reusable HTTP integrations shared across steps or playbooks

Tips
- Keep task names unique within the workbook scope
- Document expectations with `assert.expects`/`assert.returns`
- Combine with `save` to persist reusable action results consistently
