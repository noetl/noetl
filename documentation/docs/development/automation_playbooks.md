---
sidebar_position: 15
---

# Automation Playbooks

NoETL provides playbook-based automation for development workflows, replacing traditional Makefile and Taskfile commands with declarative YAML playbooks. This allows you to manage infrastructure as code using NoETL's own DSL.

## Overview

Automation playbooks are located in the `automation/` directory and provide self-service workflows for:
- Environment setup and teardown (bootstrap/destroy)
- Docker image building and deployment
- Test infrastructure management
- Infrastructure as Playbook (IaP) for cloud resources

## Runtime Modes

All automation playbooks use **local runtime** by default, executing directly via the Rust interpreter without requiring a NoETL server. Playbooks include the `executor` section:

```yaml
executor:
  profile: local           # Use local Rust interpreter
  version: noetl-runtime/1 # Runtime version
```

### Runtime Selection

```bash
# Auto-detect (file paths default to local)
noetl run automation/setup/bootstrap.yaml

# Explicit local runtime
noetl run automation/setup/bootstrap.yaml -r local

# Verbose output
noetl run automation/setup/bootstrap.yaml -v
```

## Main Entry Point

The `automation/main.yaml` playbook serves as the central router:

```bash
# Show available targets
noetl run automation/main.yaml --set target=help

# Bootstrap complete environment
noetl run automation/main.yaml --set target=bootstrap

# Destroy environment
noetl run automation/main.yaml --set target=destroy
```

Or use JSON payload:

```bash
noetl run automation/main.yaml --payload '{"target":"bootstrap"}'
```

## Quick Commands

For convenience, shortcut playbooks are available:

```bash
# Bootstrap (equivalent to main.yaml --set target=bootstrap)
noetl run boot

# Destroy (equivalent to main.yaml --set target=destroy)
noetl run destroy
```

## Bootstrap Workflow

Complete K8s environment setup including:
- Prerequisite validation (noetl, docker, kind, kubectl, task, python3, uv)
- Docker image building (Python server/worker image)
- Kind cluster creation
- Image loading to cluster
- PostgreSQL deployment
- NoETL server and worker deployment
- Observability stack (ClickHouse, Qdrant, NATS)
- Health checks and validation

### Usage

```bash
# Via main entry point
noetl run automation/main.yaml --set target=bootstrap

# Direct execution
noetl run automation/setup/bootstrap.yaml

# With verbose output
noetl run automation/setup/bootstrap.yaml -v

# Skip Gateway deployment
noetl run automation/setup/bootstrap.yaml --set deploy_gateway=false

# Build Rust CLI when needed
noetl run automation/setup/bootstrap.yaml --set build_rust_cli=true
```

### Steps

1. **validate_prerequisites** - Check required tools
2. **check_docker_running** - Verify Docker daemon
3. **check_existing_cluster** - Check for existing cluster
4. **build_rust_cli** - Build noetlctl binary (optional)
5. **build_docker_images** - Build NoETL Python container
6. **create_kind_cluster** - Create K8s cluster
7. **load_image_to_kind** - Load image to cluster
8. **deploy_postgres** - Deploy PostgreSQL
9. **deploy_gateway** - Deploy Gateway API (optional)
10. **deploy_noetl** - Deploy NoETL server/workers
11. **deploy_observability** - Deploy ClickHouse, Qdrant, NATS
11. **wait_for_services** - Wait for pods to be ready
12. **test_cluster_health** - Verify endpoints
13. **summary** - Show completion status

### Observability Stack

NATS is **mandatory** for NoETL operation. Bootstrap deploys:
- **NATS JetStream** (required) - Event streaming and KV store
- **ClickHouse** (optional) - Logs, metrics, traces storage
- **Qdrant** (optional) - Vector database for embeddings

### Equivalent Commands

| Playbook | Task Command |
|----------|-------------|
| `noetl run automation/main.yaml --set target=bootstrap` | `task bring-all` |
| `noetl run automation/setup/destroy.yaml` | `make destroy` |

## Destroy Workflow

Clean up all resources:

