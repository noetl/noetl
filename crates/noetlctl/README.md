# NoETL CLI

[![Crates.io](https://img.shields.io/crates/v/noetl.svg)](https://crates.io/crates/noetl)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

NoETL workflow automation CLI - Execute playbooks locally or orchestrate distributed server-worker pipelines.

## Installation

### Via Cargo

```bash
cargo install noetl
```

### Via Homebrew (macOS)

```bash
brew tap noetl/tap
brew install noetl
```

### Via APT (Ubuntu/Debian)

```bash
echo 'deb [trusted=yes] https://noetl.github.io/apt jammy main' | sudo tee /etc/apt/sources.list.d/noetl.list
sudo apt-get update
sudo apt-get install noetl
```

## Quick Start

Create a simple playbook:

```yaml
# hello.yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: hello_world

workflow:
  - step: start
    tool:
      kind: shell
      cmds:
        - "echo 'Hello from NoETL!'"
    next:
      - step: end
  - step: end
```

Run it:

```bash
noetl run hello.yaml
```

## Features

- **Local Playbook Execution** - Run workflows without server infrastructure
- **HTTP Actions** - Make REST API calls with automatic pagination
- **Conditional Flow** - Dynamic routing with case/when/then/else
- **Playbook Composition** - Call sub-playbooks for modularity
- **Server/Worker Management** - Start/stop distributed services
- **Kubernetes Operations** - Deploy to K8s clusters
- **Database Management** - Initialize and validate schemas

## Usage

Check version:
```bash
noetl --version
```

### Local Execution

```bash
# Run playbook locally
noetl run playbook.yaml

# Pass variables
noetl run playbook.yaml --set env=prod --set version=v2.5.5

# Verbose output
noetl run playbook.yaml --verbose
```

### Server Management

Start NoETL server:
```bash
noetl server start
noetl server start --init-db  # Initialize database on startup
```

Stop NoETL server:
```bash
noetl server stop
noetl server stop --force  # Force stop without confirmation
```

### Worker Management

Start NoETL worker:
```bash
noetl worker start
noetl worker start --max-workers 4
```

Stop NoETL worker:
```bash
noetl worker stop  # Interactive selection if multiple workers
noetl worker stop --name my-worker
noetl worker stop --name my-worker --force
```

### Database Management

Initialize database schema:
```bash
noetl db init
```

Validate database schema:
```bash
noetl db validate
```

### Build Management

Build NoETL Docker image:
```bash
noetl build
noetl build --no-cache  # Build without using cache
```

The build command:
- Builds the Docker image with a timestamp-based tag
- Saves the tag to `.noetl_last_build_tag.txt` for deployment use
- Streams build output to console
- Replaces `task docker-build-noetl`

### Kubernetes Management

Deploy NoETL to kind cluster:
```bash
noetl k8s deploy
```

Remove NoETL from cluster:
```bash
noetl k8s remove
```

Rebuild and redeploy:
```bash
noetl k8s redeploy
noetl k8s redeploy --no-cache  # Rebuild without cache
```

Full reset (schema reset + redeploy + test setup):
```bash
noetl k8s reset
noetl k8s reset --no-cache  # Reset with clean build
```

The k8s commands:
- `deploy`: Applies Kubernetes manifests to kind cluster
- `remove`: Deletes NoETL resources from cluster
- `redeploy`: Builds image, loads to kind, and deploys (replaces `task noetl:k8s:redeploy`)
- `reset`: Full workflow - resets database schema, redeploys, runs test setup (replaces `task noetl:k8s:reset`)

### Configuration and Contexts

`noetl` supports multiple contexts to manage different server environments.

#### Add a Context
```bash
noetl context add local --server-url http://localhost:8082 --set-current
noetl context add prod --server-url http://noetl-server:8082
```

#### List Contexts
```bash
noetl context list
```

#### Switch Context
```bash
noetl context use prod
```

#### Show Current Context
```bash
noetl context current
```

### CLI Mode

#### Catalog Management

Register a resource (auto-detects kind: Credential or Playbook):
```bash
noetl catalog register tests/fixtures/playbooks/data_transfer/http_to_postgres_transfer/http_to_postgres_transfer.yaml
```

Get resource details:
```bash
noetl catalog get tests/fixtures/playbooks/data_transfer/http_iterator_save_postgres
```

List resources:
```bash
noetl catalog list Playbook --json
```

#### Execution

Execute a playbook:
```bash
noetl execute playbook tests/fixtures/playbooks/regression_test/master_regression_test --json
```

Get execution status:
```bash
noetl execute status 522107710393811426 --json
```

#### Credentials

Get credential details:
```bash
noetl get credential gcs_service_account --include-data
```

#### SQL Query Execution

Execute SQL queries via NoETL Postgres API:

```bash
# Query with table format (default)
noetl query "SELECT * FROM noetl.keychain LIMIT 5"

# Query with specific schema
noetl query "SELECT execution_id, credential_name FROM noetl.keychain WHERE execution_id = 12345" --schema noetl

# Query with JSON output
noetl query "SELECT * FROM noetl.event ORDER BY created_at DESC LIMIT 10" --format json

# Query public schema tables
noetl query "SELECT * FROM users LIMIT 5" --schema public --format table
```

**Output Formats:**
- `table` (default): Formatted ASCII table with borders
- `json`: Pretty-printed JSON output

**Example Output (table format):**
```
┌────────────────────┬────────────────┬──────────────┐
│ execution_id       │ credential_name│ access_count │
├────────────────────┼────────────────┼──────────────┤
│ 507861119290048685 │ openai-api-key │ 0            │
│ 507861119290048686 │ postgres-creds │ 2            │
└────────────────────┴────────────────┴──────────────┘
(2 rows)
```

#### Registering (Legacy/Explicit)

Register a Credential:
```bash
noetl register credential -f tests/fixtures/credentials/pg_k8s.json
```

Register a Playbook:
```bash
noetl register playbook -f tests/fixtures/playbooks/api_integration/auth0/provision_auth_schema.yaml
```

#### Direct Execution/Status/List

Execute a Playbook:
```bash
noetl run playbook api_integration/auth0/provision_auth_schema
```

Get Execution Status:
```bash
noetl status <execution_id>
```

List Resources:
```bash
noetl list Playbook
```

### Interactive TUI Mode

Run `noetl` with the `-i` or `--interactive` flag:

```bash
noetl --interactive
```

- **Navigation**: Use Up/Down arrows or `j`/`k` to navigate lists.
- **Refresh**: Press `r` to refresh the data.
- **Quit**: Press `q` to exit.

## Docker Integration

The `noetl` binary is built into the Docker image using a multi-stage build:

```dockerfile
# Rust builder stage compiles the CLI
FROM rust:1.75-slim as rust-builder
WORKDIR /build
COPY noetlctl/ ./
RUN cargo build --release

# Production stage includes the binary
COPY --from=rust-builder /build/target/release/noetl /usr/local/bin/noetl
```

The Kubernetes manifests use the Rust CLI for server and worker management:

**Server deployment:**
```yaml
command: ["noetl"]
args: ["server", "start"]
```

**Worker deployment:**
```yaml
command: ["noetl"]
args: ["worker", "start"]
```

This provides a unified binary for both local development and containerized deployments.

## Command Mapping

The Rust CLI replaces several task commands:

| Task Command | noetl Command |
|-------------|---------------|
| `task docker-build-noetl` | `noetl build` |
| `task noetl:k8s:deploy` | `noetl k8s deploy` |
| `task noetl:k8s:redeploy` | `noetl k8s redeploy` |
| `task noetl:k8s:reset` | `noetl k8s reset` |
| `task noetl:server:start` | `noetl server start` |
| `task noetl:worker:start` | `noetl worker start` |
