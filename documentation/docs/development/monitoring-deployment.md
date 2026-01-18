---
sidebar_position: 15
---

# Monitoring Stack Deployment

Complete guide for deploying and managing the VictoriaMetrics monitoring stack.

## Overview

NoETL includes a complete monitoring stack based on VictoriaMetrics, providing:

- **Metrics Collection**: VMAgent scrapes metrics from NoETL, Postgres, and Kubernetes
- **Metrics Storage**: VMSingle stores time-series data
- **Visualization**: Grafana dashboards with pre-configured panels
- **Alerting**: VMAlert for metric-based alerts
- **Log Aggregation**: VictoriaLogs for centralized logging
- **Service Discovery**: Automatic discovery of services in Kubernetes

## Quick Start

Deploy the complete monitoring stack:

```bash
noetl run automation/infrastructure/monitoring.yaml --set action=deploy
```

This deploys:
- VictoriaMetrics Operator
- VMStack (VMSingle, VMAgent, VMAlert, Grafana)
- Metrics Server (Kubernetes metrics)
- Kube State Metrics
- Node Exporter
- PostgreSQL Exporter
- NoETL service monitors

## Access Services

All services are accessible via NodePort mappings configured in Kind cluster:

| Service | URL | Port Mapping |
|---------|-----|--------------|
| **Grafana** | http://localhost:3000 | 30300 → 3000 |
| **VictoriaLogs** | http://localhost:9428 | 30428 → 9428 |
| **NoETL API** | http://localhost:8082 | 30082 → 8082 |
| **PostgreSQL** | localhost:54321 | 30321 → 54321 |
| **ClickHouse HTTP** | http://localhost:30123 | 30123 → 30123 |
| **ClickHouse Native** | localhost:30900 | 30900 → 30900 |
| **Qdrant HTTP** | http://localhost:30633 | 30633 → 30633 |
| **Qdrant gRPC** | localhost:30634 | 30634 → 30634 |
| **NATS** | localhost:30422 | 30422 → 30422 |

### Grafana Access

Grafana is configured with **authentication disabled** for local development:

```bash
open http://localhost:3000
```

No credentials required - you'll have immediate access to all dashboards.

## Available Actions

### Main Actions

```bash
# Deploy complete stack
noetl run automation/infrastructure/monitoring.yaml --set action=deploy

# Check deployment status
noetl run automation/infrastructure/monitoring.yaml --set action=status

# Remove entire stack
noetl run automation/infrastructure/monitoring.yaml --set action=undeploy
```

### Helm Repository Management

```bash
# Add all monitoring helm repositories
noetl run automation/infrastructure/monitoring.yaml --set action=add-helm-repos

# Add individual repositories
noetl run automation/infrastructure/monitoring.yaml --set action=add-victoriametrics-helm-repo
noetl run automation/infrastructure/monitoring.yaml --set action=add-vector-helm-repo
noetl run automation/infrastructure/monitoring.yaml --set action=add-metrics-server-helm-repo
```

### Granular Deployment

Deploy components individually:

```bash
# Deploy VictoriaMetrics operator
noetl run automation/infrastructure/monitoring.yaml --set action=deploy-vmstack-operator

# Deploy VictoriaMetrics stack
noetl run automation/infrastructure/monitoring.yaml --set action=deploy-vmstack

# Deploy Metrics Server
noetl run automation/infrastructure/monitoring.yaml --set action=deploy-metrics-server

# Deploy PostgreSQL exporter
noetl run automation/infrastructure/monitoring.yaml --set action=deploy-exporter

# Deploy NoETL service scrape config
noetl run automation/infrastructure/monitoring.yaml --set action=deploy-noetl-scrape

# Deploy Vector log collector
noetl run automation/infrastructure/monitoring.yaml --set action=deploy-vector

# Deploy VictoriaLogs
noetl run automation/infrastructure/monitoring.yaml --set action=deploy-vmlogs

# Deploy Grafana dashboards
noetl run automation/infrastructure/monitoring.yaml --set action=deploy-dashboards
```

## Architecture

### Components

**VictoriaMetrics Operator**
- Namespace: `vmoperator`
- Manages VictoriaMetrics custom resources (VMAgent, VMSingle, VMAlert, etc.)
- Handles service discovery and scrape configuration

**VMStack**
- Namespace: `vmstack`
- **VMSingle**: Time-series database
- **VMAgent**: Metrics scraper and forwarder
- **VMAlert**: Alerting engine
- **Grafana**: Visualization and dashboards
- **Kube State Metrics**: Kubernetes cluster metrics
- **Node Exporter**: Node-level metrics

**Additional Exporters**
- **PostgreSQL Exporter**: Database metrics (namespace: `postgres`)
- **NoETL Service Monitors**: Application-specific metrics

### Data Flow

```
Kubernetes Services → VMAgent (scrapes) → VMSingle (stores) → Grafana (visualizes)
                                        ↓
                                    VMAlert (alerts)
```

## Verification

### Check Pod Status

```bash
# All monitoring components
kubectl get pods -A | grep -E "vm|grafana"

# Operator namespace
kubectl get pods -n vmoperator

# Stack namespace
kubectl get pods -n vmstack
```

