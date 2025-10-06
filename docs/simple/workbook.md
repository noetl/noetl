# Workbook (reusable tasks)

Optional block for named tasks reusable across workflows.

What it is
- A list of named actions with the same shape as normal steps (type, data, code/command/sql, assert, save)
- Invoked from workflow steps via `type: workbook` and a reference to the task by `name`

Required keys
- workbook: list of tasks
- Each task: name, type, and implementation fields for that type

Invocation from workflow
- Use a workflow step with `type: workbook`
- Reference the task by `name` (not `task`)
- Pass `data:` like any other step

Patterns (fragments)
- Small Python utilities (validation, transformations)
- SQL snippets for parameterized DDL/DML
- Composable building blocks used by multiple playbooks

Tips
- Keep task names unique within the workbook.
- Use `assert` on tasks to document inputs/outputs.
- Prefer pure functions in Python tasks for predictability.
- Workbook tasks support all step fields (type, data, code, assert, save, etc.)
