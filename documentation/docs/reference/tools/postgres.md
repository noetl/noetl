---
sidebar_position: 2
title: Postgres Tool (Canonical v10)
description: Execute PostgreSQL commands/queries as pipeline tasks with policy-driven retry and reference-first results (Canonical v10)
---

# Postgres Tool (Canonical v10)

The Postgres tool executes SQL commands/queries inside a canonical step pipeline (`step.tool`).

Canonical reminders:
- Handle errors/retry via `task.spec.policy.rules` (no legacy `eval`/`expr`).
- Use `auth: <credential_name>` to reference credentials resolved by the runtime/keychain.
- Store large results reference-first (ResultRef) when needed.

---

## Basic usage

```yaml
- step: query_users
  tool:
    - query:
        kind: postgres
        auth: pg_k8s
        command: "SELECT id, email FROM users WHERE active = true"
        spec:
          policy:
            rules:
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then: { do: break }
```

---

## Retry on transient DB errors (canonical)

```yaml
- store_page:
    kind: postgres
    auth: pg_k8s
    command: "INSERT INTO results_ok (...) VALUES (...)"
    spec:
      policy:
        rules:
          - when: "{{ outcome.status == 'error' and outcome.pg.code in ['40001','40P01'] }}"
            then: { do: retry, attempts: 5, backoff: exponential, delay: 2.0 }
          - when: "{{ outcome.status == 'error' }}"
            then: { do: fail }
          - else:
              then: { do: continue }
```

---

## Outcome helpers

A Postgres task emits an `outcome` envelope with optional helpers:
- `outcome.pg.code` (SQLSTATE or driver code)
- `outcome.pg.sqlstate`

Policies can branch on these helpers for retry vs fail-fast decisions.

---

## Reference-first results (recommended)

For large query results, prefer externalization and pass references downstream.
See:
- `documentation/docs/reference/result_storage_canonical_v10.md`
- `documentation/docs/reference/dsl/runtime_results.md`