```bash
# Via main entry point
noetl run automation/main.yaml --set target=destroy

# Direct execution
noetl run automation/setup/destroy.yaml
```

### Steps

1. **delete_cluster** - Delete kind cluster
2. **cleanup_docker** - Prune Docker resources
3. **clear_cache** - Clear cache directories
4. **clear_noetl_data** - Remove data directories

## Pagination Test Server

Manage the pagination test server for HTTP pagination testing:

```bash
# Show available actions
noetl run automation/test/pagination-server.yaml --set action=help

# Full workflow (build + load + deploy + test)
noetl run automation/test/pagination-server.yaml --set action=full

# Individual actions
noetl run automation/test/pagination-server.yaml --set action=build
noetl run automation/test/pagination-server.yaml --set action=load
noetl run automation/test/pagination-server.yaml --set action=deploy
noetl run automation/test/pagination-server.yaml --set action=status
noetl run automation/test/pagination-server.yaml --set action=test
noetl run automation/test/pagination-server.yaml --set action=logs
noetl run automation/test/pagination-server.yaml --set action=undeploy
```

### Actions

| Action | Description | Task Equivalent |
|--------|-------------|----------------|
| `build` | Build Docker image | `task pagination-server:tpsb` |
| `load` | Load image to kind | `task pagination-server:tpsl` |
| `deploy` | Deploy to K8s | `task pagination-server:tpsd` |
| `full` | Complete workflow | `task pagination-server:tpsf` |
| `status` | Check pod status | `task pagination-server:tpss` |
| `test` | Test endpoints | `task pagination-server:tpst` |
| `logs` | Show server logs | `task pagination-server:tpslog` |
| `undeploy` | Remove from K8s | `task pagination-server:tpsu` |

### Test Endpoints

The pagination server provides:
- **Health**: `http://localhost:30555/health`
- **Page-based**: `http://localhost:30555/api/v1/assessments`
- **Offset-based**: `http://localhost:30555/api/v1/users`
- **Cursor-based**: `http://localhost:30555/api/v1/events`
- **Retry testing**: `http://localhost:30555/api/v1/flaky`

## Output Visibility

All playbook output is visible by default. Use `--verbose` for extra debug information:

```bash
# Normal output (step names, command results)
noetl run automation/main.yaml --set target=bootstrap

# Verbose output (+ command details, condition matching)
noetl run automation/main.yaml --set target=bootstrap --verbose
```

## Variable Passing

### Using --set

```bash
noetl run automation/main.yaml --set target=bootstrap
noetl run automation/test/pagination-server.yaml --set action=full
```

### Using --payload (JSON)

```bash
noetl run automation/main.yaml --payload '{"target":"bootstrap"}'
noetl run automation/test/pagination-server.yaml --payload '{"action":"deploy"}'
```

### Variable Priority

When multiple sources provide variables:
1. `--set` flags (highest priority)
2. `--payload` JSON object
3. Playbook `workload` section (default values)

## Infrastructure Component Management

### PostgreSQL

Manage PostgreSQL deployment and operations:

```bash
# Deploy PostgreSQL to kind cluster
noetl run automation/infrastructure/postgres.yaml --set action=deploy

# Check deployment status
noetl run automation/infrastructure/postgres.yaml --set action=status

# Reset NoETL system schema
noetl run automation/infrastructure/postgres.yaml --set action=schema-reset

# View PostgreSQL logs
noetl run automation/infrastructure/postgres.yaml --set action=logs

# Remove PostgreSQL
noetl run automation/infrastructure/postgres.yaml --set action=remove

# Clear cache directory
noetl run automation/infrastructure/postgres.yaml --set action=clear-cache
```

**Available Actions:**
- `deploy` - Deploy PostgreSQL to kind cluster
- `remove` - Remove PostgreSQL from kind cluster
- `schema-reset` - Reset NoETL system schema
- `clear-cache` - Clear postgres data cache directory
- `status` - Check deployment status
- `logs` - Show PostgreSQL logs

### Qdrant Vector Database

