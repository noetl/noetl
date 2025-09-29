# NoETL Unified Platform Deployment

This directory contains scripts for deploying NoETL in a unified architecture where the server, workers, and observability stack all run in the same Kubernetes namespace within a single cluster.

## Architecture

### Before (Separate Deployments)
- **NoETL Server**: `noetl` namespace
- **Workers**: `noetl-worker-cpu-01`, `noetl-worker-cpu-02`, `noetl-worker-gpu-01` namespaces
- **Observability**: `observability` namespace  
- **PostgreSQL**: `postgres` namespace

### After (Unified Deployment)
- **All NoETL Components**: `noetl-platform` namespace (or custom name)
  - NoETL server
  - All worker pools (cpu-01, cpu-02, gpu-01)
  - Observability stack (Grafana, VictoriaMetrics, VictoriaLogs, Vector)
- **PostgreSQL**: `postgres` namespace (unchanged)

## Benefits

1. **Simplified Management**: All components in one namespace
2. **Better Service Discovery**: Direct service-to-service communication
3. **Unified Monitoring**: Observability stack monitors everything in the same namespace
4. **Resource Efficiency**: Reduced namespace overhead
5. **Easier Networking**: No cross-namespace communication needed

## Quick Start

### 1. Clean Up Existing Deployments

If you have existing NoETL deployments, clean them up first:

```bash
./k8s/cleanup-old-deployments.sh
```

### 2. Deploy Unified Platform

```bash
./k8s/deploy-unified-platform.sh
```

This will:
- Create/reuse the Kind cluster
- Deploy PostgreSQL (if not already deployed)
- Create a unified namespace (`noetl-platform`)
- Deploy NoETL server and all workers in the unified namespace
- Deploy observability stack in the same namespace
- Set up monitoring and port-forwarding

### 3. Access Services

After deployment, services are available at:

- **NoETL Server**: http://localhost:30082/api/health
- **Grafana**: http://localhost:3000 (admin/admin)
- **VictoriaMetrics**: http://localhost:8428/vmui/
- **VictoriaLogs**: http://localhost:9428

## Advanced Usage

### Custom Namespace

Deploy to a custom namespace:

```bash
./k8s/deploy-unified-platform.sh --namespace my-noetl-platform
```

### Selective Deployment

Skip certain components:

```bash
# Skip observability
./k8s/deploy-unified-platform.sh --no-observability

# Skip PostgreSQL (if already deployed)
./k8s/deploy-unified-platform.sh --no-postgres

# Use existing cluster
./k8s/deploy-unified-platform.sh --no-cluster
```

### Development Mode

Deploy from local repository:

```bash
./k8s/deploy-unified-platform.sh --deploy-noetl-dev --repo-path /path/to/noetl
```

## Components

### Scripts

- `deploy-unified-platform.sh` - Main deployment script
- `generate-unified-noetl-deployment.sh` - Generates unified NoETL YAML
- `deploy-unified-observability.sh` - Deploys observability to unified namespace
- `cleanup-old-deployments.sh` - Cleans up separate deployments

### Generated Resources

The unified deployment creates:

**NoETL Components:**
- `noetl-server` - Server deployment and service
- `noetl-worker-cpu-01` - CPU worker pool 1
- `noetl-worker-cpu-02` - CPU worker pool 2  
- `noetl-worker-gpu-01` - GPU worker pool

**Observability Components:**
- `vmstack` - VictoriaMetrics stack (includes Grafana)
- `vlogs` - VictoriaLogs for log aggregation
- `vector` - Log and metrics collection
- Custom VMPodScrape resources for NoETL monitoring

## Monitoring

### Metrics Collection

The unified deployment automatically sets up:

1. **Prometheus Annotations**: All pods have prometheus scrape annotations
2. **VMPodScrape Resources**: Custom resources for VictoriaMetrics agent
3. **Service Discovery**: Automatic discovery of NoETL components
4. **Unified Dashboards**: Grafana dashboards for server and workers

### Port Forwarding Management

```bash
# Check status
./k8s/observability/port-forward-unified.sh status

# Stop all port-forwards
./k8s/observability/port-forward-unified.sh stop

# Start port-forwards
./k8s/observability/port-forward-unified.sh start
```

## Troubleshooting

### Check Deployment Status

```bash
# Check all pods in unified namespace
kubectl get pods -n noetl-platform

# Check services
kubectl get services -n noetl-platform

# Check logs
kubectl logs -n noetl-platform -l app=noetl
kubectl logs -n noetl-platform -l component=worker
```

### Common Issues

1. **Workers not starting**: Check if server is ready first
2. **Observability issues**: Ensure Helm repos are updated
3. **Port conflicts**: Check for existing port-forwards

### Cleanup

To completely remove the unified deployment:

```bash
# Delete unified namespace
kubectl delete namespace noetl-platform

# Delete cluster
kind delete cluster --name noetl-cluster
```

## Migration from Separate Deployments

1. **Backup data** (if any persistent data exists)
2. **Run cleanup script** to remove old deployments
3. **Deploy unified platform** using the new script
4. **Verify all components** are running in unified namespace
5. **Update any external clients** to use new service endpoints

The unified deployment maintains compatibility with existing NoETL configurations and APIs.