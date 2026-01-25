# Python Tool

Run inline Python code inside a playbook step.

## Basic Usage

```yaml
- step: transform
  tool:
    kind: python
    args:
      value: "{{ workload.input }}"
    code: |
      result = {"value": value, "status": "ok"}
```

## Notes

- Code runs without a `def main()` wrapper.
- Use `args` to inject values into the script scope.
