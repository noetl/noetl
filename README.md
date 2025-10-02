# Not Only ETL

__NoETL__ is an automation framework for data processing and MLOps orchestration.

[![PyPI version](https://badge.fury.io/py/noetl.svg)](https://badge.fury.io/py/noetl)


## System Architecture

The following diagram illustrates the main components and intent of the NoETL system:

![NoETL System Diagram](docs/images/NoETL.png)

- Worker (worker.py): background worker pool, no HTTP endpoints
- Server (server.py): orchestration + API endpoints (credential lookup, catalog, events)
- CLI (clictl.py): manages worker pools and server lifecycle

## Quick Start

### Installation

- Install NoETL from PyPI:
  ```bash
  pip install noetl
  ```

For development or specific versions:
- Install in a virtual environment
  ```bash
  python -m venv .venv
  source .venv/bin/activate
  pip install noetl
  ```
- For Windows users (in PowerShell)
  ```bash
  python -m venv .venv
  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
  .venv\Scripts\Activate.ps1
  pip install noetl
  ```
- Install a specific version
  ```bash
  pip install noetl==1.0.0
  ```

### Prerequisites

- Python 3.11+
- For full functionality:
  - Postgres database (mandatory, for the event-sourcing persistent storage and NoETL system metadata)
  - Docker (optional, for containerized development and deployment)

### Kubernetes Development Environment (Recommended)

For a complete development environment with server, workers, and observability:

```bash
# Clone repository
git clone https://github.com/noetl/noetl.git
cd noetl

# Deploy unified platform (requires Docker, Kind, kubectl, Helm)
make unified-deploy

# Or complete recreation from scratch
make unified-recreate-all

# Check health status
make unified-health-check

# Manage port forwarding
make unified-port-forward-start
make unified-port-forward-status
make unified-port-forward-stop
```

**Services available:**
- **NoETL Server**: http://localhost:30082 (API & UI)
- **Grafana Dashboard**: http://localhost:3000 (admin/admin)
- **VictoriaMetrics**: http://localhost:8428/vmui/
- **VictoriaLogs**: http://localhost:9428

**Management Commands:**
```bash
# Get Grafana credentials
make unified-grafana-credentials

# View all available commands
make help

# Clean up when done
kind delete cluster --name noetl-cluster
```

See [k8s/README.md](k8s/README.md) for detailed deployment documentation.

## Quick Reference

### Unified Kubernetes Platform
```bash
make unified-deploy          # Deploy complete platform
make unified-health-check    # Check platform health
make unified-recreate-all    # Rebuild everything from scratch
```

### Makefile Commands
```bash
make help                    # Show all available commands
make unified-*              # Unified deployment commands
make test                   # Run test suite
make install-dev            # Development setup
```

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

### 3. Docker Deployment

For containerized deployment:

```bash
# Pull the latest image
docker pull noetl/noetl:latest

# Start the server
docker run -p 8080:8080 noetl/noetl:latest

# with environment variables
docker run -p 8080:8080 -e NOETL_RUN_MODE=server noetl/noetl:latest

# Stop the server
docker run -e NOETL_RUN_MODE=server-stop -e NOETL_FORCE_STOP=true noetl/noetl:latest
```

### 4. Kubernetes Deployment

For Kubernetes deployment using Kind (Kubernetes in Docker):

```bash
# Follow the instructions in k8s/README.md
# Or use the automated deployment script
./k8s/deploy-kind.sh

# To stop the server in Kubernetes, create a job:
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: noetl-server-stop
spec:
  template:
    spec:
      containers:
      - name: noetl-stop
        image: noetl:latest
        env:
        - name: NOETL_RUN_MODE
          value: "server-stop"
        - name: NOETL_FORCE_STOP
          value: "true"
      restartPolicy: Never
  backoffLimit: 1
EOF
```

See [Kubernetes Deployment Guide](k8s/KIND-README.md) for detailed instructions.

## Credential Handling

NoETL provides three distinct approaches for handling credentials and secrets in workflows:

- **`auth:`** single credential reference resolved by the Server at runtime
- **`credentials:`** multiple credential bindings with developer-chosen aliases (for steps needing several creds at once)  
- **`secret:`** resolve values from an external secret manager at render/exec time (used inside templates like `{{ secret.NAME }}`)

### Quick Examples

**Single Credential (Postgres):**
```yaml
- step: create_table
  type: postgres
  auth:
    pg:
      type: postgres
      key: pg_local
  command: CREATE TABLE users (id SERIAL, name TEXT);
```

**Multiple Credentials (DuckDB):**
```yaml
- step: aggregate_data
  type: duckdb
  credentials:
    pg_db:      { key: pg_local }
    gcs_secret: { key: gcs_hmac_local }
  commands: |
    ATTACH '{{ credentials.pg_db.connstr }}' AS pg_db (TYPE postgres);
    CREATE SECRET gcs_secret (
      TYPE gcs,
      KEY_ID '{{ credentials.gcs_secret.key_id }}',
      SECRET '{{ credentials.gcs_secret.secret_key }}'
    );
```

**External Secrets (HTTP):**
```yaml
- step: api_call
  type: http
  method: GET
  endpoint: "https://api.example.com/data"
  headers:
    Authorization: "Bearer {{ secret.api_service_token }}"
```

### Why This Works
- **No ambiguity**: each keyword has a distinct role
- **Separation of concerns**:
  - `auth` → lookup credential record (single)
  - `credentials` → bind multiple credentials via aliases
  - `secret` → resolve external secret value at runtime
- **Native SQL**: DuckDB aliases and secret names are unchanged and under your control

For detailed documentation, see [Credential Management Guide](docs/concepts/credentials.md).

### Unified Authentication System (v1.0+)

NoETL v1.0+ introduces a unified authentication system that consolidates authentication patterns under a single `auth` attribute:

```yaml
# New unified syntax
- step: postgres_task
  type: postgres
  auth:
    type: postgres
    credential: pg_local
  
- step: http_task
  type: http
  auth:
    type: bearer
    env: API_TOKEN
    
- step: duckdb_task
  type: duckdb
  auth:
    db: {type: postgres, credential: pg_main}
    storage: {type: gcs, credential: gcs_hmac}
```

**Key Features:**
- Single `auth` syntax across all plugins
- Multiple sources: credential store, environment variables, secret managers, inline
- Plugin-specific validation (single vs multi-auth)
- Automatic security redaction in logs
- Full backwards compatibility with deprecation warnings

For complete migration guide, see [Unified Auth Migration Guide](docs/migration/auth-unified.md).

## Workflow DSL Structure

NoETL uses a declarative YAML-based Domain Specific Language (DSL) for defining workflows. The key components of a NoETL playbook include:

- **Metadata**: Version, path, and description of the playbook
- **Workload**: Input data and parameters for the workflow
- **Workflow**: A list of steps that make up the workflow, where each step is defined with `step: step_name`, including:
  - **Steps**: Individual operations in the workflow
  - **Tasks**: Actions performed at each step (HTTP requests, database operations, Python code)
  - **Transitions**: Rules for moving between steps
  - **Conditions**: Logic for branching the workflow
- **Workbook**: Reusable task definitions that can be called from workflow steps, including:
  - **Task Types**: Python, HTTP, DuckDB, PostgreSQL, Secret.
  - **Parameters**: Input parameters for the tasks
  - **Code**: Implementation of the tasks

For examples of NoETL playbooks and detailed explanations, see the [Examples Guide](https://github.com/noetl/noetl/blob/master/docs/examples.md).

To run a playbook:

```bash
noetl agent -f path/to/playbooks.yaml
```

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

NoETL includes several example playbooks that demonstrate some capabilities:

- **Weather API Integration** - Fetches and processes weather data from external APIs
- **Database Operations** - Demonstrates Postgres and DuckDB integration
- **Google Cloud Storage** - A secure cloud storage operations with Google Cloud
- **Secrets Management** - Illustrates secure handling of credentials and sensitive data
- **Multi-Playbook Workflows** - Complex workflow orchestration

For detailed examples, see the [Examples Guide](https://github.com/noetl/noetl/blob/master/docs/examples.md).

### After-refactor example (end-to-end)

```yaml
- step: ensure_pg_table
  type: postgres
  auth:
    pg:
      type: postgres
      key: pg_local
  command: |
    CREATE TABLE IF NOT EXISTS public.weather_http_raw (
      id TEXT PRIMARY KEY,
      execution_id TEXT,
      iter_index INTEGER,
      city TEXT,
      url TEXT,
      elapsed DOUBLE PRECISION,
      payload TEXT,
      created_at TIMESTAMPTZ DEFAULT now()
    );

- step: aggregate_with_duckdb
  type: duckdb
  credentials:
    pg_db:      { key: pg_local }
    gcs_secret: { key: gcs_hmac_local }
  commands: |
    INSTALL postgres; LOAD postgres;
    INSTALL httpfs;  LOAD httpfs;

    ATTACH '{{ credentials.pg_db.connstr }}' AS pg_db (TYPE postgres);

    CREATE OR REPLACE SECRET gcs_secret (
      TYPE gcs,
      KEY_ID  '{{ credentials.gcs_secret.key_id }}',
      SECRET  '{{ credentials.gcs_secret.secret_key }}',
      SCOPE   'gs://{{ workload.gcs_bucket }}'
    );

    CREATE OR REPLACE TABLE weather_flat AS
    SELECT id, city, url, elapsed, payload
    FROM   pg_db.public.weather_http_raw
    WHERE  execution_id = '{{ execution_id }}';

    COPY weather_flat TO 'gs://{{ workload.gcs_bucket }}/weather/flat_{{ execution_id }}.parquet' (FORMAT PARQUET);

- step: call_api
  type: http
  method: GET
  endpoint: "https://api.example.com/data"
  headers:
    Authorization: "Bearer {{ secret.api_service_token }}"
```

## Security & Redaction

- Ephemeral scope: step-scoped creds are injected only at runtime and not persisted into results.
- Redacted logs: secrets and DSNs are redacted in logs and events.


## Development

For information about contributing to NoETL or building from source:

- [Development Guide](https://github.com/noetl/noetl/blob/master/docs/development.md) - Setting up a development environment
- [PyPI Publishing Guide](https://github.com/noetl/noetl/blob/master/docs/pypi_manual.md) - Building and publishing to PyPI

## Community & Support

- **GitHub Issues**: [Report bugs or request features](https://github.com/noetl/noetl/issues)
- **Documentation**: [Full documentation](https://noetl.io/docs)
- **Website**: [https://noetl.io](https://noetl.io)

## License

NoETL is released under the MIT License. See the [LICENSE](LICENSE) file for details.

## For UI developers

- `make install-dev`
- `docker compose up database -d`
- `./start_server.sh`
- `make register-examples`
- check __API_BASE_URL__ in vite.config.js for actual noetl base url
- `cd ui-src`
- `npm run dev`
- before commit in ui use `npx prettier  . --write`
