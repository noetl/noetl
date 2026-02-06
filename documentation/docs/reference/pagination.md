---
sidebar_position: 13
title: HTTP Pagination (Canonical v10)
description: Canonical pagination patterns for NoETL DSL — streaming pagination with task policy (retry/jump/break) and outer-loop fan-out
---

# HTTP Pagination (Canonical v10)

Canonical v10 models pagination as a **deterministic streaming state machine inside a step pipeline**:

- **No** `loop.pagination:` block
- **No** step-level `retry:` wrapper
- **No** legacy `eval`/`expr`
- Pagination uses:
  - iteration state (`iter.*`)
  - task outcome policy (`task.spec.policy.rules`)
  - pipeline control actions (`do: jump` / `do: break`)

If you need high parallelism and ordered paging:
- **outer loop fan-out** (parallel/distributed) via `step.loop`
- **inner ordered pagination stream** (sequential per item) inside each iteration lease

For the full canonical walkthrough + example, see:
- `documentation/docs/reference/dsl/pagination.md`
- `documentation/docs/reference/dsl/noetl_step_spec.md`

---

## Canonical streaming pagination skeleton

```yaml
- step: fetch_all_pages

  loop:
    spec: { mode: parallel, max_in_flight: 10 }
    in: "{{ workload.endpoints }}"
    iterator: endpoint

  tool:
    - init_iter:
        kind: noop
        spec:
          policy:
            rules:
              - else:
                  then:
                    do: continue
                    set_iter: { page: 1, has_more: true }

    - fetch_page:
        kind: http
        method: GET
        url: "{{ workload.api_url }}{{ iter.endpoint.path }}"
        params:
          page: "{{ iter.page }}"
          pageSize: "{{ iter.endpoint.page_size }}"
        spec:
          policy:
            rules:
              - when: "{{ outcome.status == 'error' and outcome.http.status in [429,500,502,503,504] }}"
                then: { do: retry, attempts: 10, backoff: exponential, delay: 2.0 }
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then:
                    do: continue
                    set_iter:
                      has_more: "{{ outcome.result.data.paging.hasMore | default(false) }}"

    - store_page:
        kind: postgres
        auth: pg_k8s
        command: "INSERT INTO pages (...)"
        spec:
          policy:
            rules:
              - when: "{{ outcome.status == 'error' and outcome.pg.code in ['40001','40P01'] }}"
                then: { do: retry, attempts: 5, backoff: exponential, delay: 2.0 }
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then: { do: continue }

    - paginate:
        kind: noop
        spec:
          policy:
            rules:
              - when: "{{ iter.has_more == true }}"
                then:
                  do: jump
                  to: fetch_page
                  set_iter:
                    page: "{{ (iter.page | int) + 1 }}"
              - else:
                  then: { do: break }

  next:
    spec: { mode: exclusive }
    arcs:
      - step: validate_results
        when: "{{ event.name == 'loop.done' }}"
      - step: cleanup
        when: "{{ event.name == 'step.failed' }}"
```

Key property: **no fall-through**. Branching inside a pipeline should use `jump` to ensure only the intended tasks execute.
