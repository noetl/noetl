# Snowflake ↔ Postgres transfer (quickstart) — Canonical v10

Canonical v10:
- Use `kind: transfer` (or tool-specific patterns) inside `step.tool`.
- Handle retry via `task.spec.policy.rules`.
- Store large intermediate payloads reference-first (ResultRef) and load with `kind: artifact`.

## See also
- Transfer tool: `documentation/docs/reference/tools/transfer.md`
- Snowflake tool: `documentation/docs/reference/tools/snowflake.md`
- Postgres tool: `documentation/docs/reference/tools/postgres.md`
