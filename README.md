# Not Only ETL

**NoETL** is an automation framework for Data Mesh and MLOps orchestration.

[![PyPI version](https://badge.fury.io/py/noetl.svg)](https://badge.fury.io/py/noetl)

![NoETL](https://raw.githubusercontent.com/noetl/noetl/master/noetl.png)

## Documentation

Full documentation is available at **[noetl.dev](https://noetl.dev)**

### Getting Started

- [Quick Start](https://noetl.dev/docs/getting-started/quickstart) - Get running in minutes
- [Installation](https://noetl.dev/docs/getting-started/installation) - PyPI and Kubernetes setup
- [Architecture](https://noetl.dev/docs/getting-started/architecture) - System components
- [Design Philosophy](https://noetl.dev/docs/getting-started/design-philosophy) - Architectural principles

### Playbook Guide

- [Playbook Structure](https://noetl.dev/docs/features/playbook_structure) - DSL syntax and structure
- [Variables](https://noetl.dev/docs/features/variables) - Data flow and templating
- [Iterator](https://noetl.dev/docs/features/iterator) - Looping over collections

### Reference

- [DSL Specification](https://noetl.dev/docs/reference/dsl/) - Complete DSL reference
- [CLI Reference](https://noetl.dev/docs/reference/noetl_cli_usage) - Command line usage
- [Tools Reference](https://noetl.dev/docs/reference/tools/) - HTTP, PostgreSQL, Python, DuckDB, etc.
- [Authentication](https://noetl.dev/docs/reference/auth_and_keychain_reference) - Credential handling

### Examples

- [Authentication Examples](https://noetl.dev/docs/examples/authentication/) - OAuth, tokens, credentials
- [Data Transfer](https://noetl.dev/docs/examples/data-transfer/) - ETL patterns
- [Pagination](https://noetl.dev/docs/examples/pagination/) - API pagination patterns

### Operations

- [Observability](https://noetl.dev/docs/reference/observability_services) - ClickHouse, Qdrant, NATS
- [CI/CD Setup](https://noetl.dev/docs/operations/ci-setup) - Deployment automation

## Quick Start

```bash
# Install from PyPI
pip install noetl

# Or bootstrap complete development environment
git clone https://github.com/noetl/noetl.git
cd noetl
make bootstrap
```

After bootstrap, services are available at:
- **NoETL Server**: http://localhost:8082
- **Grafana**: http://localhost:3000
- **PostgreSQL**: localhost:54321

See [Quick Start Guide](https://noetl.dev/docs/getting-started/quickstart) for details.

## Basic Usage

```bash
# Register a playbook
noetl register playbook path/to/playbook.yaml --host localhost --port 8082

# Execute a playbook
noetl run playbook "catalog/path" --host localhost --port 8082

# List playbooks
noetl catalog list playbook --host localhost --port 8082
```

## Example Playbook

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: hello_world
  path: examples/hello_world
workload:
  message: "Hello from NoETL!"
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
        # Variables injected via args: message
        result = {"status": "success", "data": {"greeting": message}}
    next:
      - step: end

  - step: end
```

## Test Fixtures

NoETL includes example playbooks in `tests/fixtures/playbooks/`:

| Category | Description |
|----------|-------------|
| `oauth/` | Google Cloud, Interactive Brokers OAuth 2.0 |
| `save_storage_test/` | Postgres and DuckDB integration |
| `duckdb_gcs/` | Google Cloud Storage operations |
| `retry_test/` | Retry patterns for HTTP, SQL, Python |
| `playbook_composition/` | Multi-playbook workflows |
| `data_transfer/` | ETL patterns |
| `hello_world/` | Getting started examples |

See [tests/fixtures/playbooks/README.md](tests/fixtures/playbooks/README.md) for complete inventory.

## Development

```bash
# Quick development cycle
task dev

# Deploy all components
task deploy-all

# Register test fixtures
task test:k8s:setup-environment

# Run tests
task test:k8s:cluster-health
```

See [Development Guide](https://noetl.dev/docs/contributing/overview) for contributing.

## License

NoETL is released under the MIT License. See [LICENSE](LICENSE) for details.
