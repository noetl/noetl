---
id: command-reference
title: Command Reference
sidebar_label: Command Reference
sidebar_position: 2
---

# NoETL Command Reference

Complete reference for all NoETL automation playbooks and CLI commands.

## Quick Start

```bash
# Complete environment setup
noetl run automation/setup/bootstrap.yaml

# Destroy environment
noetl run automation/setup/destroy.yaml

# Build Docker image
noetl build

# Deploy to Kubernetes
noetl k8s deploy
```

## Setup Commands

### Bootstrap Environment

```bash
noetl run automation/setup/bootstrap.yaml
```

Performs complete K8s environment setup:
1. Verify dependencies (Docker, kubectl, kind)
2. Check ports availability (54321, 3000, 9428, 8082)
3. Build noetlctl Rust CLI
4. Build NoETL Docker image
5. Create kind Kubernetes cluster
6. Load image into kind
7. Deploy PostgreSQL
8. Deploy observability stack (ClickHouse, Qdrant, NATS)
9. Deploy monitoring stack (VictoriaMetrics, Grafana)
10. Deploy NoETL server and workers

**Options:**
```bash
# Force rebuild Rust CLI
noetl run automation/setup/bootstrap.yaml --set build_rust_cli=true

# Skip Gateway deployment
noetl run automation/setup/bootstrap.yaml --set deploy_gateway=false

# Use minimal kind config
noetl run automation/setup/bootstrap.yaml --set kind_config=ci/kind/config-minimal.yaml
```

### Destroy Environment

```bash
noetl run automation/setup/destroy.yaml
```

Cleans up all resources:
1. Delete kind cluster
2. Clean Docker resources
3. Clear cache directories
4. Clear NoETL data and logs

## Infrastructure Commands

### Kind Cluster

| Action | Command |
|--------|---------|
| Create cluster | `noetl run automation/infrastructure/kind.yaml --set action=create` |
| Delete cluster | `noetl run automation/infrastructure/kind.yaml --set action=delete` |
| List clusters | `noetl run automation/infrastructure/kind.yaml --set action=list` |
| Check status | `noetl run automation/infrastructure/kind.yaml --set action=status` |
| Load image | `noetl run automation/infrastructure/kind.yaml --set action=image-load` |
| List images | `noetl run automation/infrastructure/kind.yaml --set action=images-list` |
| Set context | `noetl run automation/infrastructure/kind.yaml --set action=context-set` |

### PostgreSQL

| Action | Command |
|--------|---------|
| Deploy | `noetl run automation/infrastructure/postgres.yaml --set action=deploy` |
| Remove | `noetl run automation/infrastructure/postgres.yaml --set action=remove` |
| Status | `noetl run automation/infrastructure/postgres.yaml --set action=status` |
| Logs | `noetl run automation/infrastructure/postgres.yaml --set action=logs` |
| Schema reset | `noetl run automation/infrastructure/postgres.yaml --set action=schema-reset` |
| Clear cache | `noetl run automation/infrastructure/postgres.yaml --set action=clear-cache` |
| Port forward | `noetl run automation/infrastructure/postgres.yaml --set action=port-forward` |

### ClickHouse

| Action | Command |
|--------|---------|
| Deploy | `noetl run automation/infrastructure/clickhouse.yaml --set action=deploy` |
| Remove | `noetl run automation/infrastructure/clickhouse.yaml --set action=undeploy` |
| Status | `noetl run automation/infrastructure/clickhouse.yaml --set action=status` |
| Health | `noetl run automation/infrastructure/clickhouse.yaml --set action=health` |
| Connect CLI | `noetl run automation/infrastructure/clickhouse.yaml --set action=connect` |
| Logs | `noetl run automation/infrastructure/clickhouse.yaml --set action=logs` |
| Query | `noetl run automation/infrastructure/clickhouse.yaml --set action=query` |
| Port forward | `noetl run automation/infrastructure/clickhouse.yaml --set action=port-forward` |
| Deploy schema | `noetl run automation/infrastructure/clickhouse.yaml --set action=deploy-schema` |
| Clean data | `noetl run automation/infrastructure/clickhouse.yaml --set action=clean-data` |
| Optimize | `noetl run automation/infrastructure/clickhouse.yaml --set action=optimize` |

### Qdrant

| Action | Command |
|--------|---------|
| Deploy | `noetl run automation/infrastructure/qdrant.yaml --set action=deploy` |
| Remove | `noetl run automation/infrastructure/qdrant.yaml --set action=undeploy` |
| Status | `noetl run automation/infrastructure/qdrant.yaml --set action=status` |
| Health | `noetl run automation/infrastructure/qdrant.yaml --set action=health` |
| Logs | `noetl run automation/infrastructure/qdrant.yaml --set action=logs` |
| Collections | `noetl run automation/infrastructure/qdrant.yaml --set action=collections` |
| Test | `noetl run automation/infrastructure/qdrant.yaml --set action=test` |
| Restart | `noetl run automation/infrastructure/qdrant.yaml --set action=restart` |
| Port forward | `noetl run automation/infrastructure/qdrant.yaml --set action=port-forward` |

