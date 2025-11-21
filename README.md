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
# 5. Deploys monitoring stack (VictoriaMetrics, Grafana, VictoriaLogs)
# 6. Deploys NoETL server and workers

# After bootstrap, you can use task commands directly:
task --list                  # Show all available tasks
task noetl:k8s:deploy        # Deploy NoETL components
task postgres:k8s:deploy     # Deploy PostgreSQL
task monitoring:k8s:deploy   # Deploy monitoring stack
```

**Services available after bootstrap:**
- **NoETL Server**: http://localhost:8082 (API & UI)
- **Postgres**: localhost:54321 (user: demo, password: demo, database: noetl)
- **Grafana Dashboard**: http://localhost:3000 (admin credentials via `task grafana`)
- **VictoriaMetrics**: http://localhost:9428/ 
- **VictoriaLogs**: http://localhost:9428/select/vmui/

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

# Check cluster health
task test-cluster-health
```

All `make` commands execute Taskfile automation under the hood. Use `task --list` to see all available tasks.

### Using NoETL as a Submodule

If you're integrating NoETL into another project as a Git submodule and want to use its full development infrastructure (Kind cluster, PostgreSQL, monitoring, task automation), use the automated bootstrap system:

```bash
# Initialize NoETL submodule (if already added to your project)
git submodule update --init --recursive

# Run bootstrap to install all tools and provision environment
# This executes .noetl/ci/bootstrap/bootstrap.sh under the hood
make -C .noetl bootstrap
```

The bootstrap automatically:
- Installs all required tools (Docker, kubectl, helm, kind, **task**, psql, pyenv, tfenv, uv, Python 3.12+)
- Sets up Python virtual environment with your project + NoETL dependencies
- Creates project Taskfile.yml that imports all NoETL tasks
- Deploys Kind cluster with PostgreSQL and monitoring stack
- Copies template files (.env.local, pyproject.toml, .gitignore, credentials/)
- Creates project directories (credentials/, playbooks/, data/, logs/, secrets/)

**Important:** The bootstrap installs `task` (Taskfile automation tool), so run it before using any `task` commands.

After bootstrap completes, all NoETL infrastructure tasks are available with `noetl:` prefix:

```bash
# Use NoETL tasks from your project root
task noetl:postgres:k8s:deploy      # Deploy PostgreSQL
task noetl:noetl:k8s:deploy         # Deploy NoETL server and workers
task noetl:test:k8s:cluster-health  # Check cluster health

# Your project-specific tasks (defined in Taskfile.yml)
task dev:run                         # Run your application
task credentials:register            # Register your credentials
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

After installing NoETL:

### 1. Run the NoETL Server

Start the NoETL server to access the web UI and REST API:

```bash
# Start the server with default settings
noetl server

#  use the explicit start command with options
noetl server start --host 0.0.0.0 --port 8080 --workers 4 --debug

# Stop the server
noetl server stop

# Force stop without confirmation
noetl server stop --force
```

The server starts on http://localhost:8080 by default. You can customize the host, port, number of workers, and enable debug mode using command options.

### 2. Running Workers (Optional)

For distributed execution, you can run worker processes that execute playbooks:

```bash
# Start a worker
make worker-start

# Start multiple workers with different configurations
NOETL_WORKER_POOL_NAME=worker-cpu-01 NOETL_WORKER_POOL_RUNTIME=cpu make worker-start
NOETL_WORKER_POOL_NAME=worker-gpu-01 NOETL_WORKER_POOL_RUNTIME=gpu make worker-start

# Quick start multiple workers using provided scripts
./bin/start_multiple_workers.sh

# Stop workers
./bin/stop_multiple_workers.sh
```

See [Multiple Workers Guide](docs/multiple_workers.md) for detailed instructions on running and managing multiple worker instances.

NoETL provides a command-line interface for managing and executing playbooks:

- Register a playbook in the catalog
```bash
noetl register ./path/to/playbook.yaml
```

- List playbooks in the catalog
```bash
noetl catalog list playbook
```

- Execute a registered playbook
```bash
noetl execute my_playbook --version 1.0.0
```

- Register and execute with the catalog command
```bash
noetl catalog register ./path/to/playbook.yaml
noetl catalog execute my_playbook --version 1.0.0
```

## Workflow DSL Structure

NoETL uses a declarative YAML-based Domain Specific Language (DSL) for defining workflows. The key components of a NoETL playbook include:

- **Metadata**: Version, path, and description of the playbook
- **Workload**: Input data and parameters for the workflow (Jinja2 templated)
- **Workflow**: A list of steps that make up the workflow, where each step is defined with `step: step_name`, including:
  - **Step**: Individual operations with unique names
  - **Tool**: Action types performed at each step (http, postgres, duckdb, python)
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

## For UI developers

- `uv pip install --editable .`
- `task kind:local:cluster-delete`
- `task docker:local:cleanup-all`
- `task cache:local:clear-all`
- `task dev:k8s:bootstrap`
- `task test:k8s:setup-environment`
- `task noetl:local:ui-dev-start`
- `cd ui-src`
- before commit in ui use `npx prettier  . --write`

## Noetl register
- `uv pip install --editable .`
- `noetl register tests/fixtures/playbooks/hello_world/hello_world.yaml --host localhost --port 8084`

## DOcumentation UI from md

https://docusaurus.io/docs/versioning

`cd documentation`

`npm run start`


