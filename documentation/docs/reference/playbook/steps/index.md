# Step patterns (overview) — Canonical v10

Canonical v10 does **not** have step “types” (no `type: http|python|iterator|...`).

Steps are built from:
- `spec` (including `spec.policy.admit` admission)
- optional `loop` (`in` + `iterator` + `loop.spec`)
- `tool` (ordered pipeline of labeled tasks with `kind:`)
- `next` (router: `next.spec` + `next.arcs[]`)

This folder is now a set of pointers to the canonical v10 pages:
- HTTP: `documentation/docs/reference/tools/http.md`
- Python: `documentation/docs/reference/tools/python.md`
- Postgres: `documentation/docs/reference/tools/postgres.md`
- DuckDB: `documentation/docs/reference/tools/duckdb.md`
- Snowflake: `documentation/docs/reference/tools/snowflake.md`
- Loops: `documentation/docs/reference/iterator_v3.md`
- Retry: `documentation/docs/reference/retry_mechanism_v2.md`
- Storage: `documentation/docs/reference/result_storage_canonical_v10.md`
- Step spec: `documentation/docs/reference/dsl/noetl_step_spec.md`