Manage Qdrant vector database for embeddings and semantic search:

```bash
# Deploy Qdrant
noetl run automation/infrastructure/qdrant.yaml --set action=deploy

# Check deployment status
noetl run automation/infrastructure/qdrant.yaml --set action=status

# Check health
noetl run automation/infrastructure/qdrant.yaml --set action=health

# Test with sample collection
noetl run automation/infrastructure/qdrant.yaml --set action=test

# List all collections
noetl run automation/infrastructure/qdrant.yaml --set action=collections

# View logs
noetl run automation/infrastructure/qdrant.yaml --set action=logs

# Restart Qdrant
noetl run automation/infrastructure/qdrant.yaml --set action=restart

# Remove Qdrant
noetl run automation/infrastructure/qdrant.yaml --set action=undeploy
```

**Available Actions:**
- `deploy` - Deploy Qdrant vector database
- `undeploy` - Remove Qdrant from cluster
- `status` - Check deployment status
- `logs` - Show Qdrant logs
- `health` - Check Qdrant health
- `test` - Test with sample collection
- `collections` - List Qdrant collections
- `restart` - Restart Qdrant

**Qdrant Endpoints:**
- HTTP: `http://localhost:30633`
- gRPC: `localhost:30634`
- ClusterIP: `http://qdrant.qdrant.svc.cluster.local:6333`

### VictoriaMetrics Monitoring Stack

Manage VictoriaMetrics monitoring infrastructure including Grafana, metrics collection, and logging:

```bash
# Deploy complete monitoring stack
noetl run automation/infrastructure/monitoring.yaml --set action=deploy

# Check deployment status
noetl run automation/infrastructure/monitoring.yaml --set action=status

# Get Grafana admin credentials
noetl run automation/infrastructure/monitoring.yaml --set action=grafana-creds

# Deploy Grafana dashboards
noetl run automation/infrastructure/monitoring.yaml --set action=deploy-dashboards

# Deploy postgres exporter
noetl run automation/infrastructure/monitoring.yaml --set action=deploy-exporter

# Deploy NoETL metrics scraper
noetl run automation/infrastructure/monitoring.yaml --set action=deploy-noetl-scrape

# Deploy Vector log collector
noetl run automation/infrastructure/monitoring.yaml --set action=deploy-vector

# Deploy VictoriaLogs
noetl run automation/infrastructure/monitoring.yaml --set action=deploy-vmlogs

# Remove component
noetl run automation/infrastructure/monitoring.yaml --set action=remove-dashboards
noetl run automation/infrastructure/monitoring.yaml --set action=remove-vector

# Remove complete stack
noetl run automation/infrastructure/monitoring.yaml --set action=undeploy
```

**Main Actions:**
- `deploy` - Deploy complete monitoring stack (Metrics Server, VM Operator, VM Stack)
- `undeploy` - Remove monitoring stack
- `status` - Check deployment status
- `grafana-creds` - Get Grafana admin credentials

**Component Actions:**
- `deploy-dashboards` / `remove-dashboards` - Manage NoETL and Postgres Grafana dashboards
- `deploy-exporter` / `remove-exporter` - Manage postgres-exporter and VMScrape
- `deploy-noetl-scrape` / `remove-noetl-scrape` - Manage VMServiceScrape for NoETL
- `deploy-vector` / `remove-vector` - Manage Vector log collector
- `deploy-vmlogs` / `remove-vmlogs` - Manage VictoriaLogs

**Monitoring Stack Components:**
- **Grafana** - Metrics visualization and dashboards
- **VictoriaMetrics** - Time-series metrics storage
- **VMAgent** - Metrics collection agent
- **VMAlert** - Alerting system
- **Vector** - Log collector and processor
- **VictoriaLogs** - Log storage and querying
- **Postgres Exporter** - PostgreSQL metrics exporter

### ClickHouse Observability Stack

Manage ClickHouse for logs, metrics, and traces storage:

