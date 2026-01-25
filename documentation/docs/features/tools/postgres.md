# Postgres Tool

Run SQL statements against PostgreSQL.

## Basic Usage

```yaml
- step: query
  tool:
    kind: postgres
    auth: pg_local
    query: "SELECT 1"
```

## Notes

- Use `auth` or `credentials` to bind connection settings.
- For large scripts, use the `script` attribute.
