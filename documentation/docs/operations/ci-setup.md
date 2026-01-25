---
id: ci-setup
title: CI/CD Infrastructure Setup
sidebar_label: CI Setup
sidebar_position: 1
---

# CI/CD Infrastructure Setup

NoETL uses a Kubernetes-based CI/CD infrastructure for local development and testing. This guide covers all components deployed to the Kind cluster.

## Overview

The CI infrastructure consists of:

- **Kind Cluster**: Local Kubernetes cluster for development
- **PostgreSQL**: Primary database for NoETL state and catalog
- **NoETL Services**: Server and worker deployments
- **Observability Stack**: ClickHouse, Qdrant, NATS JetStream
- **Monitoring**: VictoriaMetrics stack with Grafana

## Kind Cluster

### Cluster Configuration

- **Name**: `noetl-cluster` (default)
- **Kubernetes Version**: Latest stable
- **Network**: Bridge mode with port mappings
- **Registry**: Local registry integration

### Port Mappings

NodePort services expose the following ports:

| Service | Port | Purpose |
|---------|------|---------|
| PostgreSQL | 30543 | Database access |
| NoETL Server | 30083 | API and UI |
| ClickHouse HTTP | 30123 | Query interface |
| ClickHouse Native | 30900 | Native protocol |
| Qdrant HTTP | 30633 | REST API |
| Qdrant gRPC | 30634 | gRPC API |
| NATS Client | 30422 | Messaging |
| NATS Monitoring | 30822 | Dashboard |

### Cluster Management

```bash
# Create cluster
noetl run automation/infrastructure/kind.yaml --set action=create

# Delete cluster
noetl run automation/infrastructure/kind.yaml --set action=delete

# Load images
noetl run automation/infrastructure/kind.yaml --set action=load-image

# Check status
kubectl cluster-info
kubectl get nodes
```

## PostgreSQL

### Deployment

PostgreSQL is deployed as a StatefulSet with persistent storage.

**Namespace**: `postgres`
**Service**: `postgres`
**Port**: 5432 (internal), 30543 (NodePort)

### Configuration

- **Version**: PostgreSQL 15+
- **Storage**: 10Gi PVC
- **Credentials**: Configured via ConfigMap/Secret
- **Schema**: Auto-initialized from `noetl/database/ddl/postgres/schema_ddl.sql`

### Database Schema

Main tables:
- `resource` - Resource definitions
- `catalog` - Playbook catalog
- `workload` - Execution payloads
- `event` - Event log (source of truth)
- `workflow` - Workflow definitions
- `credential` - Stored credentials
- `queue` - Job queue
- `schedule` - Scheduled executions

### Management

```bash
# Deploy PostgreSQL
noetl run automation/infrastructure/postgres.yaml --set action=deploy

# Remove PostgreSQL
noetl run automation/infrastructure/postgres.yaml --set action=remove

# Port forward
noetl run automation/infrastructure/postgres.yaml --set action=port-forward

# Access via psql
kubectl exec -it -n postgres deploy/postgres -- psql -U noetl -d noetl
```

## NoETL Services

### Server

FastAPI-based orchestration engine.

**Namespace**: `noetl`
**Deployment**: `noetl-server`
**Replicas**: 1
**Port**: 8083 (internal), 30083 (NodePort)

**Endpoints**:
- `/api/catalog` - Playbook registration
- `/api/execution` - Execution management
- `/api/credentials` - Credential management
- `/api/queue` - Job queue
- `/api/events` - Event stream
- `/health` - Health check

### Worker

Job execution workers that poll from PostgreSQL queue.

**Namespace**: `noetl`
**Deployment**: `noetl-worker`
**Replicas**: 1-5 (configurable)

**Features**:
- Polling-based job acquisition
- Plugin-based action execution
- Event reporting to server
- Automatic retry on failure

### Deployment

```bash
# Deploy both server and workers
noetl run automation/deployment/noetl-stack.yaml --set action=deploy

# Redeploy (rebuild + deploy)
noetl run automation/development/noetl.yaml --set action=redeploy

# Remove
noetl run automation/deployment/noetl-stack.yaml --set action=remove

# Scale workers
kubectl scale deployment noetl-worker -n noetl --replicas=3
```

### Configuration

Environment variables via ConfigMap:
- `NOETL_*` - Application settings
- `POSTGRES_*` - Database connection
- `TZ` - Timezone (must match PostgreSQL)

## Monitoring Stack

VictoriaMetrics-based monitoring with Grafana dashboards.

### Components

1. **VictoriaMetrics Single**: Time-series database
2. **Grafana**: Visualization and dashboards
3. **Prometheus Exporters**: Metrics collection

### Access

```bash
# Deploy monitoring stack
noetl run automation/infrastructure/monitoring.yaml --set action=deploy

# Access Grafana
noetl run automation/infrastructure/monitoring.yaml --set action=port-forward
# Open http://localhost:3000
```

### Pre-configured Dashboards

- NoETL Server metrics
- Worker execution metrics
- PostgreSQL database metrics
- Kubernetes cluster metrics

## Bootstrap Process

### Complete Bootstrap

```bash
noetl run automation/setup/bootstrap.yaml
```

This executes:
1. Verify dependencies (Docker, kubectl, helm, kind)
2. Build NoETL Docker images
3. Create Kind cluster
4. Load images into cluster
5. Deploy PostgreSQL
6. Deploy observability stack
7. Deploy monitoring stack
8. Deploy NoETL services

### Manual Step-by-Step

