# Python step

Run inline Python, get a JSON-serializable result back from `main(...)`.

What it does
- Evaluates the provided code in-process.
- Calls `main(**data)` and uses its return value as the step output.

Required keys
- type: python
- code: Python source defining a `main(...)` function

Common optional keys
- data: Arguments passed to `main` as keyword args
- assert: Validate inputs/outputs (expects/returns)
- sink: Persist the return value or a projection

Inputs and context
- Values in `data:` are evaluated from context and passed to `main`.
- Access earlier step results via `{{ previous.data }}` etc.

Return value rules
- Must be JSON-serializable (dict/list/str/number/bool/null)
- The entire value becomes `this.data` (and `<step>.data` for later steps)

Usage patterns
- Compute derived values
  ```yaml
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
  ```yaml
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
  ```yaml
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
- Keep code side-effect free; use dedicated steps for I/O.
- Raise ValueError with clear messages for invalid inputs to produce useful logs.

Retry
- Add a `retry` block when code may raise intermittent exceptions (network calls, random test failures).
- Context vars: `error`, `attempt`, `max_attempts`, plus any partial `data` if produced before exception handling.
```yaml
retry:
  max_attempts: 5
  initial_delay: 0.2
  backoff_multiplier: 1.5
  max_delay: 2.0
  retry_when: "{{ error != None }}"
```
Use `stop_when` if you detect a stable success condition distinct from error absence.
