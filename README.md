# Not Only ETL

__NoETL__ is an automation framework for Data Mash and MLOps orchestration.

[![PyPI version](https://badge.fury.io/py/noetl.svg)](https://badge.fury.io/py/noetl)


## System Architecture

The following diagram illustrates the main parts and intent of the NoETL system:

![NoETL System Diagram](docs/images/NoETL.png)

- Server: orchestration + API endpoints (catalog, credentials, events)
- Worker: background worker pool, no HTTP endpoints
- Noetl CLI: manages worker pools and server lifecycle

## Quick Start

## Concept
- [Playbook notes](docs/concepts/playbook_notes.md)


### Installation

- Install NoETL from PyPI:
  ```bash
  pip install noetl
  ```
- Install a specific version:
  ```bash
  pip install noetl==1.0.4
  ```

### Local Development Environment

For a complete local development environment with server, workers, postgres, and monitoring stack:

```bash
# Clone repository
git clone https://github.com/noetl/noetl.git
cd noetl

# Bootstrap: Install all tools and provision complete environment
# This runs Taskfile commands under the hood (task bootstrap)
make bootstrap

# What bootstrap does:
# 1. Installs required tools: Docker, kubectl, helm, kind, task, psql, pyenv, tfenv, uv
# 2. Creates Kind Kubernetes cluster
# 3. Builds NoETL Docker image
# 4. Deploys PostgreSQL database
# 5. Deploys observability stack (ClickHouse, Qdrant, NATS JetStream)
# 6. Deploys monitoring stack (VictoriaMetrics, Grafana, VictoriaLogs)
# 7. Deploys NoETL server and workers

# After bootstrap, you can use task commands directly:
task --list                  # Show all available tasks
task noetl:k8s:deploy        # Deploy NoETL components
task postgres:k8s:deploy     # Deploy PostgreSQL
task monitoring:k8s:deploy   # Deploy monitoring stack
```

**Services available after bootstrap:**
- **NoETL Server**: http://localhost:8082 (API & UI)
- **Grafana Dashboard**: http://localhost:3000 (admin credentials via `task grafana`)
- **VictoriaMetrics**: http://localhost:9428/ 
- **VictoriaLogs**: http://localhost:9428/select/vmui/
- **Postgres**: `jdbc:postgresql://localhost:54321/demo_noetl` (user: demo, password: demo, database: demo_noetl)
- **ClickHouse HTTP**: http://localhost:30123 (OLAP database for logs/metrics/traces)
- **ClickHouse Native**: localhost:30900 (native protocol)
- **Qdrant HTTP**: http://localhost:30633 (vector database REST API)
- **Qdrant gRPC**: localhost:30634 (vector database gRPC)
- **NATS Client**: localhost:30422 (messaging)
- **NATS Monitoring**: http://localhost:30822 (dashboard)

**Cleanup:**
```bash
# Destroy environment and clean up all resources
# This runs multiple Taskfile commands under the hood:
# - task kind:local:cluster-delete (delete Kind cluster)
# - task docker:local:cleanup-all (clean Docker resources)
# - task cache:local:clean (clear cache directories)
# - task noetl:local:clear-all (clear NoETL data/logs)
make destroy
```

**Development Workflow:**
```bash
# Quick development cycle (build + reload)
task dev                     # Executes: task docker:local:build → task kind:local:image-load → task noetl:k8s:restart

# Fast rebuild without cache
task dev-fast

# Deploy all components
task deploy-all              # Executes: task postgres:k8s:deploy → task monitoring:k8s:deploy → task noetl:k8s:deploy

# Register test credentials and playbooks (one-time setup after deployment)
task test:k8s:setup-environment   # Register all credentials and playbooks for testing

# Check cluster health
task test-cluster-health
```

All `make` commands execute Taskfile automation under the hood. Use `task --list` to see all available tasks.

### Using NoETL as a Submodule

If you're integrating NoETL into another project as a Git submodule and want to use its full development infrastructure (Kind cluster, PostgreSQL, monitoring, task automation), follow these steps:

```bash
# Add NoETL as a submodule (name it .noetl to keep it hidden)
git submodule add https://github.com/noetl/noetl.git .noetl
git submodule update --init --recursive

# Run bootstrap to install all tools and provision environment
# This executes .noetl/ci/bootstrap/bootstrap.sh under the hood
make -C .noetl bootstrap
```

**Note:** The submodule must be named `.noetl` (hidden directory) for the bootstrap to work correctly. 

The bootstrap automatically:
- Installs all required tools (Docker, kubectl, helm, kind, **task**, psql, pyenv, tfenv, uv, Python 3.12+)
- Sets up Python virtual environment with your project + NoETL dependencies
- Creates project Taskfile.yml that imports all NoETL tasks
- Deploys Kind cluster with PostgreSQL, observability (ClickHouse, Qdrant, NATS), and monitoring stack
- Copies template files (.env.local, pyproject.toml, .gitignore, credentials/)
- Creates project directories (credentials/, playbooks/, data/, logs/, secrets/)

**Important:** The bootstrap installs `task` (Taskfile automation tool), so run it before using any `task` commands.

After bootstrap completes, all NoETL infrastructure tasks are available with `noetl:` prefix:

```bash
# Use NoETL tasks from your project root
task noetl:postgres:k8s:deploy         # Deploy PostgreSQL
task noetl:noetl:k8s:deploy            # Deploy NoETL server and workers
task noetl:test:k8s:cluster-health     # Check cluster health

# Register test credentials and playbooks for Kind environment
task noetl:test:k8s:setup-environment  # Complete setup (credentials + playbooks)
task noetl:test:k8s:register-credentials   # Register credentials only
task noetl:test:k8s:register-playbooks     # Register playbooks only

# Your project-specific tasks (defined in Taskfile.yml)
task dev:run                           # Run your application
```

**Cleanup:**
```bash
# Destroy NoETL environment and clean up all resources
make -C .noetl destroy
```

**Documentation:**
- [Bootstrap README](.noetl/ci/bootstrap/README.md) - Complete guide and reference
- [Bootstrap Quickstart](.noetl/ci/bootstrap/QUICKSTART.md) - Step-by-step tutorial
- [Bootstrap Implementation](.noetl/ci/bootstrap/IMPLEMENTATION.md) - Technical deep dive

The bootstrap system creates a clean separation between your project and NoETL infrastructure while providing access to all development tools.

## Quick Reference

### Local Development (Taskfile-based)
```bash
make bootstrap               # Provision complete environment (runs task bootstrap)
make destroy                 # Destroy environment and clean all resources
task --list                  # Show all available tasks
task dev                     # Quick development cycle
task deploy-all              # Deploy all components
```

### Makefile Commands
```bash
make help                    # Show help
make bootstrap               # Bootstrap environment (installs tools + deploys everything)
make destroy                 # Clean up all resources (cluster, Docker, caches)
```

**Note:** All `make` commands execute Taskfile tasks under the hood. The Makefile provides convenient shortcuts.

## Basic Usage

NoETL is primarily deployed as a Kubernetes-based service. After running `make bootstrap`, the server and workers are already running in your Kind cluster.

### Working with Playbooks

```bash
# Register credentials and playbooks for Kind environment (one-time setup)
task test:k8s:setup-environment     # Register all test credentials and playbooks
# Or individually:
task test:k8s:register-credentials  # Register test credentials only
task test:k8s:register-playbooks    # Register test playbooks only

# Register a single playbook to the catalog
noetl register tests/fixtures/playbooks/hello_world/hello_world.yaml --host localhost --port 8082

# List registered playbooks
noetl catalog list playbook --host localhost --port 8082

# Execute a registered playbook by path
noetl execute playbook "tests/fixtures/playbooks/hello_world" --host localhost --port 8082

# Execute with custom payload data (merged with workload)
noetl execute playbook "tests/fixtures/playbooks/hello_world" \
  --host localhost --port 8082 \
  --payload '{"custom_var": "value"}' --merge
```

### Local Development Mode (Optional)

For rapid iteration without K8s, you can run the server and workers locally:

```bash
# Start server and worker locally
task noetl:local:start

# Check status
task noetl:local:status

# Stop server and worker
task noetl:local:stop

# Restart both
task noetl:local:restart

# Full reset: drops schema, recreates tables, reloads credentials and test playbooks
task noetl:local:reset
```

The local server runs on http://localhost:8083 by default.

### CLI Reference

```bash
# Server management (local mode)
noetl server start              # Start server
noetl server stop               # Stop server gracefully
noetl server stop --force       # Force stop

# Catalog operations
noetl register <playbook.yaml>  # Register playbook
noetl catalog list playbook     # List all playbooks
noetl catalog list credential   # List all credentials

# Execution
noetl execute playbook "<path>" # Execute by catalog path
```

For distributed execution patterns and worker pool management, see [Multiple Workers Guide](docs/multiple_workers.md).

## Workflow DSL Structure

NoETL uses a declarative YAML-based Domain Specific Language (DSL) for defining workflows. The key parts of a NoETL playbook include:

- **Metadata**: Version, path, and description of the playbook
- **Workload**: Input data and parameters for the workflow (Jinja2 templated)
- **Workflow**: A list of steps that make up the workflow, where each step is defined with `step: step_name`, including:
  - **Step**: Individual operations with unique names
  - **Tool**: Action types performed at each step (http, python, workbook, playbook, script, postgres, duckdb, snowflake, clickhouse)
  - **Next**: Conditional routing to subsequent steps with `when` clauses
  - **Args**: Parameters passed to the next step using templating (Jinja2)
- **Workbook** (optional): Reusable task definitions that can be called from workflow steps via `tool: workbook` and `name: task_name`

For examples of NoETL playbooks and detailed explanations, see the [Examples Guide](https://github.com/noetl/noetl/blob/master/docs/examples.md).

To execute a playbook:

```bash
noetl execute playbook "path/to/playbook" --host localhost --port 8082
```

## Credential Handling

NoETL provides a unified authentication system for handling credentials in workflows:

### Simple Credential Reference

For single credential authentication, use a direct string reference:

```yaml
- step: create_table
  desc: Create test table
  tool: postgres
  auth: "{{ workload.pg_auth }}"
  command: |
    CREATE TABLE IF NOT EXISTS users (
      id SERIAL PRIMARY KEY,
      name VARCHAR(255)
    )
```

### Structured Authentication

For more complex scenarios (multiple credentials, scoped access), use structured auth:

```yaml
- step: upload_to_gcs
  desc: Upload parquet file to GCS via DuckDB
  tool: duckdb
  auth:
    pg_db:
      source: credential
      tool: postgres
      key: "{{ workload.pg_auth }}"
    gcs_secret:
      source: credential
      tool: hmac
      key: gcs_hmac_local
      scope: gs://{{ workload.gcs_bucket }}
  commands: |
    INSTALL httpfs;
    LOAD httpfs;
    
    CREATE TABLE test_data AS
    SELECT 'test data' AS message;
    
    COPY test_data TO 'gs://{{ workload.gcs_bucket }}/data.parquet' (FORMAT PARQUET);
```

### OAuth Token Authentication

For OAuth-based APIs (Google Cloud, Interactive Brokers, etc.), use the `token()` function:

```yaml
- step: list_buckets
  desc: List GCS buckets using OAuth token
  tool: http
  method: GET
  url: "https://storage.googleapis.com/storage/v1/b?project={{ workload.project_id }}"
  headers:
    Authorization: "Bearer {{ token(workload.google_auth) }}"
    Content-Type: application/json
```

### Authentication Patterns

- **Simple string reference**: `auth: "{{ workload.pg_auth }}"` - resolves credential by name
- **Structured auth**: `auth: { pg_db: {...}, gcs_secret: {...} }` - multiple credentials with specific tools
- **OAuth tokens**: `{{ token(credential_name) }}` - generates OAuth access tokens at runtime
- **Source types**: 
  - `credential` - lookup from NoETL credential store
  - `env` - resolve from environment variables (future)

For detailed documentation, see [Credential Management Guide](docs/concepts/credentials.md).



## CP-SAT Scheduler (experimental)

NoETL includes an experimental OR-Tools CP-SAT planner to schedule playbooks with iterator expansion and resource capacities.

Install dependency:

pip install ortools

Plan a playbook (no execution, just schedule JSON):

noetl plan examples/test/http_duckdb_postgres.yaml --resources http_pool=4,pg_pool=5,duckdb_host=1 --max-solve-seconds 5 --json

The output includes per-step start/end times and respects capacities (e.g., http_pool concurrency, exclusive duckdb_host).

## Documentation

For more detailed information, please refer to the following documentation:

> **Note:**  
> When installed from PyPI, the `docs` folder is included in your local package.  
> You can find all documentation files in the `docs/` directory of your installed package.

### Getting Started
- [Installation Guide](https://github.com/noetl/noetl/blob/master/docs/installation.md) - Installation instructions
- [CLI Usage Guide](https://github.com/noetl/noetl/blob/master/docs/cli_usage.md) - Commandline interface usage
- [Multiple Workers Guide](https://github.com/noetl/noetl/blob/master/docs/multiple_workers.md) - Running multiple worker instances
- [API Usage Guide](https://github.com/noetl/noetl/blob/master/docs/api_usage.md) - REST API usage
- [Docker Usage Guide](https://github.com/noetl/noetl/blob/master/docs/docker_usage.md) - Docker deployment

### Core Concepts
- [Playbook Structure](https://github.com/noetl/noetl/blob/master/docs/playbook_structure.md) - Structure of NoETL playbooks
- [Workflow Tasks](https://github.com/noetl/noetl/blob/master/docs/action_type.md) - Action types and parameters
- [Environment Configuration](https://github.com/noetl/noetl/blob/master/docs/environment_variables.md) - Setting up environment variables
- [Credential Management](docs/concepts/credentials.md) - auth vs credentials vs secret

### Infrastructure & Operations
- [CI/CD Setup](documentation/docs/operations/ci-setup.md) - Kind cluster, PostgreSQL, NoETL deployment
- [Observability Services](documentation/docs/operations/observability.md) - ClickHouse, Qdrant, NATS JetStream


### Examples

NoETL includes test playbooks in `tests/fixtures/playbooks/` that demonstrate various capabilities:

- **OAuth Integration** (`oauth/`) - Google Cloud (GCS, Secret Manager), Interactive Brokers OAuth 2.0 with JWT
- **Database Operations** (`save_storage_test/`, `python_psycopg/`) - Postgres and DuckDB integration patterns
- **Cloud Storage** (`duckdb_gcs/`) - Google Cloud Storage operations with HMAC and Workload Identity
- **Retry Logic** (`retry_test/`) - HTTP, Postgres, DuckDB, and Python exception retry patterns
- **Playbook Composition** (`playbook_composition/`) - Multi-playbook workflows and task reuse
- **Data Transfer** (`data_transfer/`) - ETL patterns for moving data between systems
- **Hello World** (`hello_world/`) - Simple getting started examples

Each directory contains working playbooks with detailed comments. See [tests/fixtures/playbooks/README.md](tests/fixtures/playbooks/README.md) for complete fixture inventory and setup instructions.

~~For conceptual guides and API documentation, see the [Examples Guide](https://github.com/noetl/noetl/blob/master/docs/examples.md).~~

## Security & Redaction

- Ephemeral scope: step-scoped creds are injected only at runtime and not persisted into results.
- Redacted logs: secrets and DSNs are redacted in logs and events.


## Development

For information about contributing to NoETL or building from source:

- [Development Guide](https://github.com/noetl/noetl/blob/master/docs/development.md) - Setting up a development environment
- [PyPI Publishing Guide—](https://github.com/noetl/noetl/blob/master/docs/pypi_manual.md)Building and publishing to PyPI

## Community & Support

- **GitHub Issues**: [Report bugs or request features](https://github.com/noetl/noetl/issues)
- **Documentation**: [Full documentation](https://noetl.io/docs)
- **Website**: [https://noetl.io](https://noetl.io)

## License

NoETL is released under the MIT License. See the [LICENSE](LICENSE) file for details.

## Quick Start for Developers

### Environment Setup
```bash
# Bootstrap complete environment (installs tools + deploys infrastructure)
make bootstrap

# Or manually:
task tools:local:verify           # Verify required tools
task noetl:k8s:bootstrap          # Deploy complete K8s environment

# Observability services (automatically deployed with bootstrap)
task observability:activate-all   # Deploy ClickHouse, Qdrant, NATS
task observability:deactivate-all # Remove observability services
task observability:status-all     # Check all services status
task observability:health-all     # Health check all services
```

### UI Development
```bash
# Start NoETL backend
task noetl:k8s:deploy             # Deploy to K8s (recommended)
# OR
task noetl:local:start            # Run server+worker locally

# Start UI dev server (in separate terminal)
task noetl:local:ui-dev-start     # Auto-connects to backend

# Format UI code before commit
cd ui-src && npx prettier . --write
```

### Register Test Playbooks
```bash
# Register a playbook to the catalog
noetl register tests/fixtures/playbooks/hello_world/hello_world.yaml --host localhost --port 8082

# Execute a registered playbook
noetl execute playbook "tests/fixtures/playbooks/hello_world" --host localhost --port 8082
```

### Register Credentials and Playbooks for Kubernetes Environment

When running NoETL in Kind Kubernetes (after `make bootstrap` or `task bootstrap`), use these commands:

```bash
# Register test credentials for Kind environment
task test:k8s:register-credentials
# Aliases: task rtc, task register-test-credentials

# Register all test playbooks
task test:k8s:register-playbooks
# Aliases: task rtp, task register-test-playbooks

# Complete setup (register credentials + playbooks)
task test:k8s:setup-environment
# Alias: task ste, task setup-test-environment
```

**What gets registered:**
- **Credentials**: `pg_k8s` (Postgres in cluster), `pg_local`, `gcs_hmac_local`, `sf_test`
- **Playbooks**: All fixtures from `tests/fixtures/playbooks/`

**Verify registration:**
```bash
# List registered credentials
curl http://localhost:8082/api/credentials | jq

# List registered playbooks
curl http://localhost:8082/api/catalog/playbook | jq

# Or using CLI
noetl catalog list credential --host localhost --port 8082
noetl catalog list playbook --host localhost --port 8082
```

### Cleanup
```bash
# Destroy environment and clean all resources
make destroy

# Or selective cleanup:
task kind:local:cluster-delete    # Delete K8s cluster
task docker:local:cleanup-all     # Clean Docker resources
task noetl:local:clear-all        # Clear NoETL cache
```

## Documentation

### Build Documentation Site
The documentation uses [Docusaurus](https://docusaurus.io/docs/versioning):

```bash
cd documentation
npm install
npm run start                     # Local dev server
npm run build                     # Production build
```


