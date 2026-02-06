---
sidebar_position: 8
title: DuckLake Tool (Canonical v10)
description: Distributed DuckDB with a PostgreSQL metastore for multi-worker concurrency (Canonical v10)
---

# DuckLake Tool (Canonical v10)

The `ducklake` tool executes DuckDB SQL with a **PostgreSQL-backed metastore** so multiple workers can read/write concurrently without DuckDB file locking conflicts.

Use it when you need:
- concurrent multi-worker writes/reads to the same logical tables
- snapshot/time-travel semantics (implementation-defined)
- shared storage-backed data path

---

## Basic usage

```yaml
- step: create_table
  tool:
    - ddl:
        kind: ducklake
        # Either provide an explicit connection string...
        # catalog_connection: "postgresql://user:pass@host:5432/ducklake_catalog"
        # ...or provide unified auth (runtime-defined)
        auth:
          source: credential
          key: ducklake_catalog_pg
          service: postgres
        catalog_name: analytics
        data_path: /opt/noetl/data/ducklake
        command: |
          CREATE TABLE IF NOT EXISTS users(id INTEGER, email VARCHAR);
          INSERT INTO users VALUES (1, 'a@example.com');
        spec:
          policy:
            rules:
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then: { do: break }
```

---

## Required fields

| Field | Meaning |
|---|---|
| `catalog_connection` | Postgres connection string for the metastore (optional if `auth` is provided) |
| `auth` | Unified auth config resolved to a Postgres connection (optional if `catalog_connection` is provided) |
| `catalog_name` | DuckLake catalog name |
| `data_path` | Shared path for data files (RWX storage in k8s) |
| `command` or `commands` | SQL to execute |

---

## See also
- DuckDB tool: `documentation/docs/reference/tools/duckdb.md`
- Retry semantics: `documentation/docs/reference/retry_mechanism_v2.md`
