# HTTP in steps — Canonical v10

Canonical v10 has no `tool: http` step type. Use an HTTP **tool task** (`kind: http`) inside `step.tool`.

```yaml
- step: call_api
  tool:
    - call:
        kind: http
        method: GET
        url: "{{ workload.api_url }}/v1/data"
        spec:
          policy:
            rules:
              - when: "{{ outcome.status == 'error' and outcome.http.status in [429,500,502,503,504] }}"
                then: { do: retry, attempts: 5, backoff: exponential, delay: 2 }
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then: { do: break }
```

## See also
- Canonical HTTP tool: `documentation/docs/reference/tools/http.md`
- Retry semantics: `documentation/docs/reference/retry_mechanism_v2.md`
- Pagination pattern: `documentation/docs/reference/pagination_v2.md`
