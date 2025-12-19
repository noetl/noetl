# Playbook (composition) step

Compose and invoke another playbook from within a workflow.

What it does
- Loads a referenced child playbook (by path) from the catalog
- Executes it as a nested workflow with its own steps and context
- Optionally extracts a specific step's output (`return_step`) to become the parent step's result
- Supports `data`, `assert`, `save`, and `retry` like other action steps

Required keys
- `type: playbook`
- `path`: catalog path of the target playbook (e.g. `tests/fixtures/playbooks/playbook_composition/user_profile_scorer`)

Optional keys
- `return_step`: name of a step inside the child playbook whose `.data` should be surfaced as this step's output. If omitted, engine-defined default (often final step or aggregated result).
- `data`: mapping of inputs passed as the child playbook's workload overlay or root data inject (engine-specific; typically merged / available via templating inside child).
- `assert`: contracts on provided inputs (`expects`) and projected result (`returns`).
- `save`: persist projected data to storages or variables.
- `retry`: bounded retry around the entire child execution (transient failures inside propagate as `error`).

Context & data flow
- Parent step templating occurs before invoking the child.
- Child playbook gets a fresh execution context inheriting execution-level metadata (e.g., `execution_id`).
- Data passed via `data:` becomes accessible as `{{ workload.<key> }}` or dedicated injection (depending on engine implementation) inside the child.
- When `return_step` is set, the parent step's `this.data` is the `return_step.data` from the child; without it, behavior defaults to the child's final step output or an aggregation.

Example (fragment from composition test)
```yaml
- step: process_users
  type: iterator
  collection: "{{ workload.users }}"
  element: user
  mode: sequential
  task:
    task: process_users           # explicit task id for traceability
    type: playbook
    path: tests/fixtures/playbooks/playbook_composition/user_profile_scorer
    return_step: finalize_result  # surface this step's data
    data:
      user_data: "{{ user }}"
      execution_context: "{{ execution_id }}"
    sink:
      data:
        id: "{{ execution_id }}:{{ user.name }}"
        execution_id: "{{ execution_id }}"
        user_name: "{{ user.name }}"
        profile_score: "{{ this.profile_score or 0.0 }}"
        score_category: "{{ this.score_category or 'unknown' }}"
      tool: postgres
      auth: "{{ workload.pg_auth }}"
      table: public.user_profile_results
      mode: upsert
      key: id
```

Retry considerations
- Transient errors in the child bubble up as a single `error` at the composition step; use a `retry` block if the child contains external calls likely to flake.

Tips
- Keep child playbooks focused; composition is most effective with small reusable pipelines (scoring, enrichment, normalization).
- Document inputs required by the child; validate with `assert.expects` in the parent before invoking.
- Use consistent naming for `return_step` across composed playbooks to standardize extraction patterns.

See also
- `workflow.md` for step key overview
- `retry.md` for retry policy
- Other step docs for `save` patterns