Expected output:
```
NAMESPACE   NAME                                        READY   STATUS
vmoperator  vmoperator-victoria-metrics-operator-...    1/1     Running
vmstack     vmagent-vmstack-...                         2/2     Running
vmstack     vmalertmanager-vmstack-...                  2/2     Running
vmstack     vmsingle-vmstack-...                        1/1     Running
vmstack     vmstack-grafana-...                         2/2     Running
vmstack     vmstack-kube-state-metrics-...              1/1     Running
vmstack     vmstack-prometheus-node-exporter-...        1/1     Running
```

### Check Services

```bash
kubectl get svc -n vmstack
```

### Test Metrics Collection

```bash
# Query VMSingle directly
curl http://localhost:8429/api/v1/query?query=up

# Or through Grafana Explore view
open http://localhost:3000/explore
```

## Dashboards

Pre-configured Grafana dashboards:

### NoETL Dashboards
- **NoETL Overview**: High-level application metrics
- **NoETL Server**: Server-specific metrics
- **NoETL Worker**: Worker pool metrics
- **Execution Details**: Per-execution metrics

### PostgreSQL Dashboards
- **PostgreSQL Overview**: Database health and performance
- **PostgreSQL Queries**: Query performance and statistics
- **PostgreSQL Connections**: Connection pool monitoring

### Kubernetes Dashboards
- **Cluster Overview**: Node and pod metrics
- **Resource Usage**: CPU, memory, disk utilization
- **Network Traffic**: Network I/O across cluster

## Configuration

### Custom Scrape Configs

Add custom service monitors by creating VMServiceScrape resources:

```yaml
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMServiceScrape
metadata:
  name: my-service
  namespace: vmstack
spec:
  selector:
    matchLabels:
      app: my-service
  endpoints:
  - port: metrics
    path: /metrics
```

### Retention Settings

Modify VMSingle retention (default: 7 days):

```bash
kubectl edit vmsingle -n vmstack vmstack-victoria-metrics-k8s-stack
```

Change `retentionPeriod` value.

### Grafana Configuration

Grafana configuration is managed via Helm values. To customize:

1. Extract current values:
```bash
helm get values vmstack -n vmstack > vmstack-values.yaml
```

2. Modify `grafana` section

3. Upgrade release:
```bash
helm upgrade vmstack vm/victoria-metrics-k8s-stack \
  -n vmstack \
  -f vmstack-values.yaml
```

## Troubleshooting

### Pods Not Starting

Check events:
```bash
kubectl get events -n vmstack --sort-by='.lastTimestamp'
```

Check logs:
```bash
kubectl logs -n vmstack -l app.kubernetes.io/name=vmsingle
```

### No Metrics Appearing

1. Check VMAgent is running:
```bash
kubectl logs -n vmstack -l app.kubernetes.io/name=vmagent
```

2. Verify service discovery:
```bash
kubectl get vmservicescrape -n vmstack
```

3. Check scrape targets in Grafana:
   - Go to http://localhost:3000
   - Configuration → Data Sources → VictoriaMetrics
   - Explore → Query: `up`

### Grafana Dashboard Not Loading

1. Verify Grafana pod is running:
```bash
kubectl get pods -n vmstack | grep grafana
```

2. Check Grafana logs:
```bash
kubectl logs -n vmstack -l app.kubernetes.io/name=grafana
```

3. Restart Grafana:
```bash
kubectl rollout restart deployment/vmstack-grafana -n vmstack
```

### Port Mapping Issues

Port mappings are defined in `ci/kind/config.yaml`. Changes require cluster recreation:

```bash
# Delete cluster
kind delete cluster --name noetl

# Recreate with new config
kind create cluster --config ci/kind/config.yaml
```

## Cleanup

### Remove Individual Components

```bash
# Remove dashboards
noetl run automation/infrastructure/monitoring.yaml --set action=remove-dashboards

# Remove exporters
noetl run automation/infrastructure/monitoring.yaml --set action=remove-exporter

# Remove VMStack
noetl run automation/infrastructure/monitoring.yaml --set action=remove-vmstack

# Remove operator
noetl run automation/infrastructure/monitoring.yaml --set action=remove-vmstack-operator
```

### Complete Removal

```bash
noetl run automation/infrastructure/monitoring.yaml --set action=undeploy
```

This removes:
- All VMStack components
- VictoriaMetrics operator
- Metrics Server
- Custom resource definitions
- Namespaces (`vmstack`, `vmoperator`)

## Production Considerations

For production deployments:

1. **Enable Authentication**: Configure Grafana with proper authentication
2. **TLS/HTTPS**: Enable TLS for all service endpoints
3. **Persistence**: Configure persistent storage for metrics
4. **High Availability**: Deploy VMCluster instead of VMSingle
5. **Resource Limits**: Set appropriate CPU/memory limits
6. **Backup**: Configure regular backups for metrics data
7. **Alerting**: Set up alert receivers (email, Slack, PagerDuty)
8. **Retention**: Adjust retention period based on requirements

Example production Helm values:

```yaml
vmsingle:
  retentionPeriod: "30d"
  persistence:
    enabled: true
    storageClassName: "fast-ssd"
    size: 100Gi
  resources:
    limits:
      cpu: "2"
      memory: "4Gi"

grafana:
  admin:
    existingSecret: grafana-admin-secret
  ingress:
    enabled: true
    tls:
      - secretName: grafana-tls
        hosts:
          - grafana.example.com
```

## Related Documentation

- [Automation Playbooks](./automation_playbooks.md)
- [Observability Services](../reference/observability_services.md)
- [Kind Cluster Setup](./kind_kubernetes.md)
