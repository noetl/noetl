# Step types (overview)

- start: Entry point. Routes to the first executable step via `next`.
- end: Terminal step.
- http: HTTP requests (endpoint, method, headers, data, timeout, assert, save)
- python: Inline code (code with main(...), data args, assert, save)
- iterator: Loop controller (collection, element, task, mode, concurrency, where, order_by, limit, chunk)
- duckdb: DuckDB SQL (commands/sql, auth mapping, extensions, attach, save)
- postgres: PostgreSQL SQL (command/sql, auth, idempotent DDL, upserts, save)
- workbook: Invoke a task from the `workbook` block.
- save: Not a top-level type; used inside steps to persist results.

See individual pages in this folder for capabilities, required/optional keys, context rules, and usage patterns.
