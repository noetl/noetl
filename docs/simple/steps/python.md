# Python step

For a more detailed usage example check: `tests/fixtures/playbooks/playbook_composition/user_profile_scorer.yaml`

Run inline Python, get a JSON-serializable result back from `main(...)`.

What it does
- Evaluates the provided code in-process.
- Calls `main(**data)` and uses its return value as the step output.
- Workbook tasks of type python are invoked the same way from workflow steps.

Required keys
- type: python
- code: Python source defining a `main(...)` function

Common optional keys
- data: Arguments passed to `main` as keyword args
- assert: Validate inputs/outputs (expects/returns)
- save: Persist the return value or a projection

Inputs and context
- Values in `data:` are evaluated from context and passed to `main`
- Access earlier step results via `{{ previous.data }}` etc.
- Use `print` for debug output (appears in logs)

Return value rules
- Must be JSON-serializable (dict/list/str/number/bool/null)
- The entire value becomes `this.data` (and `<step>.data` for later steps)

Usage patterns
- Compute derived values
  ```YAML
  - step: summarize
    type: python
    data:
      items: "{{ http_loop.data }}"
    code: |
      def main(items):
          total = len(items) if isinstance(items, list) else 0
          return {"count": total}
  ```

- Input validation with assert
  ```YAML
  - step: summarize
    type: python
    data:
      items: "{{ http_loop.data }}"
    code: |
      def main(items):
          total = len(items) if isinstance(items, list) else 0
          return {"count": total}
    assert:
      expects: [ data.items ]
      returns: [ data.count ]
  ```

- Defensive coding for early/partial values (e.g., tracking states)
  ```YAML
  - step: summarize
    type: python
    data:
      items: "{{ http_loop.data }}"
    code: |
      def main(maybe_dict):
          if not isinstance(maybe_dict, dict):
              return {"status": "tracking", "raw": str(maybe_dict)}
          return maybe_dict
  ```

Tips
- Keep code side-effect free; use dedicated steps for I/O
- Raise ValueError with clear messages for invalid inputs to produce useful logs
- All step fields (data, assert, save, etc.) are supported in workbook tasks
