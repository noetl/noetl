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
- CI/CD workflows

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

## Bootstrap Workflow

Complete K8s environment setup including:
- Prerequisite validation (noetl, docker, kind, kubectl, task, python3, uv)
- Rust CLI binary compilation
- Docker image building
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

# Start from specific step
noetl run automation/setup/bootstrap.yaml validate_prerequisites
noetl run automation/setup/bootstrap.yaml build_docker_images
noetl run automation/setup/bootstrap.yaml deploy_observability
```

### Steps

1. **validate_prerequisites** - Check required tools
2. **check_docker_running** - Verify Docker daemon
3. **check_existing_cluster** - Check for existing cluster
4. **build_rust_cli** - Build noetlctl binary
5. **build_docker_images** - Build NoETL container
6. **create_kind_cluster** - Create K8s cluster
7. **load_image_to_kind** - Load image to cluster
8. **deploy_postgres** - Deploy PostgreSQL
9. **deploy_noetl** - Deploy NoETL server/workers
10. **deploy_observability** - Deploy ClickHouse, Qdrant, NATS
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

## Best Practices

1. **Start with help** - Always run `--set action=help` or `--set target=help` to see available options
2. **Use full workflows** - Prefer `action=full` for complete setup rather than manual step-by-step
3. **Check status** - Run `action=status` to verify deployments before testing
4. **Use verbose for debugging** - Add `--verbose` when troubleshooting issues
5. **Validate prerequisites** - Bootstrap validates required tools automatically
6. **NATS is required** - Don't skip observability deployment, NATS is mandatory

## Troubleshooting

### Bootstrap Fails

1. Check prerequisites: `noetl run automation/setup/bootstrap.yaml validate_prerequisites`
2. Verify Docker running: `docker ps`
3. Check existing cluster: `kind get clusters`
4. View logs: Add `--verbose` flag

### Image Loading Issues

If pods show `ImagePullBackOff`:
1. Rebuild and load: `noetl run automation/setup/bootstrap.yaml build_docker_images`
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
├── README.md                      # Detailed documentation
├── setup/
│   ├── bootstrap.yaml            # Environment setup
│   └── destroy.yaml              # Cleanup
├── infrastructure/
│   ├── postgres.yaml             # PostgreSQL management
│   ├── qdrant.yaml               # Qdrant management
│   └── monitoring.yaml           # VictoriaMetrics monitoring stack
└── test/
    └── pagination-server.yaml    # Test server automation
```

## Next Steps

- See [Local Development Setup](./local_dev_setup.md) for manual setup instructions
- See [Kind Kubernetes](./kind_kubernetes.md) for cluster management
- See [Docker Usage](./docker_usage.md) for container workflows
- See [Testing Guide](../test/README.md) for test infrastructure details
