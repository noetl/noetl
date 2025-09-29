# NoETL Unified Deployment Guide

This guide covers the unified deployment architecture for NoETL, which consolidates all components into a single Kubernetes namespace with integrated observability.

## Overview

The unified deployment represents a significant improvement over the previous separate namespace architecture, providing:

- **Simplified Management**: All NoETL components in one namespace
- **Better Performance**: Direct service-to-service communication
- **Unified Observability**: Integrated monitoring and logging
- **Resource Efficiency**: Reduced namespace overhead
- **Easier Troubleshooting**: Everything in one location

## Architecture Comparison

### Before: Separate Namespaces
```
├── noetl                    # Server
├── noetl-worker-cpu-01     # CPU Worker 1
├── noetl-worker-cpu-02     # CPU Worker 2  
├── noetl-worker-gpu-01     # GPU Worker
├── observability           # Grafana, VictoriaMetrics, etc.
└── postgres                # Database
```

### After: Unified Platform
```
├── noetl-platform          # Server + Workers + Observability
└── postgres                # Database (unchanged)
```

## Quick Start

### Prerequisites

- **Docker**: For running Kind and building images
- **Kind**: Kubernetes in Docker
- **kubectl**: Kubernetes command-line tool  
- **Helm**: For observability stack deployment

### Installation

```bash
# Install prerequisites on macOS
brew install docker kind kubectl helm

# Install prerequisites on Linux (Ubuntu/Debian)
sudo apt update
sudo apt install docker.io
curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.20.0/kind-linux-amd64
chmod +x ./kind && sudo mv ./kind /usr/local/bin/kind
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl && sudo mv kubectl /usr/local/bin/kubectl
curl https://get.helm.sh/helm-v3.12.0-linux-amd64.tar.gz | tar xz
sudo mv linux-amd64/helm /usr/local/bin/helm
```

### Deployment

```bash
# Clone repository
git clone https://github.com/noetl/noetl.git
cd noetl

# Deploy unified platform (recommended)
make unified-deploy

# OR: Complete recreation from scratch
make unified-recreate-all

# OR: Direct script usage
./k8s/deploy-unified-platform.sh
```

### Management Commands

```bash
# Health checking
make unified-health-check          # Check platform health

# Port forwarding
make unified-port-forward-start    # Start port forwards
make unified-port-forward-status   # Check status
make unified-port-forward-stop     # Stop port forwards

# Credentials
make unified-grafana-credentials   # Get Grafana password

# Utilities
make help                          # Show all commands
```

## Deployment Components

### NoETL Platform (Namespace: `noetl-platform`)

#### Server Component
- **Deployment**: `noetl-server`
- **Service**: `noetl-server` (NodePort 30082)
- **Image**: `noetl-local-dev:latest`
- **Port**: 8082
- **Health Check**: `/api/health`

#### Worker Components
- **CPU Workers**: `noetl-worker-cpu-01`, `noetl-worker-cpu-02`
- **GPU Worker**: `noetl-worker-gpu-01`
- **Image**: `noetl-local-dev:latest`
- **Metrics Port**: 8080
- **Init Container**: Waits for server readiness

#### Observability Stack
- **VictoriaMetrics**: Metrics storage and querying
- **Grafana**: Dashboard and visualization
- **VictoriaLogs**: Log aggregation and search  
- **Vector**: Log and metrics collection
- **VMPodScrape**: Automatic NoETL metrics collection

### PostgreSQL (Namespace: `postgres`)
- **Deployment**: `postgres`
- **Service**: `postgres`
- **Image**: `postgres-noetl:latest`
- **Storage**: Persistent volume
- **Schema Job**: `noetl-apply-schema`

## Configuration Options

### Basic Options

```bash
# Skip cluster creation (use existing)
./k8s/deploy-unified-platform.sh --no-cluster

# Skip PostgreSQL (if already deployed)
./k8s/deploy-unified-platform.sh --no-postgres  

# Skip observability stack
./k8s/deploy-unified-platform.sh --no-observability

# Skip NoETL deployment
./k8s/deploy-unified-platform.sh --no-noetl-pip
```

### Advanced Options

```bash
# Custom namespace
./k8s/deploy-unified-platform.sh --namespace my-platform

# Development mode (from local repo)
./k8s/deploy-unified-platform.sh --deploy-noetl-dev

# Custom repo path
./k8s/deploy-unified-platform.sh --deploy-noetl-dev --repo-path /path/to/noetl
```

## Accessing Services

### NoETL API
- **Base URL**: http://localhost:30082
- **Health Check**: http://localhost:30082/api/health
- **API Documentation**: http://localhost:30082/docs
- **OpenAPI Spec**: http://localhost:30082/openapi.json