### NATS JetStream

| Action | Command |
|--------|---------|
| Deploy | `noetl run automation/infrastructure/nats.yaml --set action=deploy` |
| Remove | `noetl run automation/infrastructure/nats.yaml --set action=undeploy` |
| Status | `noetl run automation/infrastructure/nats.yaml --set action=status` |
| Health | `noetl run automation/infrastructure/nats.yaml --set action=health` |
| Logs | `noetl run automation/infrastructure/nats.yaml --set action=logs` |
| Streams | `noetl run automation/infrastructure/nats.yaml --set action=streams` |
| Monitoring | `noetl run automation/infrastructure/nats.yaml --set action=monitoring` |
| Connect | `noetl run automation/infrastructure/nats.yaml --set action=connect` |
| Test | `noetl run automation/infrastructure/nats.yaml --set action=test` |
| Restart | `noetl run automation/infrastructure/nats.yaml --set action=restart` |
| Port forward | `noetl run automation/infrastructure/nats.yaml --set action=port-forward` |

### Observability (Aggregate)

Control all observability services (ClickHouse, Qdrant, NATS) together:

| Action | Command |
|--------|---------|
| Deploy all | `noetl run automation/infrastructure/observability.yaml --set action=deploy` |
| Remove all | `noetl run automation/infrastructure/observability.yaml --set action=remove` |
| Status all | `noetl run automation/infrastructure/observability.yaml --set action=status` |
| Health all | `noetl run automation/infrastructure/observability.yaml --set action=health` |
| Restart all | `noetl run automation/infrastructure/observability.yaml --set action=restart` |

### Monitoring (VictoriaMetrics)

| Action | Command |
|--------|---------|
| Deploy | `noetl run automation/infrastructure/monitoring.yaml --set action=deploy` |
| Remove | `noetl run automation/infrastructure/monitoring.yaml --set action=undeploy` |
| Status | `noetl run automation/infrastructure/monitoring.yaml --set action=status` |
| Grafana creds | `noetl run automation/infrastructure/monitoring.yaml --set action=grafana-creds` |
| Deploy dashboards | `noetl run automation/infrastructure/monitoring.yaml --set action=deploy-dashboards` |
| Deploy exporter | `noetl run automation/infrastructure/monitoring.yaml --set action=deploy-exporter` |
| Deploy NoETL scrape | `noetl run automation/infrastructure/monitoring.yaml --set action=deploy-noetl-scrape` |
| Deploy Vector | `noetl run automation/infrastructure/monitoring.yaml --set action=deploy-vector` |
| Deploy VictoriaLogs | `noetl run automation/infrastructure/monitoring.yaml --set action=deploy-vmlogs` |

### JupyterLab

| Action | Command |
|--------|---------|
| Full deploy | `noetl run automation/infrastructure/jupyterlab.yaml --set action=full` |
| Deploy | `noetl run automation/infrastructure/jupyterlab.yaml --set action=deploy` |
| Remove | `noetl run automation/infrastructure/jupyterlab.yaml --set action=undeploy` |
| Status | `noetl run automation/infrastructure/jupyterlab.yaml --set action=status` |
| Logs | `noetl run automation/infrastructure/jupyterlab.yaml --set action=logs` |
| Port forward | `noetl run automation/infrastructure/jupyterlab.yaml --set action=port-forward` |
| Update notebook | `noetl run automation/infrastructure/jupyterlab.yaml --set action=update-notebook` |
| Restart | `noetl run automation/infrastructure/jupyterlab.yaml --set action=restart` |
| Shell | `noetl run automation/infrastructure/jupyterlab.yaml --set action=shell` |

### Gateway API

| Action | Command |
|--------|---------|
| Deploy all | `noetl run automation/infrastructure/gateway.yaml --set action=deploy-all` |
| Build image | `noetl run automation/infrastructure/gateway.yaml --set action=build-image` |
| Deploy | `noetl run automation/infrastructure/gateway.yaml --set action=deploy` |
| Remove | `noetl run automation/infrastructure/gateway.yaml --set action=remove` |
| Status | `noetl run automation/infrastructure/gateway.yaml --set action=status` |
| Logs | `noetl run automation/infrastructure/gateway.yaml --set action=logs` |
| Test | `noetl run automation/infrastructure/gateway.yaml --set action=test` |
| Redeploy | `noetl run automation/infrastructure/gateway.yaml --set action=redeploy` |
| Restart | `noetl run automation/infrastructure/gateway.yaml --set action=restart` |

