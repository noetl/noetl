---
id: gke-deployment
title: GKE Deployment Guide
sidebar_label: GKE Deployment
sidebar_position: 5
---

# NoETL GKE Deployment Guide

Deploy NoETL to Google Kubernetes Engine (GKE) Autopilot clusters using Infrastructure as Playbook (IAP).

## Overview

NoETL provides playbook-based infrastructure provisioning for GCP, allowing you to:

- Create and manage GKE Autopilot clusters
- Deploy the complete NoETL stack (PostgreSQL, NATS, ClickHouse, NoETL, Gateway)
- Manage Artifact Registry for container images
- Automatically initialize database schema and register in-cluster credentials
- Handle state management with GCS buckets

## Prerequisites

1. **GCP Project** with billing enabled
2. **gcloud CLI** installed and authenticated
3. **kubectl** installed
4. **Helm** installed (v3+)
5. **Docker** installed (for building images)
6. **NoETL CLI** installed

### Authenticate with GCP

```bash
# Login to GCP
gcloud auth login

# Set default project
gcloud config set project noetl-demo-19700101

# Enable required APIs
gcloud services enable container.googleapis.com
gcloud services enable artifactregistry.googleapis.com
gcloud services enable storage.googleapis.com
```

## Quick Start

### Deploy Complete Stack

Deploy the entire NoETL stack to GKE with a single command:

```bash
noetl run automation/iap/gcp/deploy_gke_stack.yaml \
  --set project_id=noetl-demo-19700101
```

This creates:
- GKE Autopilot cluster
- Artifact Registry repository
- **Builds and pushes all container images** (NoETL server, Gateway, Worker Pool)
- PostgreSQL database with NoETL schema initialized
- NATS JetStream
- ClickHouse analytics database
- NoETL server and workers
- NoETL Gateway
- In-cluster credentials automatically registered

### Check Status

```bash
noetl run automation/iap/gcp/deploy_gke_stack.yaml \
  --set action=status \
  --set project_id=noetl-demo-19700101
```

### Destroy Stack

```bash
noetl run automation/iap/gcp/deploy_gke_stack.yaml \
  --set action=destroy \
  --set project_id=noetl-demo-19700101
```

## Step-by-Step Deployment

### 1. Create Artifact Registry

```bash
noetl run automation/iap/gcp/artifact_registry.yaml \
  --set action=create \
  --set project_id=noetl-demo-19700101 \
  --set region=us-central1
```

### 2. Build and Push Images

The NoETL stack requires building and pushing container images to Artifact Registry. The deployment playbook handles this automatically, with two build options:

#### Option A: Google Cloud Build (Recommended for ARM Mac)

Cloud Build runs on native AMD64 machines, making Rust compilation fast (~5-10 minutes instead of ~2 hours on ARM Mac with QEMU emulation):

```bash
noetl run automation/iap/gcp/deploy_gke_stack.yaml \
  --set project_id=noetl-demo-19700101 \
  --set use_cloud_build=true
```

This automatically builds and pushes:
- NoETL server (Python) - uses `E2_HIGHCPU_8` machine
- Gateway (Rust) - uses `E2_HIGHCPU_32` machine for faster compilation

#### Option B: Local Docker Build

If you're on an AMD64 machine or prefer local builds:

```bash
noetl run automation/iap/gcp/deploy_gke_stack.yaml \
  --set project_id=noetl-demo-19700101 \
  --set use_cloud_build=false
```

#### Option C: Skip Image Building

If images already exist in the registry:

```bash
noetl run automation/iap/gcp/deploy_gke_stack.yaml \
  --set project_id=noetl-demo-19700101 \
  --set build_images=false
```

#### Manual Build (if needed)

