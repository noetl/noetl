# Playbook Declaration Notes

- Playbooks are rendered with Jinja2 before execution. Every string can reference `workload`, iterator context, prior step results, or execution metadata.
- Include a `metadata` block with `name` and `path` (plus optional `version`, `description`, labels, annotations).
- Define `workload` as the global variables merged with the payload supplied when registering or executing the playbook.
- Use `workbook` to hold reusable action definitions; workflow steps can reference them with `type: workbook` and `name: <task>`.
- Model the execution graph in the `workflow` array. Provide a `start` step for entry routing and an `end` step to aggregate or return results.
- Every step declares its identifier with the `step` attribute and can add a `desc` for documentation.
- Give each step a `type`. Steps support the same action types as workbook tasks, plus the special `workbook` type for indirection.
- `type: workbook` steps must include `name` so the engine can locate the task definition.
- `type: python` runs code via `def main(input_data): ...`. Inputs are passed through the step `data` mapping.
- `type: playbook` composes another playbook. Use `path` (and optional `return_step`) to decide what to expose back to the parent.
- Iteration uses `type: iterator` with `collection`, `element`, and a nested `task` definition. Iterator steps can run sequentially or in parallel (`mode`).
- Each action may include an `auth` block (string alias or structured) for credential lookup.
- Attach `save` to fan out the action result into another persistence-oriented action (postgres, duckdb, http, etc.).
- Steps define downstream routing with `next`. You can combine direct targets, `when`/`then` conditions, and `else` fallbacks.
- `next` entries (or targets inside `then`/`else`) can attach `data` to shape the payload received by the next step.
- Expose meaningful results from actions; they remain accessible via `{{ step_name.result }}` or iterator scopes like `{{ this }}`.
- Always declare an `end` step so the engine can finalise the workflow (persist summaries, propagate results to parent playbooks, etc.).
- The maintained fixtures (`control_flow_workbook`, `http_duckdb_postgres`, `playbook_composition`, `user_profile_scorer`) serve as canonical references for structure and advanced patterns.
