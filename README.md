# Not Only ETL

**NoETL** is an automation framework for Data Mesh and MLOps orchestration.

[![PyPI version](https://badge.fury.io/py/noetl.svg)](https://badge.fury.io/py/noetl)

![NoETL](https://raw.githubusercontent.com/noetl/noetl/master/noetl.png)

## Documentation

Full documentation is available at **[noetl.io/docs](https://noetl.io/docs)**

### Getting Started

- [Quick Start](https://noetl.io/docs/getting-started/quickstart) - Get running in minutes
- [Installation](https://noetl.io/docs/getting-started/installation) - PyPI and Kubernetes setup
- [Architecture](https://noetl.io/docs/getting-started/architecture) - System components
- [Design Philosophy](https://noetl.io/docs/getting-started/design-philosophy) - Architectural principles

### Playbook Guide

- [Playbook Structure](https://noetl.io/docs/features/playbook_structure) - DSL syntax and structure
- [Variables](https://noetl.io/docs/features/variables) - Data flow and templating
- [Iterator](https://noetl.io/docs/features/iterator) - Looping over collections

### Reference

- [DSL Specification](https://noetl.io/docs/reference/dsl/) - Complete DSL reference
- [CLI Reference](https://noetl.io/docs/reference/noetl_cli_usage) - Command line usage
- [Tools Reference](https://noetl.io/docs/reference/tools/) - HTTP, PostgreSQL, Python, DuckDB, etc.
- [Authentication](https://noetl.io/docs/reference/auth_and_keychain_reference) - Credential handling

### Examples

- [Authentication Examples](https://noetl.io/docs/examples/authentication/) - OAuth, tokens, credentials
- [Data Transfer](https://noetl.io/docs/examples/data-transfer/) - ETL patterns
- [Pagination](https://noetl.io/docs/examples/pagination/) - API pagination patterns

### Operations

- [Observability](https://noetl.io/docs/reference/observability_services) - ClickHouse, Qdrant, NATS
- [CI/CD Setup](https://noetl.io/docs/operations/ci-setup) - Deployment automation

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

See [Quick Start Guide](https://noetl.io/docs/getting-started/quickstart) for details.

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
apiVersion: noetl.io/v1
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
    tool: python
    code: |
      def main(input_data):
        return {"greeting": input_data["message"]}
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

See [Development Guide](https://noetl.io/docs/development/development) for contributing.

## License

NoETL is released under the MIT License. See [LICENSE](LICENSE) for details.
