# Storage/save in steps — Canonical v10

Canonical v10 removes the step-level `sink:` / `save:` blocks.

Storage is a **pattern**:
- use normal tools (postgres/duckdb/gcs/nats/…) to persist data
- return a reference (ResultRef / TempRef) for large payloads
- optionally patch non-secret metadata into `ctx`/`iter` via task policy (`set_ctx` / `set_iter`)

## See also
- Result storage (canonical): `documentation/docs/reference/result_storage_canonical_v10.md`
- ResultRef / TempRef: `documentation/docs/reference/tempref_storage.md`
- Scopes (`workload/ctx/iter`): `documentation/docs/reference/variables_v2.md`