## Deployment Commands

### NoETL Stack

| Action | Command |
|--------|---------|
| Deploy | `noetl run automation/deployment/noetl-stack.yaml --set action=deploy` |
| Remove | `noetl run automation/deployment/noetl-stack.yaml --set action=remove` |
| Status | `noetl run automation/deployment/noetl-stack.yaml --set action=status` |
| Logs | `noetl run automation/deployment/noetl-stack.yaml --set action=logs` |

## Development Commands

### Docker

| Action | Command |
|--------|---------|
| Build image | `noetl run automation/development/docker.yaml --set action=build` |
| Status | `noetl run automation/development/docker.yaml --set action=status` |
| Cleanup all | `noetl run automation/development/docker.yaml --set action=cleanup-all` |
| Clear images | `noetl run automation/development/docker.yaml --set action=images-clear` |

### NoETL Development

| Action | Command |
|--------|---------|
| Deploy | `noetl run automation/development/noetl.yaml --set action=deploy` |
| Redeploy | `noetl run automation/development/noetl.yaml --set action=redeploy` |

### Dev Tools Setup

**OS-Aware (auto-detects macOS vs Linux):**

| Action | Command |
|--------|---------|
| Detect OS | `noetl run automation/development/setup_tooling.yaml --set action=detect` |
| Install dev tools | `noetl run automation/development/setup_tooling.yaml --set action=install-devtools` |
| Validate tools | `noetl run automation/development/setup_tooling.yaml --set action=validate-install` |

**macOS (Homebrew):**

| Action | Command |
|--------|---------|
| Install base | `noetl run automation/development/tooling_macos.yaml --set action=install-base` |
| Install dev tools | `noetl run automation/development/tooling_macos.yaml --set action=install-devtools` |
| Install Homebrew | `noetl run automation/development/tooling_macos.yaml --set action=install-homebrew` |

**Linux/WSL2 (apt-get):**

| Action | Command |
|--------|---------|
| Install base | `noetl run automation/development/tooling_linux.yaml --set action=install-base` |
| Install dev tools | `noetl run automation/development/tooling_linux.yaml --set action=install-devtools` |
| Fix Docker perms | `noetl run automation/development/tooling_linux.yaml --set action=fix-docker-perms` |

## Test Commands

### Pagination Test Server

| Action | Command |
|--------|---------|
| Full workflow | `noetl run automation/test/pagination-server.yaml --set action=full` |
| Build | `noetl run automation/test/pagination-server.yaml --set action=build` |
| Load | `noetl run automation/test/pagination-server.yaml --set action=load` |
| Deploy | `noetl run automation/test/pagination-server.yaml --set action=deploy` |
| Status | `noetl run automation/test/pagination-server.yaml --set action=status` |
| Test | `noetl run automation/test/pagination-server.yaml --set action=test` |
| Logs | `noetl run automation/test/pagination-server.yaml --set action=logs` |
| Remove | `noetl run automation/test/pagination-server.yaml --set action=undeploy` |

### Regression Tests

```bash
noetl run tests/fixtures/playbooks/regression_test/regression_test.yaml
```

## GCP Infrastructure as Playbook (IAP)

NoETL provides Infrastructure as Playbook capabilities for GCP resources.

### GKE Autopilot Cluster

| Action | Command |
|--------|---------|
| Create cluster | `noetl run automation/iap/gcp/gke_autopilot.yaml --set action=create --set project_id=<project>` |
| Deploy stack | `noetl run automation/iap/gcp/gke_autopilot.yaml --set action=deploy --set project_id=<project>` |
| Destroy cluster | `noetl run automation/iap/gcp/gke_autopilot.yaml --set action=destroy --set project_id=<project>` |
| Show plan | `noetl run automation/iap/gcp/gke_autopilot.yaml --set action=plan --set project_id=<project>` |

### Full GKE Stack Deployment

Deploy complete NoETL stack to GKE (PostgreSQL, NATS, ClickHouse, NoETL, Gateway):

| Action | Command |
|--------|---------|
| Deploy all | `noetl run automation/iap/gcp/deploy_gke_stack.yaml --set project_id=<project>` |
| Destroy all | `noetl run automation/iap/gcp/deploy_gke_stack.yaml --set action=destroy --set project_id=<project>` |
| Check status | `noetl run automation/iap/gcp/deploy_gke_stack.yaml --set action=status --set project_id=<project>` |

**Example - Deploy to noetl-demo-19700101:**
```bash
noetl run automation/iap/gcp/deploy_gke_stack.yaml \
  --set project_id=noetl-demo-19700101 \
  --set region=us-central1
```