```bash
# 1. Build images
noetl run automation/development/docker.yaml --set action=build

# 2. Create cluster
noetl run automation/infrastructure/kind.yaml --set action=create

# 3. Load images
noetl run automation/infrastructure/kind.yaml --set action=load-image

# 4. Deploy components
noetl run automation/infrastructure/postgres.yaml --set action=deploy
noetl run automation/infrastructure/observability.yaml --set action=deploy
noetl run automation/infrastructure/monitoring.yaml --set action=deploy
noetl run automation/deployment/noetl-stack.yaml --set action=deploy
```

### Verification

```bash
# Check cluster health
kubectl get nodes
kubectl get pods -A

# Verify NoETL
curl http://localhost:30083/health

# Check observability services
noetl run automation/infrastructure/observability.yaml --set action=status
```

## Development Workflows

### Local Development

```bash
# Start infrastructure
noetl run automation/setup/bootstrap.yaml

# Make code changes...

# Rebuild and redeploy
noetl run automation/development/noetl.yaml --set action=redeploy

# View logs
kubectl logs -n noetl deployment/noetl-server -f
kubectl logs -n noetl deployment/noetl-worker -f
```

### Testing

```bash
# Run regression tests
noetl run tests/fixtures/playbooks/regression_test/regression_test.yaml

# Test specific playbook
noetl run path/to/playbook.yaml
```

### Cleanup

```bash
# Destroy all infrastructure
noetl run automation/setup/destroy.yaml

# Or delete just the cluster
noetl run automation/infrastructure/kind.yaml --set action=delete
```

## Troubleshooting

### Cluster Issues

```bash
# Check cluster status
kubectl get nodes
kubectl get pods --all-namespaces

# Check events
kubectl get events --sort-by='.lastTimestamp'

# Describe problematic pod
kubectl describe pod <pod-name>
```

### Service Issues

```bash
# Check logs
kubectl logs <pod-name>
kubectl logs <pod-name> --previous  # Previous container

# Port conflicts
lsof -i :30083  # macOS
netstat -tulpn | grep 30083  # Linux

# Image pull issues
noetl run automation/infrastructure/kind.yaml --set action=load-image
```

### Database Issues

```bash
# Check PostgreSQL status
kubectl get pods -n postgres

# Connect to database
kubectl exec -it -n postgres deploy/postgres -- psql -U noetl -d noetl

# Check schema
\dt noetl.*
```

## Resource Requirements

### Minimum

- **CPU**: 4 cores
- **Memory**: 8GB RAM
- **Storage**: 30GB

### Recommended

- **CPU**: 8 cores
- **Memory**: 16GB RAM
- **Storage**: 50GB

### Resource Breakdown

| Component | Memory | CPU | Storage |
|-----------|--------|-----|---------|
| Kind Cluster | 1Gi | 1 core | 5Gi |
| PostgreSQL | 1Gi | 500m | 10Gi |
| NoETL Server | 512Mi | 250m | - |
| NoETL Worker | 512Mi | 250m | - |
| ClickHouse | 2Gi | 2 cores | 6Gi |
| Qdrant | 2Gi | 1 core | 5Gi |
| NATS | 2Gi | 1 core | 5Gi |
| Monitoring | 2Gi | 1 core | 5Gi |

## Configuration Files

### Manifests

Located in `ci/manifests/`:
- `postgres/` - PostgreSQL deployment
- `noetl/` - Server and worker deployments
- `clickhouse/` - ClickHouse operator and cluster
- `qdrant/` - Qdrant vector database
- `nats/` - NATS JetStream
- `timezone-config.yaml` - Timezone configuration

### Automation Playbooks

Located in `automation/`:
- `setup/bootstrap.yaml` - Full environment setup
- `setup/destroy.yaml` - Tear down environment
- `infrastructure/kind.yaml` - Kind cluster management
- `infrastructure/postgres.yaml` - PostgreSQL operations
- `infrastructure/monitoring.yaml` - VictoriaMetrics stack
- `infrastructure/observability.yaml` - Unified observability control
- `infrastructure/clickhouse.yaml` - ClickHouse operations
- `infrastructure/qdrant.yaml` - Qdrant operations
- `infrastructure/nats.yaml` - NATS operations
- `deployment/noetl-stack.yaml` - NoETL service deployment
- `development/docker.yaml` - Docker image building
- `development/noetl.yaml` - Development workflow

### Environment Configuration

Environment variables are managed through:
- ConfigMaps for non-sensitive config
- Secrets for credentials
- `.env.local` for local development

Key settings:
- `NOETL_HOST` - Server hostname
- `NOETL_PORT` - Server port
- `POSTGRES_HOST` - Database host
- `POSTGRES_PORT` - Database port
- `TZ` - Timezone (UTC default, must match across components)

## CI/CD Pipeline Integration

### GitHub Actions

The CI infrastructure can be used in GitHub Actions:

```yaml
- name: Setup Kind cluster
  run: noetl run automation/infrastructure/kind.yaml --set action=create

- name: Deploy infrastructure
  run: noetl run automation/setup/bootstrap.yaml

- name: Run tests
  run: pytest tests/
```

### Local Testing

Mirror CI behavior locally:

```bash
# Full CI simulation
noetl run automation/setup/bootstrap.yaml
pytest tests/
noetl run automation/setup/destroy.yaml
```

## Best Practices

1. **Use automation playbooks**: Use `noetl run` commands for infrastructure management
2. **Check health before testing**: Verify all pods are running
3. **Clean state**: Clean up between test runs if needed
4. **Monitor resources**: Watch `kubectl top nodes` and `kubectl top pods`
5. **Match timezones**: Ensure `TZ` is consistent across all components
6. **Port conflicts**: Check ports before starting cluster
7. **Image management**: Rebuild and reload images after code changes

## References

- [Kind Documentation](https://kind.sigs.k8s.io/)
- [Kubernetes Documentation](https://kubernetes.io/docs/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [Architecture Design](/docs/reference/architecture_design)
- [Observability Services](/docs/reference/observability_services)
