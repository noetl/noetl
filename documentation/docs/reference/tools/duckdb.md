---
sidebar_position: 4
title: DuckDB Tool (Canonical v10)
description: Execute DuckDB SQL as pipeline tasks with unified auth and reference-first results (Canonical v10)
---

# DuckDB Tool (Canonical v10)

The DuckDB tool executes SQL inside a canonical step pipeline (`step.tool`).

Canonical reminders:
- Use `task.spec.policy.rules` for retry/fail/jump/break (no legacy `eval/expr`).
- Use unified auth (when needed) for cloud URIs and DB attachments.
- Prefer reference-first results for large outputs.

---

## Basic usage

```yaml
- step: analyze
  tool:
    - q:
        kind: duckdb
        command: "SELECT 1 AS ok"
        spec:
          policy:
            rules:
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then: { do: break }
```

---

## Command sources (supported aliases)

DuckDB accepts SQL via:
- `command` / `commands` / `query` / `queries` / `cmd` / `cmds`
- base64: `command_b64` / `commands_b64` / `query_b64`
- external script descriptor: `script: { uri, source: { type, ... } }`

See `documentation/docs/reference/script_execution_v2.md` for `script` descriptor shape.

---

## Cloud storage and attachments (overview)

If your SQL touches `gs://...` or `s3://...` URIs (e.g. `read_parquet('gs://bucket/...')`), configure credentials via `auth` (unified auth mapping; runtime-defined).

For large exports, consider writing Parquet/CSV directly to object storage and returning only a reference.

---

## See also
- Result storage (reference-first): `documentation/docs/reference/result_storage_canonical_v10.md`
- Unified auth / keychain: `documentation/docs/reference/auth_and_keychain_reference.md`