### Artifact Registry

| Action | Command |
|--------|---------|
| Create repository | `noetl run automation/iap/gcp/artifact_registry.yaml --set action=create --set project_id=<project>` |
| Delete repository | `noetl run automation/iap/gcp/artifact_registry.yaml --set action=destroy --set project_id=<project>` |

### GCS State Bucket

| Action | Command |
|--------|---------|
| Initialize bucket | `noetl run automation/iap/gcp/init_state_bucket.yaml --set project_id=<project>` |

## Rust CLI Commands

The `noetl` Rust CLI provides direct commands:

### Build Commands

| Command | Description |
|---------|-------------|
| `noetl build` | Build Docker image |
| `noetl build --no-cache` | Build without cache |

### Kubernetes Commands

| Command | Description |
|---------|-------------|
| `noetl k8s deploy` | Deploy to kind cluster |
| `noetl k8s remove` | Remove from cluster |
| `noetl k8s redeploy` | Rebuild and redeploy |
| `noetl k8s reset` | Full reset (schema + redeploy + test setup) |

### Server/Worker Commands

| Command | Description |
|---------|-------------|
| `noetl server start` | Start FastAPI server |
| `noetl server stop` | Stop server |
| `noetl worker start` | Start worker |
| `noetl worker stop` | Stop worker |

### Database Commands

| Command | Description |
|---------|-------------|
| `noetl db init` | Initialize database schema |
| `noetl db validate` | Validate database schema |

### Playbook Commands

| Command | Description |
|---------|-------------|
| `noetl run <path>` | Execute playbook |
| `noetl run <path> --set key=value` | Execute with variables |
| `noetl run <path> -v` | Execute with verbose output |
| `noetl playbook register <path>` | Register playbook to catalog |
| `noetl execution create <path>` | Create execution |

## Service Ports

After deployment, services are available at:

| Service | Port | URL |
|---------|------|-----|
| NoETL API | 8082 | http://localhost:8082 |
| PostgreSQL | 54321 | localhost:54321 |
| Grafana | 3000 | http://localhost:3000 |
| VictoriaLogs | 9428 | http://localhost:9428 |
| ClickHouse HTTP | 30123 | http://localhost:30123 |
| ClickHouse Native | 30900 | localhost:30900 |
| Qdrant HTTP | 30633 | http://localhost:30633 |
| Qdrant gRPC | 30634 | localhost:30634 |
| NATS Client | 30422 | localhost:30422 |
| NATS Monitoring | 30822 | http://localhost:30822 |
| Test Server | 30555 | http://localhost:30555 |

## Playbook Directory Structure

```
automation/
├── main.yaml                      # Main router
├── setup/
│   ├── bootstrap.yaml            # Complete K8s environment setup
│   └── destroy.yaml              # Environment teardown
├── infrastructure/
│   ├── kind.yaml                 # Kind cluster management
│   ├── postgres.yaml             # PostgreSQL operations
│   ├── clickhouse.yaml           # ClickHouse operations
│   ├── qdrant.yaml               # Qdrant operations
│   ├── nats.yaml                 # NATS operations
│   ├── observability.yaml        # Unified observability control
│   ├── monitoring.yaml           # VictoriaMetrics stack
│   ├── jupyterlab.yaml           # JupyterLab deployment
│   └── gateway.yaml              # Gateway API service
├── iap/
│   └── gcp/
│       ├── gke_autopilot.yaml    # GKE Autopilot cluster management
│       ├── deploy_gke_stack.yaml # Full GKE stack deployment
│       ├── artifact_registry.yaml # Artifact Registry management
│       ├── init_state_bucket.yaml # GCS state bucket initialization
│       ├── state_sync.yaml       # State synchronization
│       └── state_inspect.yaml    # State inspection
├── deployment/
│   └── noetl-stack.yaml          # NoETL service deployment
├── development/
│   ├── docker.yaml               # Docker operations
│   ├── noetl.yaml                # NoETL development workflow
│   ├── setup_tooling.yaml        # OS-aware tooling setup
│   ├── tooling_macos.yaml        # macOS tools (Homebrew)
│   └── tooling_linux.yaml        # Linux tools (apt-get)
├── helm/
│   ├── noetl/                    # NoETL Helm chart
│   └── gateway/                  # Gateway Helm chart
└── test/
    └── pagination-server.yaml    # Pagination test server
```

## See Also

- [CI Setup Guide](./ci-setup.md)
- [Observability Services](./observability.md)
- [Automation Playbooks](../development/automation_playbooks.md)
- [Local Development Setup](../development/local_dev_setup.md)
- [GKE Deployment Guide](./gke-deployment.md)