```bash
# Configure Docker for Artifact Registry
gcloud auth configure-docker us-central1-docker.pkg.dev

# Set environment variables
export PROJECT_ID=noetl-demo-19700101
export REGION=us-central1
export REGISTRY=${REGION}-docker.pkg.dev/${PROJECT_ID}/noetl
export TAG=$(date +%Y%m%d%H%M%S)  # Timestamped tag to avoid caching issues
```

##### Building on ARM Mac (Apple Silicon)

GKE Autopilot runs AMD64 nodes. When building locally on ARM Mac (M1/M2/M3), you must cross-compile, which is slow for Rust. **Recommended: Use Cloud Build instead.**

```bash
# For Python images (fast locally)
docker build --platform linux/amd64 -t ${REGISTRY}/noetl:${TAG} \
  -f docker/noetl/pip/Dockerfile \
  --build-arg NOETL_VERSION=latest \
  .
docker push ${REGISTRY}/noetl:${TAG}

# For Rust images (use Cloud Build - much faster!)
gcloud builds submit --project $PROJECT_ID \
  --tag ${REGISTRY}/noetl-gateway:${TAG} \
  --timeout=3600 \
  --machine-type=e2-highcpu-32 \
  -f crates/gateway/Dockerfile .
```

##### Build NoETL Server (Python)

```bash
# Build from PyPI Dockerfile
docker build --platform linux/amd64 -t ${REGISTRY}/noetl:${TAG} \
  -f docker/noetl/pip/Dockerfile \
  --build-arg NOETL_VERSION=latest \
  .

# Push to Artifact Registry
docker push ${REGISTRY}/noetl:${TAG}

# Also tag as latest
docker tag ${REGISTRY}/noetl:${TAG} ${REGISTRY}/noetl:latest
docker push ${REGISTRY}/noetl:latest
```

##### Build Gateway (Rust) - Recommended: Cloud Build

```bash
# Using Cloud Build (fast, native AMD64)
gcloud builds submit --project $PROJECT_ID \
  --tag ${REGISTRY}/noetl-gateway:${TAG} \
  --timeout=3600 \
  --machine-type=e2-highcpu-32 \
  -f crates/gateway/Dockerfile .

# Or local Docker (slow on ARM Mac)
docker build --platform linux/amd64 -t ${REGISTRY}/noetl-gateway:${TAG} \
  -f crates/gateway/Dockerfile \
  .
docker push ${REGISTRY}/noetl-gateway:${TAG}
```

##### Build Worker Pool (Rust) - Optional

The Rust worker pool is not required for basic deployments:

```bash
# Using Cloud Build (recommended)
gcloud builds submit --project $PROJECT_ID \
  --tag ${REGISTRY}/noetl-worker:${TAG} \
  --timeout=3600 \
  --machine-type=e2-highcpu-32 \
  -f crates/worker-pool/Dockerfile .
```

##### Verify Images

```bash
# List images in Artifact Registry
gcloud artifacts docker images list ${REGISTRY}
```

### 3. Create GKE Cluster

```bash
noetl run automation/iap/gcp/gke_autopilot.yaml \
  --set action=create \
  --set project_id=noetl-demo-19700101 \
  --set cluster_name=noetl-cluster \
  --set region=us-central1
```

### 4. Deploy Stack to Cluster

```bash
noetl run automation/iap/gcp/gke_autopilot.yaml \
  --set action=deploy \
  --set project_id=noetl-demo-19700101 \
  --set noetl_image_repository=us-central1-docker.pkg.dev/noetl-demo-19700101/noetl/noetl \
  --set noetl_image_tag=latest
```

## Configuration Options

### GKE Cluster Options

| Parameter | Default | Description |
|-----------|---------|-------------|
| `project_id` | (required) | GCP project ID |
| `cluster_name` | `noetl-cluster` | Cluster name |
| `region` | `us-central1` | GCP region |
| `release_channel` | `REGULAR` | GKE release channel (RAPID, REGULAR, STABLE) |
| `enable_private_nodes` | `true` | Enable private nodes |
| `network` | `default` | VPC network |
| `subnetwork` | `default` | VPC subnetwork |