```bash
# Deploy complete ClickHouse stack
noetl run automation/infrastructure/clickhouse.yaml --set action=deploy

# Check status
noetl run automation/infrastructure/clickhouse.yaml --set action=status

# Check cluster health
noetl run automation/infrastructure/clickhouse.yaml --set action=health

# Connect to ClickHouse CLI
noetl run automation/infrastructure/clickhouse.yaml --set action=connect

# View logs
noetl run automation/infrastructure/clickhouse.yaml --set action=logs

# Deploy individual components
noetl run automation/infrastructure/clickhouse.yaml --set action=deploy-namespace
noetl run automation/infrastructure/clickhouse.yaml --set action=deploy-crds
noetl run automation/infrastructure/clickhouse.yaml --set action=deploy-operator
noetl run automation/infrastructure/clickhouse.yaml --set action=deploy-cluster
noetl run automation/infrastructure/clickhouse.yaml --set action=deploy-schema

# Remove stack
noetl run automation/infrastructure/clickhouse.yaml --set action=undeploy
```

**Main Actions:**
- `deploy` - Deploy complete ClickHouse observability stack
- `undeploy` - Remove ClickHouse stack
- `status` - Show stack status
- `health` - Check cluster health
- `test` - Test connection and schema

**Granular Deployment:**
- `deploy-namespace` - Create ClickHouse namespace
- `deploy-crds` - Deploy ClickHouse CRDs
- `deploy-operator` - Deploy ClickHouse operator
- `deploy-cluster` - Deploy ClickHouse cluster
- `deploy-schema` - Deploy observability schema
- `deploy-grafana-datasource` - Deploy Grafana datasource
- `deploy-mcp-server` - Deploy MCP server

**Operations:**
- `connect` - Connect to ClickHouse CLI
- `query` - Execute ClickHouse query
- `logs` / `logs-operator` / `logs-mcp` - View logs
- `port-forward` / `port-forward-mcp` - Port forwarding
- `restart` / `restart-operator` / `restart-mcp` - Restart components
- `clean-data` - Drop all observability data (WARNING!)
- `optimize` - Optimize ClickHouse tables

### Kind Cluster Management

Manage local Kubernetes development cluster:

```bash
# Create Kind cluster
noetl run automation/infrastructure/kind.yaml --set action=create

# Check status
noetl run automation/infrastructure/kind.yaml --set action=status

# List all Kind clusters
noetl run automation/infrastructure/kind.yaml --set action=list

# Load NoETL image to cluster
noetl run automation/infrastructure/kind.yaml --set action=image-load

# List images in cluster
noetl run automation/infrastructure/kind.yaml --set action=images-list

# Set kubectl context to kind-noetl
noetl run automation/infrastructure/kind.yaml --set action=context-set

# Delete cluster
noetl run automation/infrastructure/kind.yaml --set action=delete
```

**Cluster Management:**
- `create` - Create Kind cluster 'noetl'
- `delete` - Delete Kind cluster 'noetl'
- `list` - List all Kind clusters
- `status` - Check cluster status and nodes
- `context-set` - Set kubectl context to kind-noetl

**Image Management:**
- `image-load` - Load NoETL image to cluster
- `images-list` - List images in cluster

### JupyterLab

Manage JupyterLab deployment for data analysis:

```bash
# Full deployment workflow
noetl run automation/infrastructure/jupyterlab.yaml --set action=full

# Deploy JupyterLab
noetl run automation/infrastructure/jupyterlab.yaml --set action=deploy

# Check status
noetl run automation/infrastructure/jupyterlab.yaml --set action=status

# View logs
noetl run automation/infrastructure/jupyterlab.yaml --set action=logs

# Port-forward to localhost:8888
noetl run automation/infrastructure/jupyterlab.yaml --set action=port-forward

# Update notebook ConfigMap
noetl run automation/infrastructure/jupyterlab.yaml --set action=update-notebook

# Remove JupyterLab
noetl run automation/infrastructure/jupyterlab.yaml --set action=undeploy
```

**Deployment Actions:**
- `deploy` - Deploy JupyterLab to kind cluster
- `undeploy` - Remove JupyterLab
- `full` - Complete deployment workflow
- `status` - Check deployment status

