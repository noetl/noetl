# NoETL Tool Tasks Guide (Canonical v10)

This page aligns “task/action” documentation to **Canonical v10** (see `documentation/docs/reference/dsl/step_spec.md`).

In Canonical v10:
- A step executes an ordered **pipeline** of tool tasks under `step.tool`.
- Each pipeline item is a tool task with `kind: ...` (http/postgres/python/…).
- All conditionals use `when` (no legacy `eval`/`expr`/`case`).
- Retry/pagination/branching inside a step is expressed via `task.spec.policy.rules`.
- Routing between steps is server-side via `step.next.spec` + `step.next.arcs[]`.

---

## Canonical step shape (reminder)

```yaml
- step: some_step
  spec:            # optional (admission/lifecycle)
    policy:
      admit:
        rules:
          - else:
              then: { allow: true }

  loop:            # optional
    in: "{{ workload.items }}"
    iterator: item
    spec: { mode: parallel, max_in_flight: 10 }

  tool:            # ordered pipeline
    - first_task:  { kind: http, ... }
    - second_task: { kind: postgres, ... }

  next:            # router
    spec: { mode: exclusive }
    arcs:
      - step: next_step
        when: "{{ event.name == 'step.done' }}"
```

---

## Example: HTTP → Postgres (pipeline)

```yaml
- step: fetch_and_store
  tool:
    - fetch:
        kind: http
        method: GET
        url: "{{ workload.api_url }}/items"
        spec:
          policy:
            rules:
              - when: "{{ outcome.status == 'error' and outcome.http.status in [429,500,502,503,504] }}"
                then: { do: retry, attempts: 5, backoff: exponential, delay: 2 }
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then: { do: continue }

    - store:
        kind: postgres
        auth: pg_k8s
        command: "INSERT INTO items(raw) VALUES ('...')"
        spec:
          policy:
            rules:
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then: { do: break }
```

---

## Tool kinds

See:
- `documentation/docs/reference/tools/index.md`
- `documentation/docs/reference/tools/http.md`
- `documentation/docs/reference/tools/postgres.md`
- `documentation/docs/reference/tools/python.md`
- `documentation/docs/reference/tools/duckdb.md`
- `documentation/docs/reference/tools/snowflake.md`
- `documentation/docs/reference/tools/container.md`
- `documentation/docs/reference/tools/gcs.md`
- `documentation/docs/reference/tools/nats.md`
- `documentation/docs/reference/tools/transfer.md`
- `documentation/docs/reference/tools/ducklake.md`
- `documentation/docs/reference/tools/artifact_tool.md`

---

## Legacy → canonical mapping

| Legacy docs | Canonical v10 |
|---|---|
| `call:` / `type:` | tool task `kind:` |
| `endpoint:` (HTTP) | `url:` |
| `next: [ ... ]` list | `next.spec` + `next.arcs[]` |
| step-level `retry:` | `task.spec.policy.rules` |
| root/step `vars:` | `ctx` / `iter` via `set_ctx` / `set_iter` |
