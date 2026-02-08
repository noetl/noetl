---
sidebar_position: 1
title: HTTP Tool (Canonical v10)
description: Make HTTP requests as pipeline tasks with policy-driven retry/pagination (Canonical v10)
---

# HTTP Tool (Canonical v10)

The HTTP tool executes HTTP requests inside a canonical step pipeline (`step.tool`).

Canonical reminders:
- Use `when` in policies/arcs (no legacy `eval`/`expr`, no `case`).
- Handle retry/pagination via `task.spec.policy.rules` (`do: retry|jump|break|fail|continue`).
- Prefer reference-first results for large payloads.

---

## Basic usage

```yaml
- step: fetch_data
  tool:
    - call:
        kind: http
        method: GET
        url: "https://api.example.com/data"
        headers:
          Content-Type: application/json
        spec:
          timeout: { connect: 5, read: 15 }
          policy:
            rules:
              - when: "{{ outcome.status == 'error' and outcome.http.status in [429,500,502,503,504] }}"
                then: { do: retry, attempts: 5, backoff: exponential, delay: 2.0 }
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then: { do: break }
```

---

## Common fields

| Field | Type | Meaning |
|---|---|---|
| `method` | string | HTTP method (GET/POST/PUT/PATCH/DELETE) |
| `url` | string | Request URL (Jinja2 templating allowed) |
| `headers` | mapping | Request headers |
| `params` | mapping | Query parameters |
| `body` / `payload` | mapping/string | Request body (implementation-defined; JSON by default in many runtimes) |
| `auth` | string | Credential reference name (resolved by runtime/keychain) |
| `spec.timeout` | mapping | Connection/read timeouts (implementation-defined) |
| `spec.policy.rules` | list | Task outcome handling (retry/jump/break/fail/continue) |
| `spec.result` | mapping | Reference-first output policy (ResultRef) |

> Canonical field name is `url`. Some runtimes may accept `endpoint` as a legacy alias, but docs and canonical examples use `url`.

---

## Authentication

Two common patterns:

### 1) Credential reference (`auth`)

```yaml
- call_api:
    kind: http
    auth: openai_token
    method: GET
    url: "https://api.example.com/private"
```

### 2) Header templating (read-only `keychain.*`)

```yaml
- call_api:
    kind: http
    method: GET
    url: "https://api.example.com/private"
    headers:
      Authorization: "Bearer {{ keychain.openai_token }}"
```

If you template secret bytes into headers, ensure inputs are redacted in logs/events.

See `documentation/docs/reference/auth_and_keychain_reference.md`.

---

## Outcome envelope

The HTTP task produces a final `outcome`:
- `outcome.status`: `"ok"` or `"error"`
- `outcome.http.status`: HTTP status code (when available)
- `outcome.http.headers`: response headers (when available)
- `outcome.result`: response body (small inline payload or reference)

Many runtimes wrap response bodies as:
- `outcome.result.data` = parsed JSON body

Align your templates/policies to the wrapper used by your HTTP executor.

---

## Pagination (canonical)

Canonical v10 pagination is a streaming pipeline pattern using `jump`/`break` and `iter.*` state.
See:
- `documentation/docs/reference/pagination_v2.md`
- `documentation/docs/reference/dsl/pagination.md`

---

## Reference-first results (recommended)

For large bodies, configure `spec.result` to externalize payloads and extract small fields:

```yaml
- fetch_page:
    kind: http
    method: GET
    url: "{{ workload.api_url }}/items"
    spec:
      result:
        store: { kind: auto, scope: execution, ttl: "1h", compression: gzip }
        select:
          - path: "$.paging.hasMore"
            as: has_more
```

See `documentation/docs/reference/result_storage_canonical_v10.md`.