**Operations:**
- `logs` - View JupyterLab logs
- `port-forward` - Port-forward to localhost:8888
- `restart` - Restart deployment
- `shell` - Open shell in JupyterLab pod
- `test` - Test deployment
- `update-notebook` - Update notebook ConfigMap and restart

### Gateway API

Manage Gateway API service (Rust-based, located in crates/gateway):

```bash
# Build and deploy everything
noetl run automation/infrastructure/gateway.yaml --set action=deploy-all

# Build Gateway image
noetl run automation/infrastructure/gateway.yaml --set action=build-image

# Deploy Gateway API
noetl run automation/infrastructure/gateway.yaml --set action=deploy

# Check status
noetl run automation/infrastructure/gateway.yaml --set action=status

# Test endpoints
noetl run automation/infrastructure/gateway.yaml --set action=test

# View logs
noetl run automation/infrastructure/gateway.yaml --set action=logs

# Rebuild and redeploy
noetl run automation/infrastructure/gateway.yaml --set action=redeploy

# Remove Gateway
noetl run automation/infrastructure/gateway.yaml --set action=remove
```

**Build & Deployment:**
- `build-image` - Build Gateway Docker image and load into kind
- `deploy` - Deploy Gateway API to Kubernetes
- `deploy-all` - Build and deploy Gateway API and UI
- `remove` - Remove Gateway from Kubernetes
- `redeploy` - Rebuild and redeploy Gateway

**Operations:**
- `restart` - Restart Gateway pods
- `status` - Check deployment status
- `logs` - Show Gateway logs
- `test` - Test Gateway endpoints

**Location:** `crates/gateway`

### Gateway UI

Manage Gateway UI (located in tests/fixtures/gateway_ui):

```bash
# Deploy Gateway UI
noetl run automation/infrastructure/gateway-ui.yaml --set action=deploy

# Check status
noetl run automation/infrastructure/gateway-ui.yaml --set action=status

# Update UI files
noetl run automation/infrastructure/gateway-ui.yaml --set action=update

# View logs
noetl run automation/infrastructure/gateway-ui.yaml --set action=logs
```

**Deployment:**
- `deploy` - Deploy Gateway UI to Kubernetes
- `update` - Regenerate and deploy updated UI files

**Operations:**
- `status` - Check deployment status
- `logs` - Show Gateway UI logs

**Location:** `tests/fixtures/gateway_ui`

### Dev Tools

Manage development tooling installation and validation (WSL/Ubuntu):

```bash
# Setup and validate all tools
noetl run automation/development/tooling.yaml --set action=setup

# Install base tools
noetl run automation/development/tooling.yaml --set action=install-base

# Install all dev tools
noetl run automation/development/tooling.yaml --set action=install-devtools

# Validate installation
noetl run automation/development/tooling.yaml --set action=validate-install

# Install individual tools
noetl run automation/development/tooling.yaml --set action=install-kind
noetl run automation/development/tooling.yaml --set action=install-pyenv
noetl run automation/development/tooling.yaml --set action=install-uv

# Fix Docker permissions
noetl run automation/development/tooling.yaml --set action=fix-docker-perms
```

**Setup & Validation:**
- `setup` - Validate required tooling on WSL2 hosts
- `validate-install` - Validate required tools are installed
- `validate-devtools` - Validate optional dev tools
- `validate-docker` - Validate Docker Desktop integration

**Installation (Base):**
- `install-base` - Install basic CLI tools (git, curl, jq, make, python3, etc.)
- `install-devtools` - Install all dev tools (yq, kind, pyenv, uv, tfenv)

**Installation (Individual):**
- `install-jq`, `install-yq`, `install-kind`, `install-pyenv`, `install-uv`, `install-tfenv`, `install-psql`

**Configuration:**
- `ensure-path` - Ensure tool paths in ~/.bashrc
- `fix-docker-perms` - Add user to docker group

### Docker Operations

Manage Docker image building and cleanup:

