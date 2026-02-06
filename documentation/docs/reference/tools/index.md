---
sidebar_position: 0
title: Tools Overview (Canonical v10)
description: Overview of NoETL tool kinds and how to use them inside canonical v10 step pipelines
---

# NoETL Tools Reference (Canonical v10)

NoETL tools are executed as **tasks** inside a canonical step pipeline (`step.tool`).

Canonical v10 reminders:
- A step is: admission policy (`step.spec.policy.admit`) + ordered task pipeline (`step.tool`) + router (`step.next` arcs).
- Task outcome handling is done via `task.spec.policy.rules` (no legacy `eval`/`expr`).
- Large outputs are reference-first (ResultRef/ManifestRef patterns).

See `documentation/docs/reference/dsl/noetl_step_spec.md` for the full DSL model.

---

## Available tool kinds

| Kind | Description | Use case |
|------|-------------|----------|
| `http` | HTTP requests | APIs, webhooks, polling |
| `postgres` | PostgreSQL commands/queries | OLTP + result storage |
| `python` | Inline Python execution | transforms, custom logic |
| `duckdb` | DuckDB queries | analytics, local joins |
| `snowflake` | Snowflake queries | warehouse operations |
| `container` | Job/container execution | heavy deps, isolation |
| `gcs` | Google Cloud Storage | export/import artifacts |
| `ducklake` | Lakehouse queries | unified analytics |
| `nats` | JetStream/KV/Object Store | state, messaging, artifacts |

---

## Canonical usage pattern

### Basic task in a pipeline

```yaml
- step: fetch_ping
  tool:
    - call:
        kind: http
        method: GET
        url: "{{ workload.api_url }}/ping"
        spec:
          policy:
            rules:
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then: { do: break }
```

### With routing

```yaml
next:
  spec: { mode: exclusive }
  arcs:
    - step: end
      when: "{{ event.name == 'step.done' }}"
```

### With authentication

Canonical approach:
- declare required credentials under root `keychain`
- reference credentials by name in tasks (for example `auth: pg_k8s`)

See `documentation/docs/reference/auth_and_keychain_reference.md`.

---

## Outcome envelope (canonical)

Each task produces an `outcome`:
- `outcome.status`: `"ok"` or `"error"`
- `outcome.result`: success output (small inline payload or reference)
- `outcome.error`: structured error (`kind` required; `retryable` recommended)
- `outcome.meta`: timing/attempt metadata

Policies (`task.spec.policy.rules`) evaluate over `outcome`.

---

## Template namespaces

Common namespaces available in templates:
- `workload.*` (immutable merged input)
- `keychain.*` (resolved credentials; read-only)
- `ctx.*` (execution-scoped mutable context)
- `iter.*` (iteration-scoped mutable context; loops only)
- `args.*` (token payload / arc inscription)
- pipeline locals: `_prev`, `_task`, `_attempt`, `outcome` (policy evaluation)
- routing: `event` (boundary event; `next.arcs[].when`)

---

## See also

- `documentation/docs/reference/dsl/spec.md`
- `documentation/docs/reference/dsl/runtime_events.md`
- `documentation/docs/reference/dsl/runtime_results.md`
- `documentation/docs/reference/retry_mechanism_v2.md`
- `documentation/docs/reference/pagination_v2.md`
