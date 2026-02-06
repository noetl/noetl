# Playbook composition in steps — Canonical v10

If your runtime supports composition, invoke a nested playbook as a **tool task** (`kind: playbook`) inside a step pipeline.

The nested execution behaves like any other task:
- the worker produces an `outcome`
- task policy decides retry/fail/continue
- server routing (`next.arcs`) decides subsequent steps

Example (shape only; tool fields are runtime-defined):

```yaml
- step: run_child
  tool:
    - child:
        kind: playbook
        path: "catalog/path/to/child"
        args:
          user_id: "{{ workload.user_id }}"
        spec:
          policy:
            rules:
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then: { do: break }
```

## See also
- Step spec: `documentation/docs/reference/dsl/noetl_step_spec.md`
