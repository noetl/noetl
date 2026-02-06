# HTTP in NoETL (Canonical v10)

This page previously documented legacy HTTP shapes such as:
- `tool: http` (scalar tool)
- `endpoint:` (instead of `url:`)
- workbook-style `type: http` tasks with `return:` templates

Canonical v10 uses HTTP as a **tool task** (`kind: http`) inside `step.tool`, with:
- retry/polling/pagination via `task.spec.policy.rules`
- step routing via `step.next` router arcs

## Minimal example

```yaml
- step: call_api
  tool:
    - call:
        kind: http
        method: GET
        url: "https://httpbin.org/get"
        spec:
          policy:
            rules:
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then: { do: break }
```

## See also
- Canonical HTTP tool: `documentation/docs/reference/tools/http.md`
- Retry semantics: `documentation/docs/reference/retry_mechanism_v2.md`
- Pagination pattern: `documentation/docs/reference/pagination_v2.md`
