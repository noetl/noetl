---
sidebar_position: 0
title: Examples Overview
description: Practical examples to get started with NoETL
---

# NoETL Examples

This section provides practical examples demonstrating NoETL patterns and integrations.

:::info Source of Truth
All working, tested playbooks live in the repository at:
**[tests/fixtures/playbooks/](https://github.com/noetl/noetl/tree/master/tests/fixtures/playbooks)**

The examples documented here reference those tested implementations.
:::

## Quick Start

### Hello World

The simplest NoETL playbook:

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: hello_world
  path: examples/hello_world

workload:
  message: "Hello World"

workflow:
  - step: start
    next:
      - step: greet

  - step: greet
    tool:
      kind: python
      libs: {}
      args:
        message: "{{ workload.message }}"
      code: |
        # Pure Python code - no imports, no def main()
        result = {"status": "success", "data": {"greeting": f"HELLO: {message}"}}
    next:
      - step: end

  - step: end
```

**Run it:**
```bash
# Local execution
noetl run tests/fixtures/playbooks/hello_world/hello_world.yaml -v

# Distributed execution (requires registration)
noetl register playbook tests/fixtures/playbooks/hello_world/hello_world.yaml
noetl run tests/fixtures/playbooks/hello_world -r distributed
```

## Example Categories

### [Authentication](./authentication/)
OAuth integrations with Auth0, Google Cloud, and other providers.

### [Data Transfer](./data-transfer/)
Patterns for moving data between HTTP APIs and databases (PostgreSQL, Snowflake, DuckDB).

### [Pagination](./pagination/)
HTTP pagination patterns: page-number, cursor, offset, and combined retry strategies.

### [Integrations](./integrations/)
External API integrations and cloud service connectivity.

## Test Fixture Reference

The following directories contain complete, tested playbooks:

| Directory | Description |
|-----------|-------------|
| `hello_world/` | Basic workflow validation |
| `pagination/` | All pagination patterns (basic, cursor, offset, retry) |
| `data_transfer/` | HTTP → PostgreSQL, Snowflake transfers |
| `oauth/` | Google OAuth, Secret Manager, GCS |
| `api_integration/` | Auth0, webhook handlers |
| `control_flow/` | Conditional branching, workbook patterns |
| `iterator_save_test/` | Iterator with database saves |
| `ducklake_test/` | Distributed DuckDB with PostgreSQL metastore |
| `script_execution/` | External script loading (GCS, S3, file) |
| `retry_test/` | Retry mechanism validation |
| `container_postgres_init/` | Kubernetes container jobs |

## Running Examples

### Prerequisites

1. NoETL server running (Kubernetes or local)
2. PostgreSQL database available
3. Required credentials registered

### Using Task Runner

```bash
# Full test with setup
task test-hello-world-full

# Pagination tests
task test:pagination:basic
task test:pagination:cursor
task test:pagination:retry

# Data transfer tests
task test-http-to-postgres-transfer-full
```

### Using CLI

```bash
# Local execution (file path)
noetl run tests/fixtures/playbooks/my_playbook.yaml --set key=value -v

# Distributed execution (catalog path - requires registration first)
noetl register playbook tests/fixtures/playbooks/my_playbook.yaml
noetl run catalog/path/to/playbook -r distributed --set key=value
```

## Contributing Examples

To add new examples:

1. Create playbook in `tests/fixtures/playbooks/<category>/`
2. Add `README.md` with documentation
3. Add corresponding task in `taskfile.yml` for testing
4. Update fixture inventory in `tests/fixtures/playbooks/README.md`
