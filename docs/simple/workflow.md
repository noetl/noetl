# Workflow (steps and control flow)

An ordered list of steps. Each step is isolated; pass data explicitly via `data:`. Control flow is defined by `next`.

Required keys
- workflow: list of steps
- Each step: `step` (unique id), optional `type` (default is an operation; special: start/end)

Step keys (common)
- step: unique name
- desc: human-readable description
- type: http | python | iterator | duckdb | postgres | workbook | start | end
- data: inputs for the step (templated)
- implementation fields: code | command | sql | endpoint | ... (depends on type)
- assert: input/output contracts (expects, returns)
- save: persist outputs to variables or storages
- next: transitions to subsequent steps

Transitions (next)
- Single continuation: one entry
- Conditional branches: multiple entries with `when`
- Parallel fan-out: multiple entries without `when` (run concurrently)
- Iterator: use `type: iterator` to fan out per item and aggregate

Data passing rules
- `data:` is evaluated before the step executes and passed into the step implementation
- Step result becomes `this.data` during the step and `<step>.data` afterwards
- Use `save` when you need named variables or external persistence

Common patterns (fragments)
- Linear chain: start → A → B → end
- Conditional route: branch on a flag (true/false)
- Parallel fan-out: two or more next steps with no conditions
- Per-item loop: iterator over a list with inner task and aggregated save

Tips
- Keep step names stable for easy referencing (`<step>.data`).
- Use `assert` for clearer failures and contract validation.
- Prefer small steps with single responsibility for better reuse and testing.

Minimal structure:
```yaml
workflow:
- step: start
  next:
  - step: my_step
- step: my_step
  type: python
  data:
    some_input: "{{ workload.message }}"
  code: |
    def main(some_input):
        return {"echo": some_input}
  next:
  - step: end
- step: end
  type: end
```