```bash
# Build NoETL image
noetl run automation/development/docker.yaml --set action=build

# Check Docker status
noetl run automation/development/docker.yaml --set action=status

# Cleanup all Docker resources
noetl run automation/development/docker.yaml --set action=cleanup-all

# Clear all images
noetl run automation/development/docker.yaml --set action=images-clear
```

**Build Actions:**
- `build` - Build NoETL Docker image
- `noetl-image-build` - Build noetl container with docker

**Cleanup Actions:**
- `cleanup-all` - Clean all docker resources (builders, images, volumes)
- `images-clear` - Clear all docker images

**Status:**
- `status` - Check Docker status with version, images, containers, disk usage

## Best Practices

### Execution

1. **Start with help** - Always run `--set action=help` or `--set target=help` to see available options
2. **Use full workflows** - Prefer `action=full` for complete setup rather than manual step-by-step
3. **Check status** - Run `action=status` to verify deployments before testing
4. **Use verbose for debugging** - Add `-v` or `--verbose` when troubleshooting issues
5. **Validate prerequisites** - Bootstrap validates required tools automatically
6. **NATS is required** - Don't skip observability deployment, NATS is mandatory

### Runtime Selection

All automation playbooks include the `executor` section specifying local runtime:

```yaml
executor:
  profile: local
  version: noetl-runtime/1
```

Run with explicit runtime if needed:

```bash
# Force local runtime (default for automation)
noetl run automation/setup/bootstrap.yaml -r local

# Check current context runtime
noetl context current
```

### Variable Passing

Pass variables with `--set key=value`:

```bash
# Single variable
noetl run automation/infrastructure/postgres.yaml --set action=deploy

# Multiple variables  
noetl run automation/setup/bootstrap.yaml --set target=noetl --set skip_qdrant=true

# Control Rust CLI build and Gateway deployment
noetl run automation/setup/bootstrap.yaml --set build_rust_cli=true --set deploy_gateway=false
```

## Troubleshooting

### Bootstrap Fails

1. Check prerequisites: `noetl run automation/setup/bootstrap.yaml --set target=validate -v`
2. Verify Docker running: `docker ps`
3. Check existing cluster: `kind get clusters`
4. View detailed output: Add `-v` flag for verbose output

### Image Loading Issues

If pods show `ImagePullBackOff`:
1. Rebuild and load: `noetl run automation/setup/bootstrap.yaml --set target=build`
2. Check image exists: `docker images | grep noetl`
3. Manually load: `kind load docker-image local/noetl:TAG --name noetl`

### Pagination Server Not Ready

```bash
# Check status
noetl run automation/test/pagination-server.yaml --set action=status

# View logs
noetl run automation/test/pagination-server.yaml --set action=logs

# Redeploy
noetl run automation/test/pagination-server.yaml --set action=undeploy
noetl run automation/test/pagination-server.yaml --set action=full
```

## Directory Structure

```
automation/
├── main.yaml                      # Main router
├── README.md                      # Complete reference and task mappings
├── setup/
│   ├── bootstrap.yaml            # Complete K8s environment setup
│   └── destroy.yaml              # Environment teardown
├── infrastructure/
│   ├── clickhouse.yaml           # ClickHouse observability stack
│   ├── gateway.yaml              # Gateway API service
│   ├── gateway-ui.yaml           # Gateway UI
│   ├── jupyterlab.yaml           # JupyterLab deployment
│   ├── kind.yaml                 # Kind cluster management
│   ├── monitoring.yaml           # VictoriaMetrics monitoring stack
│   ├── postgres.yaml             # PostgreSQL deployment
│   └── qdrant.yaml               # Qdrant vector database
├── development/
│   ├── docker.yaml               # Docker operations
│   └── tooling.yaml              # Dev tools installation
└── test/
    └── pagination-server.yaml    # Pagination test server
```

## Next Steps

- See [Local Development Setup](./local_dev_setup.md) for manual setup instructions
- See [Kind Kubernetes](./kind_kubernetes.md) for cluster management
- See [Docker Usage](./docker_usage.md) for container workflows
- See [Testing Guide](../test/README.md) for test infrastructure details
