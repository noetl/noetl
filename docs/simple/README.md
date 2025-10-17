# NoETL Simple Docs

A compact, example-driven guide to writing NoETL playbooks. Focused on possibilities, options, and the basic rules.

- What is a playbook? A YAML spec with four parts: Header, Workload, Workflow, and (optional) Workbook.
- Goal: Explain what each step can do, required and optional keys, and context rules, with small fragments you can adapt.

Quick navigation:
- Playbook basics and rules: ./basics.md
- Playbook parts
  - Header and metadata: ./playbook_header.md
  - Workload (inputs): ./workload.md
  - Workflow (steps and control flow): ./workflow.md
  - Workbook (reusable tasks): ./workbook.md
- Step types (focused set)
  - Overview: ./steps/index.md
  - HTTP: ./steps/http.md
  - Python: ./steps/python.md
  - Loop (iterator): ./steps/iterator.md
  - DuckDB: ./steps/duckdb.md
  - Postgres: ./steps/postgres.md
  - Saving results: ./steps/save.md
  - Playbook composition: ./steps/playbook.md
  - Retry policy: ./steps/retry.md

Examples referenced in this guide:
- Minimal HTTP loop with Python aggregation: tests/fixtures/playbooks/loop_http_test.yaml
- HTTP → DuckDB → Postgres (with per-item save): tests/fixtures/playbooks/http_duckdb_postgres/http_duckdb_postgres.yaml
- Control flow with workbook and parallel branches: tests/fixtures/playbooks/control_flow_workbook/control_flow_workbook.yaml
