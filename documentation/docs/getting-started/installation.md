---
sidebar_position: 2
title: Installation
description: Installation options for NoETL
---

# Installation

NoETL can be installed from PyPI or deployed as a Kubernetes service.

## PyPI Installation

### Basic Installation

```bash
pip install noetl
```

### Specific Version

```bash
pip install noetl==2.5.2
```

### Verify Installation

```bash
noetl --version
noetl --help
```

## Kubernetes Deployment

For production deployments, NoETL runs as a Kubernetes service with PostgreSQL backend.

### Prerequisites

- Docker
- kubectl
- Helm 3.x
- Kind (for local development)

### Local Development with Kind

```bash
# Clone repository
git clone https://github.com/noetl/noetl.git
cd noetl

# Bootstrap complete environment
make bootstrap
```

This creates a Kind cluster with:
- NoETL server and workers
- PostgreSQL database
- Observability stack (ClickHouse, Qdrant, NATS)
- Monitoring stack (VictoriaMetrics, Grafana)

### Manual Kubernetes Deployment

```bash
# Create namespace
kubectl create namespace noetl

# Deploy PostgreSQL
helm install postgres bitnami/postgresql \
  --namespace noetl \
  --set auth.database=noetl \
  --set auth.username=noetl \
  --set auth.password=noetl

# Deploy NoETL (using Helm chart)
helm install noetl ./ci/manifests/noetl \
  --namespace noetl \
  --set server.replicas=1 \
  --set worker.replicas=3
```

## Using NoETL as a Git Submodule

For integrating NoETL infrastructure into another project:

```bash
# Add NoETL as a submodule (name it .noetl)
git submodule add https://github.com/noetl/noetl.git .noetl
git submodule update --init --recursive

# Bootstrap environment
make -C .noetl bootstrap
```

After bootstrap, NoETL tasks are available with `noetl:` prefix:

```bash
task noetl:k8s:deploy              # Deploy NoETL
task noetl:test:k8s:cluster-health # Check health
```

## Environment Variables

Key environment variables for configuration:

| Variable | Description | Default |
|----------|-------------|---------|
| `NOETL_SERVER_HOST` | Server bind address | `0.0.0.0` |
| `NOETL_SERVER_PORT` | Server port | `8082` |
| `NOETL_DATABASE_URL` | PostgreSQL connection | Required |
| `NOETL_WORKER_POOL_SIZE` | Worker pool size | `4` |
| `NOETL_LOG_LEVEL` | Logging level | `INFO` |

See [Environment Configuration](/docs/operations/environment_variables) for complete list.

## Verify Installation

### Check Server Status

```bash
curl http://localhost:8082/api/health
```

### List Registered Playbooks

```bash
noetl catalog list playbook --host localhost --port 8082
```

### Run Hello World

```bash
noetl run playbook "tests/fixtures/playbooks/hello_world" \
  --host localhost --port 8082
```

## Next Steps

- [Quick Start](/docs/getting-started/quickstart) - Your first playbook
- [Architecture](/docs/getting-started/architecture) - System components
- [CLI Reference](/docs/reference/noetl_cli_usage) - Command reference