### Observability Dashboards
- **Grafana**: http://localhost:3000 (admin/admin)
- **VictoriaMetrics**: http://localhost:8428/vmui/
- **VictoriaLogs**: http://localhost:9428

### Port-Forward Management

```bash
# Check port-forward status
./k8s/observability/port-forward-unified.sh status

# Stop all port-forwards
./k8s/observability/port-forward-unified.sh stop

# Start port-forwards
./k8s/observability/port-forward-unified.sh start
```

## Monitoring and Troubleshooting

### Health Checks

```bash
# Check all components
kubectl get pods -n noetl-platform
kubectl get services -n noetl-platform

# Test NoETL API
curl http://localhost:30082/api/health

# Check PostgreSQL
kubectl get pods -n postgres
```

### Log Analysis

```bash
# NoETL server logs
kubectl logs -n noetl-platform -l app=noetl

# Worker logs
kubectl logs -n noetl-platform -l component=worker

# Follow logs in real-time
kubectl logs -n noetl-platform -l app=noetl -f

# PostgreSQL logs  
kubectl logs -n postgres -l app=postgres
```

### Resource Usage

```bash
# Check resource usage
kubectl top pods -n noetl-platform
kubectl top nodes

# Detailed pod information
kubectl describe pods -n noetl-platform

# Check events
kubectl get events -n noetl-platform --sort-by='.lastTimestamp'
```

## Metrics and Monitoring

### Automatic Monitoring

The unified deployment automatically sets up:

1. **Prometheus Annotations**: All NoETL pods have scrape annotations
2. **VMPodScrape Resources**: Custom resources for VictoriaMetrics collection
3. **Service Discovery**: Automatic discovery of NoETL components
4. **Grafana Dashboards**: Pre-configured dashboards for server and workers

### Custom Metrics

NoETL components expose metrics on the following endpoints:
- **Server**: `http://noetl-server:8082/metrics`
- **Workers**: `http://worker-pod:8080/metrics`

### Dashboard Access

Access Grafana at http://localhost:3000 with:
- **Username**: admin
- **Password**: admin

Pre-configured dashboards include:
- NoETL Server Overview
- Worker Pool Performance
- PostgreSQL Database Metrics
- Kubernetes Cluster Overview

## Migration from Legacy Deployment

### From Separate Namespaces

1. **Backup existing data** (if any persistent data exists)
2. **Clean up old deployments**:
   ```bash
   ./k8s/cleanup-old-deployments.sh
   ```
3. **Deploy unified platform**:
   ```bash
   ./k8s/deploy-unified-platform.sh
   ```
4. **Verify all components** are running
5. **Update client configurations** if needed

### Configuration Changes

The unified deployment maintains API compatibility, but some internal service names change:

**Before (Legacy)**:
- Server: `http://noetl.noetl.svc.cluster.local:8082`
- Workers: Various namespace services

**After (Unified)**:
- Server: `http://noetl-server.noetl-platform.svc.cluster.local:8082`  
- Workers: Same namespace as server

## Cleanup

### Remove Unified Deployment

```bash
# Delete unified namespace
kubectl delete namespace noetl-platform

# Delete PostgreSQL (optional)
kubectl delete namespace postgres

# Delete entire cluster
kind delete cluster --name noetl-cluster
```

### Cleanup Scripts

```bash
# Clean up old deployments (before migration)
./k8s/cleanup-old-deployments.sh

# Stop port-forwards
./k8s/observability/port-forward-unified.sh stop
```

## Troubleshooting

### Common Issues

1. **Images not found**: Run `./k8s/build-and-load-images.sh` first
2. **PostgreSQL issues**: Check PVC binding and storage
3. **Port conflicts**: Ensure ports 3000, 8428, 9428, 30082 are available
4. **Resource limits**: Increase Docker memory/CPU if needed

### Debug Commands

```bash
# Check image availability in cluster
docker exec noetl-cluster-control-plane crictl images | grep noetl

# Check cluster resources
kubectl describe nodes

# Check storage
kubectl get pv,pvc -A

# Check network policies
kubectl get networkpolicies -A
```

### Getting Help

1. Check logs: `kubectl logs -n noetl-platform -l app=noetl`
2. Check events: `kubectl get events -n noetl-platform`
3. Describe pods: `kubectl describe pod -n noetl-platform <pod-name>`
4. Check service connectivity: `kubectl exec -n noetl-platform <pod> -- curl http://noetl-server:8082/api/health`

## Best Practices

1. **Resource Limits**: Set appropriate CPU/memory limits for production
2. **Persistent Storage**: Use proper storage classes for production PostgreSQL  
3. **Security**: Configure RBAC and network policies
4. **Monitoring**: Set up alerts for critical metrics
5. **Backup**: Regular database backups for production use