### Component Toggles

| Parameter | Default | Description |
|-----------|---------|-------------|
| `create_cluster` | `true` | Create GKE cluster |
| `create_artifact_registry` | `true` | Create Artifact Registry |
| `build_images` | `true` | Build and push container images |
| `deploy_postgres` | `true` | Deploy PostgreSQL |
| `deploy_nats` | `true` | Deploy NATS JetStream |
| `deploy_clickhouse` | `true` | Deploy ClickHouse |
| `deploy_noetl` | `true` | Deploy NoETL |
| `deploy_gateway` | `true` | Deploy Gateway |
| `init_noetl_schema` | `true` | Initialize NoETL PostgreSQL schema |

### Docker Build Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `docker_platform` | `linux/amd64` | Target platform for Docker builds |
| `noetl_image_tag` | `latest` | Tag for NoETL server image |
| `gateway_image_tag` | `latest` | Tag for Gateway image |
| `worker_image_tag` | `latest` | Tag for Worker Pool image |

### Storage Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `postgres_size` | `20Gi` | PostgreSQL storage size |
| `clickhouse_size` | `10Gi` | ClickHouse storage size |
| `nats_jetstream_size` | `5Gi` | NATS JetStream storage size |

## Credentials

The deployment playbook automatically registers in-cluster credentials for NoETL workers:

| Credential | Type | Description |
|------------|------|-------------|
| `pg_demo` | postgres | In-cluster PostgreSQL for workers |
| `pg_k8s` | postgres | In-cluster PostgreSQL for workers |
| `noetl_ducklake_catalog` | postgres | PostgreSQL for DuckLake catalog |
| `nats_k8s` | nats | In-cluster NATS for messaging |
| `clickhouse_k8s` | clickhouse | In-cluster ClickHouse for observability |

### Manual Credential Registration

If you need to register credentials manually:

```bash
# Port forward to NoETL API
kubectl port-forward -n noetl svc/noetl 8082:8082

# Register a PostgreSQL credential
curl -X POST http://localhost:8082/api/credentials \
  -H "Content-Type: application/json" \
  -d '{
    "name": "pg_custom",
    "type": "postgres",
    "description": "Custom PostgreSQL connection",
    "tags": ["custom"],
    "data": {
      "host": "postgres.postgres.svc.cluster.local",
      "port": 5432,
      "user": "noetl",
      "password": "noetl",
      "database": "noetl"
    }
  }'

# List credentials
curl http://localhost:8082/api/credentials
```

### Test Credential Connectivity

```bash
# Test PostgreSQL connectivity
curl -X POST http://localhost:8082/api/postgres/execute \
  -H "Content-Type: application/json" \
  -d '{
    "credential_name": "pg_demo",
    "query": "SELECT current_database(), current_user, version()"
  }'
```

## Accessing Services

### Port Forwarding

After deployment, access services via port forwarding:

```bash
# NoETL API
kubectl port-forward -n noetl svc/noetl 8082:8082

# PostgreSQL
kubectl port-forward -n postgres svc/postgres 5432:5432

# ClickHouse
kubectl port-forward -n clickhouse svc/clickhouse 8123:8123

# NATS
kubectl port-forward -n nats svc/nats 4222:4222

# Gateway
kubectl port-forward -n gateway svc/noetl-gateway 8090:8090
```

### Internal Service URLs

Within the cluster, services are available at:

| Service | URL |
|---------|-----|
| NoETL | `http://noetl.noetl.svc.cluster.local:8082` |
| PostgreSQL | `postgres.postgres.svc.cluster.local:5432` |
| ClickHouse | `clickhouse.clickhouse.svc.cluster.local:8123` |
| NATS | `nats.nats.svc.cluster.local:4222` |
| Gateway | `http://noetl-gateway.gateway.svc.cluster.local:8090` |

