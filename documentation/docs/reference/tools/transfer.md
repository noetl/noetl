---
sidebar_position: 10
title: Transfer Tool (Canonical v10)
description: Declarative bulk data transfer between sources and targets (Canonical v10)
---

# Transfer Tool (Canonical v10)

The `transfer` tool performs bulk data movement between a **source** and **target** in a single pipeline task.

Canonical reminders:
- Use `task.spec.policy.rules` for retry/fail.
- Keep large intermediate data reference-first when possible.

---

## Basic usage (HTTP → Postgres)

```yaml
- step: transfer_posts
  tool:
    - xfer:
        kind: transfer
        source:
          tool: http
          url: "{{ workload.api_url }}/posts"
          method: GET
        target:
          tool: postgres
          auth:
            source: credential
            key: pg_demo
            service: postgres
          table: public.posts
        mapping:
          post_id: id
          user_id: userId
          title: title
          body: body
        spec:
          policy:
            rules:
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then: { do: break }
```

---

## Common fields

| Field | Meaning |
|---|---|
| `source.tool` | `http` \| `postgres` \| `snowflake` (implementation-defined) |
| `source.url` | HTTP URL (for HTTP sources) |
| `source.query` | SQL query (for DB sources) |
| `source.auth` | Auth config for DB sources |
| `target.tool` | `postgres` \| `snowflake` (implementation-defined) |
| `target.table` | Destination table (or `target.query` for custom writes) |
| `target.auth` | Auth config for target |
| `mapping` | Target column → source field mapping |
| `chunk_size` | Rows per chunk (optional) |
| `mode` | Append/overwrite/upsert (implementation-defined) |

---

## See also
- Snowflake tool: `documentation/docs/reference/tools/snowflake.md`
- Postgres tool: `documentation/docs/reference/tools/postgres.md`
