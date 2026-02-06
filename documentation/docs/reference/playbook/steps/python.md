# Python in steps — Canonical v10

Canonical v10 has no `tool: python` step type. Use a Python **tool task** (`kind: python`) inside `step.tool`.

```yaml
- step: transform
  tool:
    - run:
        kind: python
        args:
          items: "{{ workload.items }}"
        code: |
          result = {"count": len(items)}
        spec:
          policy:
            rules:
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then: { do: break }
```

## See also
- Canonical Python tool: `documentation/docs/reference/tools/python.md`
- Script loading / script jobs: `documentation/docs/reference/script_execution_v2.md`
