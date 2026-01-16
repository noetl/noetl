---
id: ci-setup
title: CI/CD Infrastructure Setup
sidebar_label: CI Setup
sidebar_position: 1
---

# CI/CD Infrastructure Setup

NoETL uses a comprehensive Kubernetes-based CI/CD infrastructure for local development and testing. This guide covers all components deployed to the Kind cluster.

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
task kind:local:cluster-create

# Delete cluster
task kind:local:cluster-delete

# Load images
task kind:local:image-load

# Check status
kubectl cluster-info
kubectl get nodes
```

## PostgreSQL

### Deployment

PostgreSQL is deployed as a StatefulSet with persistent storage.

**Namespace**: `default`  
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

### Tasks

```bash
# Deploy PostgreSQL
task postgres:k8s:deploy

# Remove PostgreSQL
task postgres:k8s:remove

# Port forward
task postgres:k8s:port-forward

# Access via psql
task postgres:local:shell
```

## NoETL Services

### Server

FastAPI-based orchestration engine.

**Namespace**: `default`  
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

**Namespace**: `default`  
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
task noetl:k8s:deploy

# Redeploy (rebuild + deploy)
task noetl:k8s:redeploy

# Remove
task noetl:k8s:remove

# Scale workers
kubectl scale deployment noetl-worker --replicas=3
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
task monitoring:k8s:deploy

# Access Grafana
kubectl port-forward -n vmstack svc/vmstack-grafana 3000:80
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
task bootstrap
# or
task bring-all
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
# 1. Check dependencies
task tools:local:verify

# 2. Build images
task docker:local:noetl-image-build

# 3. Create cluster
task kind:local:cluster-create

# 4. Load images
task kind:local:image-load

# 5. Deploy components
task postgres:k8s:deploy
task observability:activate-all
task monitoring:k8s:deploy
task noetl:k8s:deploy
```

### Verification

```bash
# Check cluster health
task test-cluster-health

# Verify all components
task bootstrap:verify

# Check observability services
task observability:status-all
```

## Development Workflows

### Local Development

```bash
# Start infrastructure
task dev:start

# Make code changes...

# Rebuild and redeploy
task noetl:k8s:redeploy

# View logs
task noetl:local:logs-server
task noetl:local:logs-worker
```

### Testing

```bash
# Run integration tests
task test-control-flow-full
task test-iterator-save-full
task test-save-storage-full

# Test specific playbook
task test-playbook -- path/to/playbook.yaml
```

### Cleanup

```bash
# Stop all services
task dev:stop

# Clear caches
task clear-all-cache

# Full cleanup
task kind:local:cluster-delete
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
task tshoot:local:check-ports

# Image pull issues
task kind:local:image-load
```

### Database Issues

```bash
# Check PostgreSQL status
task postgres:local:status

# Connect to database
task postgres:local:shell

# Check schema
psql -d demo_noetl -c '\dt'
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

### Taskfiles

Located in `ci/taskfile/`:
- `kind.yml` - Kind cluster management
- `postgres.yml` - PostgreSQL operations
- `noetl.yml` - NoETL service management
- `docker.yml` - Docker image building
- `clickhouse.yml` - ClickHouse tasks
- `qdrant.yml` - Qdrant tasks
- `nats.yml` - NATS tasks
- `observability.yml` - Unified observability control
- `vmstack.yml` - Monitoring stack
- `test.yml` - Integration tests

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
  run: task kind:local:cluster-create

- name: Deploy infrastructure
  run: task bring-all

- name: Run tests
  run: task test-all
```

### Local Testing

Mirror CI behavior locally:

```bash
# Full CI simulation
task bring-all
task test-all
task clear-all-cache
task kind:local:cluster-delete
```

## Best Practices

1. **Always use tasks**: Use taskfile commands instead of kubectl directly
2. **Check health before testing**: Run `task test-cluster-health`
3. **Clean state**: Use `task clear-all-cache` between test runs
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
