# DuckDB Tool

Run DuckDB queries for local analytics or lightweight ETL.

## Basic Usage

```yaml
- step: duckdb_query
  tool:
    kind: duckdb
    database: ":memory:"
    commands: |
      SELECT 1;
```

## Notes

- Use `database` to point to a file or `:memory:`.
- The `commands` block supports multiple statements.
