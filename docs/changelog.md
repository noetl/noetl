# Changelog (Docs)

## 0.2 — Credentials Refactor

- Added `auth:` (single credential reference resolved by Server).
- Added `credentials:` (map of aliases → { key: string }) for multi-binding steps (e.g., DuckDB).
- Introduced `{{ secret.* }}` usage inside templates for HTTP and other plugins.
- Postgres plugin resolves connections via `auth:`; non-secret overrides allowed via `with:`.
- DuckDB plugin supports native aliasing for ATTACH/CREATE SECRET via `credentials:` and exposes `credentials.<alias>.connstr` for Postgres.
- Logs redact secret material; secrets are step-scoped and not persisted.

See migration guide: docs/migration/0.2-auth-credentials-secret.md