## Ingress Configuration

Enable external access with GCE Ingress:

```bash
noetl run automation/iap/gcp/gke_autopilot.yaml \
  --set action=deploy \
  --set project_id=noetl-demo-19700101 \
  --set noetl_ingress_enabled=true \
  --set noetl_ingress_host=api.example.com \
  --set gateway_ingress_enabled=true \
  --set gateway_ingress_host=gateway.example.com
```

## Verifying the Deployment

### Check Pod Status

```bash
kubectl get pods -A | grep -E "postgres|nats|clickhouse|noetl|gateway"
```

### View Logs

```bash
# NoETL server logs
kubectl logs -n noetl -l app=noetl-server -f

# NoETL worker logs
kubectl logs -n noetl -l app=noetl-worker -f

# PostgreSQL logs
kubectl logs -n postgres -l app.kubernetes.io/instance=postgres -f
```

### Test NoETL API

```bash
# Health check
kubectl exec deploy/noetl-server -n noetl -- curl -s http://localhost:8082/api/health

# List registered credentials
kubectl exec deploy/noetl-server -n noetl -- curl -s http://localhost:8082/api/credentials

# Test database connectivity
kubectl exec deploy/noetl-server -n noetl -- curl -s -X POST http://localhost:8082/api/postgres/execute \
  -H "Content-Type: application/json" \
  -d '{"credential_name": "pg_demo", "query": "SELECT 1"}'
```

## Troubleshooting

### Common Issues

**Cluster creation fails:**
- Verify GCP APIs are enabled
- Check IAM permissions (roles/container.admin)
- Ensure sufficient quota in the region

**Pods stuck in Pending:**
- GKE Autopilot scales nodes on demand; wait a few minutes
- Check for resource quota issues: `kubectl describe pod <pod-name> -n <namespace>`

**exec format error (CrashLoopBackOff):**

This error indicates an architecture mismatch (ARM64 image on AMD64 cluster).

```bash
# Check if the error is architecture-related
kubectl logs -n noetl deploy/noetl-server 2>&1 | head -5

# If you see "exec format error", rebuild with correct platform:
docker build --platform linux/amd64 -t ${REGISTRY}/noetl:${TAG} \
  -f docker/noetl/pip/Dockerfile .
docker push ${REGISTRY}/noetl:${TAG}

# Update deployment to use new tag
kubectl set image deployment/noetl-server noetl=${REGISTRY}/noetl:${TAG} -n noetl
```

**Image pull errors (ImagePullBackOff):**
- Verify Artifact Registry repository exists
- Check image name and tag
- Ensure workload identity or service account has access
- Build and push images before deploying:
  ```bash
  # Check if images exist
  gcloud artifacts docker images list ${REGION}-docker.pkg.dev/${PROJECT_ID}/noetl

  # If empty, build and push images (see "Build and Push Images" section)
  ```

**NoETL server CrashLoopBackOff (relation does not exist):**

This indicates the PostgreSQL schema is not initialized.

```bash
# Check the logs
kubectl logs -n noetl deploy/noetl-server | grep -i "relation.*does not exist"

# Initialize schema manually
POSTGRES_POD=$(kubectl get pods -n postgres -l app.kubernetes.io/instance=postgres -o jsonpath='{.items[0].metadata.name}')

# Create schema
kubectl exec -n postgres $POSTGRES_POD -- /bin/sh -c \
  "PGPASSWORD=demo psql -U postgres -d noetl -c 'CREATE SCHEMA IF NOT EXISTS noetl'"

# Apply DDL
kubectl exec -i -n postgres $POSTGRES_POD -- /bin/sh -c \
  "PGPASSWORD=demo psql -U postgres -d noetl" < noetl/database/ddl/postgres/schema_ddl.sql

# Grant permissions
kubectl exec -n postgres $POSTGRES_POD -- /bin/sh -c \
  "PGPASSWORD=demo psql -U postgres -d noetl -c 'GRANT ALL ON SCHEMA noetl TO noetl; GRANT ALL ON ALL TABLES IN SCHEMA noetl TO noetl; GRANT ALL ON ALL SEQUENCES IN SCHEMA noetl TO noetl;'"

# Restart NoETL pods
kubectl rollout restart deployment/noetl-server -n noetl
```

