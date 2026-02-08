# Workflow (steps and routing) — Canonical v10

In Canonical v10, `workflow:` is a list of steps connected by **server-side routing** (`step.next` router + `next.arcs[]`).

A step is composed from:
- **Admission (server):** `step.spec.policy.admit.rules`
- **Execution (worker):** `step.tool` (ordered pipeline of labeled tasks)
- **Routing (server):** `step.next.spec` + `step.next.arcs[]` guarded by `when`

Canonical removals (vs legacy docs):
- no step `type:` variants (http/python/iterator/…)
- no `step.when`
- no `eval`/`expr`/`case` conditionals (use `when` only)
- no step-level `retry:` wrappers (retry belongs to `task.spec.policy.rules`)
- no special “sink” kind (storage is “just tools” returning references)

## Minimal example

```yaml
workflow:
  - step: start
    next:
      spec: { mode: exclusive }
      arcs:
        - step: fetch

  - step: fetch
    tool:
      - call:
          kind: http
          method: GET
          url: "{{ workload.api_url }}/health"
          spec:
            policy:
              rules:
                - when: "{{ outcome.status == 'error' }}"
                  then: { do: fail }
                - else:
                    then: { do: break }
    next:
      spec: { mode: exclusive }
      arcs:
        - step: end
          when: "{{ event.name == 'step.done' }}"

  - step: end
    tool:
      - done: { kind: noop }
```

## References
- `documentation/docs/reference/dsl/playbook_structure.md`
- `documentation/docs/reference/dsl/noetl_step_spec.md`
