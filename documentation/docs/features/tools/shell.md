# Shell Tool

Run shell commands from a playbook step using the local runtime or worker runtime.

## Basic Usage

```yaml
- step: list_files
  tool:
    kind: shell
    cmds:
      - ls -la
```

## Notes

- Use shell for system utilities or one-off checks.
- Prefer dedicated tools for database or HTTP actions when available.