**Playbook execution fails with credential error:**

If playbooks fail with PostgreSQL connection errors, the credentials may point to external IPs instead of in-cluster services.

```bash
# Delete and re-register the credential
kubectl exec deploy/noetl-server -n noetl -- curl -s -X DELETE http://localhost:8082/api/credentials/pg_demo

kubectl exec deploy/noetl-server -n noetl -- curl -s -X POST http://localhost:8082/api/credentials \
  -H "Content-Type: application/json" \
  -d '{
    "name": "pg_demo",
    "type": "postgres",
    "description": "In-cluster PostgreSQL connection",
    "tags": ["k8s", "postgres", "gke"],
    "data": {
      "host": "postgres.postgres.svc.cluster.local",
      "port": 5432,
      "user": "noetl",
      "password": "noetl",
      "database": "noetl"
    }
  }'
```

**ClickHouse CrashLoopBackOff (IPv6 error):**

If ClickHouse fails with `Listen [::]:9009 failed: Poco::Exception... DNS error: EAI: Address family for hostname not supported`, the issue is IPv6 not being supported on GKE Autopilot.

The deployment playbook uses IPv4 configuration (`0.0.0.0` instead of `::`). If you deployed with older manifests:

```bash
# Delete existing resources
kubectl delete statefulset clickhouse -n clickhouse
kubectl delete configmap clickhouse-config -n clickhouse

# Apply GKE-compatible manifest
kubectl apply -f ci/manifests/clickhouse/clickhouse-gke.yaml

# Verify pod starts correctly
kubectl get pods -n clickhouse -w
```

**ClickHouse stuck in Init:**
- GKE Autopilot needs to provision nodes; wait a few minutes
- Check events: `kubectl describe pod clickhouse-0 -n clickhouse`

## Database Schema

The deployment playbook automatically initializes the NoETL PostgreSQL schema. The schema includes:

| Table | Purpose |
|-------|---------|
| `noetl.resource` | Resource definitions |
| `noetl.catalog` | Playbook catalog |
| `noetl.event` | Execution events |
| `noetl.runtime` | Runtime state |
| `noetl.credential` | Encrypted credentials |
| `noetl.transient` | Temporary execution data |

Schema DDL location: `noetl/database/ddl/postgres/schema_ddl.sql`

## State Management

NoETL IAP tracks infrastructure state in DuckDB:

```bash
# Initialize state bucket
noetl run automation/iap/gcp/init_state_bucket.yaml \
  --set project_id=noetl-demo-19700101

# Sync state to GCS
noetl run automation/iap/gcp/state_sync.yaml \
  --set action=push \
  --set project_id=noetl-demo-19700101

# Inspect state
noetl run automation/iap/gcp/state_inspect.yaml \
  --set project_id=noetl-demo-19700101
```

## Cost Optimization

GKE Autopilot charges based on actual resource usage:

- **Development**: Use smaller storage sizes
- **Production**: Enable persistence and appropriate storage classes
- **Cleanup**: Destroy clusters when not in use

```bash
# Minimal development deployment
noetl run automation/iap/gcp/deploy_gke_stack.yaml \
  --set project_id=noetl-demo-19700101 \
  --set postgres_size=5Gi \
  --set clickhouse_size=5Gi \
  --set nats_jetstream_size=2Gi
```

## See Also

- [Command Reference](./command-reference.md)
- [Observability Services](../reference/observability_services.md)
- [Local Development Setup](../development/local_dev_setup.md)
