# Step types (overview)

Core execution step kinds:
- start: Entry point. Routes to the first executable step via `next`.
- end: Terminal step.
- http: HTTP requests (endpoint, method, headers, data, timeout, assert, save, optional retry)
- python: Inline code (code with main(...), data args, assert, save, optional retry)
- iterator: Loop controller (collection, element, task, mode, concurrency, where, order_by, limit, chunk)
- duckdb: DuckDB SQL (commands/sql, unified auth mapping, extensions, attach, save, optional retry)
- postgres: PostgreSQL SQL (command/sql, auth, idempotent DDL, upserts, save, optional retry)
- workbook: Invoke a named task defined in the `workbook` block.
- playbook: Compose and call another playbook (`path`, optional `return_step`), enabling modular pipelines.
- save: Not a top-level type; used inside steps to persist results (event log, postgres, duckdb, http, python custom code).

Cross-cutting capability:
- retry: Inline policy block available on action steps (http, python, postgres, duckdb, workbook task, inner iterator task) controlling bounded re-attempt logic (see `retry.md`).

See individual pages in this folder for capabilities, required/optional keys, context rules, and usage patterns.
