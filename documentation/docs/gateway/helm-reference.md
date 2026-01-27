---
sidebar_position: 3
title: Helm Chart Reference
description: Gateway Helm chart configuration and values reference
---

# Gateway Helm Chart Reference

Complete reference for the NoETL Gateway Helm chart configuration.

:::info Chart Source
The Helm chart is located at [`automation/helm/gateway/`](https://github.com/noetl/noetl/tree/master/automation/helm/gateway).
:::

## Chart Location

```
automation/helm/gateway/
├── Chart.yaml
├── values.yaml
└── templates/
    ├── deployment.yaml
    ├── service.yaml
    └── ingress.yaml
```

## Installation

```bash
# Basic installation
helm upgrade --install noetl-gateway automation/helm/gateway \
  -n gateway --create-namespace \
  --set image.repository=us-central1-docker.pkg.dev/PROJECT/noetl/noetl-gateway

# With custom values file
helm upgrade --install noetl-gateway automation/helm/gateway \
  -n gateway -f my-values.yaml
```

## Values Reference

### Namespace

```yaml
namespace: gateway
```

The Kubernetes namespace where gateway resources are deployed.

### Image Configuration

```yaml
image:
  repository: ""              # Container image repository (required)
  tag: "latest"               # Image tag
  pullPolicy: IfNotPresent    # Image pull policy
```

**Examples:**
```yaml
# Google Artifact Registry
image:
  repository: us-central1-docker.pkg.dev/my-project/noetl/noetl-gateway
  tag: "20260127115929"

# Docker Hub
image:
  repository: myorg/noetl-gateway
  tag: "v1.0.0"
```

### Service Configuration

```yaml
service:
  type: LoadBalancer          # Service type: LoadBalancer, ClusterIP, NodePort
  port: 8090                  # Service port (internal)
  nodePort: null              # NodePort (only for type: NodePort)
  loadBalancerIP: ""          # Static IP for LoadBalancer
```

**Service Types:**

| Type | Use Case | External Access |
|------|----------|-----------------|
| `ClusterIP` | Internal only, use with Ingress | Via Ingress |
| `LoadBalancer` | Direct external access | Via cloud LB |
| `NodePort` | Testing, on-prem | Via node IP:port |

**Static IP Example:**
```yaml
service:
  type: LoadBalancer
  loadBalancerIP: "34.46.180.136"
```

### Ingress Configuration

```yaml
ingress:
  enabled: false              # Enable Kubernetes Ingress
  className: gce              # Ingress class (gce, nginx, etc.)
  annotations: {}             # Additional annotations
  host: gateway.example.com   # Hostname
  tls:
    enabled: true             # Enable TLS
    secretName: ""            # TLS secret name (if not using managed cert)
  managedCertificate:
    enabled: true             # Use GKE managed certificate
    name: gateway-managed-cert
```

**GKE Ingress with Managed Certificate:**
```yaml
ingress:
  enabled: true
  className: gce
  host: gateway.mydomain.com
  tls:
    enabled: true
  managedCertificate:
    enabled: true
    name: gateway-managed-cert
```

**Nginx Ingress with cert-manager:**
```yaml
ingress:
  enabled: true
  className: nginx
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
  host: gateway.mydomain.com
  tls:
    enabled: true
    secretName: gateway-tls
  managedCertificate:
    enabled: false
```

### Environment Variables

```yaml
env:
  routerPort: "8090"
  noetlBaseUrl: "http://noetl.noetl.svc.cluster.local:8082"
  rustLog: "info,gateway=debug"
  corsAllowedOrigins: "http://localhost:8080,http://localhost:8090"
  natsUrl: "nats://nats.nats.svc.cluster.local:4222"
  natsUpdatesSubjectPrefix: "playbooks.executions."
```

| Variable | Description | Required |
|----------|-------------|----------|
| `routerPort` | Port gateway listens on | Yes |
| `noetlBaseUrl` | NoETL server URL | Yes |
| `rustLog` | Rust logging configuration | No |
| `corsAllowedOrigins` | Comma-separated CORS origins | Yes |
| `natsUrl` | NATS server URL | No |
| `natsUpdatesSubjectPrefix` | NATS subject prefix | No |

**CORS Origins Examples:**
```yaml
# Development
corsAllowedOrigins: "http://localhost:3000,http://localhost:8080"

# Production
corsAllowedOrigins: "https://app.mydomain.com,https://admin.mydomain.com"

# Multiple environments
corsAllowedOrigins: "http://localhost:3000,https://staging.mydomain.com,https://app.mydomain.com"
```

### Resource Limits

```yaml
resources:
  requests:
    memory: "128Mi"
    cpu: "100m"
  limits:
    memory: "512Mi"
    cpu: "500m"
```

**Recommended settings by environment:**

| Environment | Memory Request | Memory Limit | CPU Request | CPU Limit |
|-------------|----------------|--------------|-------------|-----------|
| Development | 64Mi | 256Mi | 50m | 200m |
| Staging | 128Mi | 512Mi | 100m | 500m |
| Production | 256Mi | 1Gi | 200m | 1000m |

## Common Deployment Patterns

### Development (Local Testing)

```yaml
# values-dev.yaml
namespace: gateway-dev

service:
  type: ClusterIP

env:
  rustLog: "debug,gateway=trace"
  corsAllowedOrigins: "http://localhost:3000,http://localhost:8080,http://localhost:8090"

resources:
  requests:
    memory: "64Mi"
    cpu: "50m"
```

### Production with LoadBalancer

```yaml
# values-prod.yaml
namespace: gateway

service:
  type: LoadBalancer
  loadBalancerIP: "34.46.180.136"

env:
  rustLog: "info,gateway=info"
  corsAllowedOrigins: "https://app.mydomain.com"
  noetlBaseUrl: "http://noetl.noetl.svc.cluster.local:8082"

resources:
  requests:
    memory: "256Mi"
    cpu: "200m"
  limits:
    memory: "1Gi"
    cpu: "1000m"
```

### Production with Ingress

```yaml
# values-prod-ingress.yaml
namespace: gateway

service:
  type: ClusterIP

ingress:
  enabled: true
  className: gce
  host: gateway.mydomain.com
  tls:
    enabled: true
  managedCertificate:
    enabled: true
    name: gateway-cert

env:
  corsAllowedOrigins: "https://app.mydomain.com"
```

## Upgrading

```bash
# Upgrade with new values
helm upgrade noetl-gateway automation/helm/gateway -n gateway \
  --set image.tag=new-version

# Rollback if needed
helm rollback noetl-gateway -n gateway

# View history
helm history noetl-gateway -n gateway
```

## Uninstalling

```bash
# Uninstall release
helm uninstall noetl-gateway -n gateway

# Delete namespace (if desired)
kubectl delete namespace gateway

# Release static IP (if no longer needed)
gcloud compute addresses delete gateway-static-ip --region=us-central1
```
