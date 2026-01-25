# NoETL Rust Worker Pool

The Rust Worker Pool is a high-performance worker implementation that executes workflow commands received from the NoETL control plane via NATS messaging.

## Overview

### Architecture

```
┌─────────────────┐     ┌─────────────┐     ┌──────────────────┐
│  NoETL Server   │────▶│    NATS     │────▶│  Rust Worker     │
│  (Control Plane)│     │  JetStream  │     │  Pool            │
└─────────────────┘     └─────────────┘     └──────────────────┘
        │                                            │
        │◀───────── HTTP Events/Heartbeats ─────────│
        └────────────────────────────────────────────┘
```

### Components

| Component | Description |
|-----------|-------------|
| `noetl-tools` | Shared tool library with implementations for shell, HTTP, Rhai, DuckDB, PostgreSQL, Python, Snowflake, Transfer, and Script tools |
| `worker-pool` | Worker binary that subscribes to NATS and executes commands |

### Supported Tools

| Tool | Description |
|------|-------------|
| `shell` | Execute shell commands |
| `http` | Make HTTP requests with authentication |
| `rhai` | Execute Rhai scripts |
| `duckdb` | Query DuckDB databases |
| `postgres` | Query PostgreSQL databases |
| `python` | Execute Python scripts |
| `snowflake` | Execute Snowflake SQL queries |
| `transfer` | Transfer data between databases |
| `script` | Execute scripts as Kubernetes jobs |

---

## Local Development

### Prerequisites

- Rust 1.75+ (install via [rustup](https://rustup.rs/))
- Docker (for containerized dependencies)
- NATS Server (for message queue)

### Building from Source

```bash
# Clone the repository
git clone https://github.com/noetl/noetl.git
cd noetl

# Build in debug mode
cargo build -p worker-pool

# Build in release mode (optimized)
cargo build --release -p worker-pool

# Run tests
cargo test -p noetl-tools
cargo test -p worker-pool
```

### Running Locally

#### 1. Start Dependencies

```bash
# Start NATS with JetStream
docker run -d --name nats \
  -p 4222:4222 \
  -p 8222:8222 \
  nats:latest -js

# Start PostgreSQL (optional, for postgres tool)
docker run -d --name postgres \
  -e POSTGRES_PASSWORD=demo \
  -e POSTGRES_USER=noetl \
  -e POSTGRES_DB=noetl \
  -p 5432:5432 \
  postgres:15
```

#### 2. Configure Environment

Create a `.env` file:

```bash
# Worker Configuration
WORKER_ID=local-worker-1
WORKER_POOL_NAME=local-pool
NOETL_SERVER_URL=http://localhost:8082
NATS_URL=nats://localhost:4222
NATS_STREAM=NOETL_COMMANDS
NATS_CONSUMER=worker-pool
WORKER_HEARTBEAT_INTERVAL=15
WORKER_MAX_CONCURRENT=4

# Logging
RUST_LOG=info,worker_pool=debug,noetl_tools=debug
```

#### 3. Run the Worker

```bash
# Using cargo
cargo run -p worker-pool

# Or run the release binary directly
./target/release/noetl-worker
```

### Development Workflow

```bash
# Watch for changes and rebuild
cargo watch -x 'build -p worker-pool'

# Run with specific log level
RUST_LOG=debug cargo run -p worker-pool

# Run clippy for linting
cargo clippy -p noetl-tools -p worker-pool

# Format code
cargo fmt --all
```

---

## Kind Cluster Deployment

### Prerequisites

- [kind](https://kind.sigs.k8s.io/) installed
- [kubectl](https://kubernetes.io/docs/tasks/tools/) configured
- [helm](https://helm.sh/docs/intro/install/) v3+
- Docker running

### Setup Kind Cluster

```bash
# Create kind cluster with ingress support
cat <<EOF | kind create cluster --config=-
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  kubeadmConfigPatches:
  - |
    kind: InitConfiguration
    nodeRegistration:
      kubeletExtraArgs:
        node-labels: "ingress-ready=true"
  extraPortMappings:
  - containerPort: 80
    hostPort: 80
    protocol: TCP
  - containerPort: 443
    hostPort: 443
    protocol: TCP
- role: worker
- role: worker
EOF

# Verify cluster
kubectl cluster-info
```

### Build and Load Images

```bash
# Build the worker-pool image
docker build -f crates/worker-pool/Dockerfile -t noetl-worker-pool:latest .

# Load into kind cluster
kind load docker-image noetl-worker-pool:latest

# Build and load NoETL server image (if needed)
docker build -f docker/noetl/pip/Dockerfile -t noetl:latest .
kind load docker-image noetl:latest
```

### Deploy Infrastructure

```bash
# Deploy NATS
helm repo add nats https://nats-io.github.io/k8s/helm/charts/
helm install nats nats/nats \
  --namespace nats \
  --create-namespace \
  --set nats.jetstream.enabled=true

# Deploy PostgreSQL
helm repo add bitnami https://charts.bitnami.com/bitnami
helm install postgres bitnami/postgresql \
  --namespace postgres \
  --create-namespace \
  --set auth.postgresPassword=demo \
  --set auth.database=noetl
```

### Deploy NoETL Stack

#### Using Helm Directly

```bash
# Deploy with local images
helm upgrade --install noetl automation/helm/noetl \
  --namespace noetl \
  --create-namespace \
  --set image.repository=noetl \
  --set image.tag=latest \
  --set image.pullPolicy=Never \
  --set workerPool.enabled=true \
  --set workerPool.image.repository=noetl-worker-pool \
  --set workerPool.image.tag=latest \
  --set workerPool.image.pullPolicy=Never
```

#### Using Playbook

```bash
# Deploy full stack
noetl run automation/deployment/noetl-stack.yaml \
  --set action=deploy \
  --set registry='' \
  --set namespace=noetl
```

### Verify Deployment

```bash
# Check pods
kubectl get pods -n noetl

# Check logs
kubectl logs -n noetl -l app=noetl-worker-pool --tail=50

# Port forward to access server
kubectl port-forward -n noetl svc/noetl 8082:8082
```

### Cleanup

```bash
# Remove NoETL
helm uninstall noetl -n noetl

# Delete kind cluster
kind delete cluster
```

---

## GKE (Google Kubernetes Engine) Deployment

### Prerequisites

- Google Cloud account with billing enabled
- [gcloud CLI](https://cloud.google.com/sdk/docs/install) installed and configured
- GKE cluster created
- Artifact Registry repository for images

### Setup GCP Resources

```bash
# Set project
export PROJECT_ID=your-project-id
export REGION=us-central1
export CLUSTER_NAME=noetl-cluster

gcloud config set project $PROJECT_ID

# Create Artifact Registry repository
gcloud artifacts repositories create noetl \
  --repository-format=docker \
  --location=$REGION \
  --description="NoETL container images"

# Configure Docker authentication
gcloud auth configure-docker ${REGION}-docker.pkg.dev

# Create GKE Autopilot cluster (recommended)
gcloud container clusters create-auto $CLUSTER_NAME \
  --region=$REGION \
  --project=$PROJECT_ID

# Or create Standard cluster
gcloud container clusters create $CLUSTER_NAME \
  --region=$REGION \
  --num-nodes=3 \
  --machine-type=e2-standard-4 \
  --enable-autoscaling \
  --min-nodes=1 \
  --max-nodes=10
```

### Build and Push Images

```bash
# Set registry
export REGISTRY=${REGION}-docker.pkg.dev/${PROJECT_ID}/noetl

# Build worker-pool
docker build -f crates/worker-pool/Dockerfile \
  -t ${REGISTRY}/noetl-worker-pool:latest \
  -t ${REGISTRY}/noetl-worker-pool:$(git rev-parse --short HEAD) \
  .

# Push to Artifact Registry
docker push ${REGISTRY}/noetl-worker-pool:latest
docker push ${REGISTRY}/noetl-worker-pool:$(git rev-parse --short HEAD)

# Build and push NoETL server
docker build -f docker/noetl/pip/Dockerfile \
  -t ${REGISTRY}/noetl:latest \
  .
docker push ${REGISTRY}/noetl:latest
```

#### Using Playbook for Build/Push

```bash
noetl run automation/deployment/worker-pool.yaml \
  --set action=all \
  --set registry=${REGISTRY}
```

### Deploy to GKE

#### Configure kubectl

```bash
gcloud container clusters get-credentials $CLUSTER_NAME \
  --region=$REGION \
  --project=$PROJECT_ID
```

#### Deploy Infrastructure

```bash
# Deploy NATS with JetStream
helm repo add nats https://nats-io.github.io/k8s/helm/charts/
helm install nats nats/nats \
  --namespace nats \
  --create-namespace \
  --set nats.jetstream.enabled=true \
  --set nats.jetstream.fileStore.pvc.size=10Gi

# Deploy Cloud SQL Proxy or managed PostgreSQL
# Option 1: Cloud SQL with proxy
# Option 2: Self-managed PostgreSQL
helm install postgres bitnami/postgresql \
  --namespace postgres \
  --create-namespace \
  --set auth.postgresPassword=your-secure-password \
  --set auth.database=noetl \
  --set primary.persistence.size=50Gi \
  --set primary.resources.requests.memory=1Gi \
  --set primary.resources.requests.cpu=500m
```

#### Deploy NoETL Stack

```bash
# Create values override file
cat > gke-values.yaml <<EOF
namespace: noetl

image:
  repository: ${REGISTRY}/noetl
  tag: latest
  pullPolicy: Always

workerPool:
  enabled: true
  poolName: worker-rust-pool
  replicas: 3
  image:
    repository: ${REGISTRY}/noetl-worker-pool
    tag: latest
    pullPolicy: Always
  resources:
    requests:
      cpu: "250m"
      memory: "512Mi"
    limits:
      cpu: "2"
      memory: "2Gi"

worker:
  replicas: 2
  resources:
    requests:
      cpu: "250m"
      memory: "512Mi"
    limits:
      cpu: "1"
      memory: "1Gi"

persistence:
  data:
    enabled: true
    storageClassName: standard-rwx
    size: 50Gi
  logs:
    enabled: true
    storageClassName: standard
    size: 20Gi

ingress:
  enabled: true
  className: gce
  host: noetl.your-domain.com
  tls:
    enabled: true
  managedCertificate:
    enabled: true
    name: noetl-cert

config:
  workerPool:
    RUST_LOG: "info,worker_pool=info,noetl_tools=info"
    WORKER_POOL_NAME: "gke-rust-pool"
    WORKER_MAX_CONCURRENT: "8"
EOF

# Deploy
helm upgrade --install noetl automation/helm/noetl \
  --namespace noetl \
  --create-namespace \
  -f gke-values.yaml \
  --wait \
  --timeout 10m
```

#### Using Playbook

```bash
noetl run automation/deployment/noetl-stack.yaml \
  --set action=deploy \
  --set registry=${REGISTRY} \
  --set namespace=noetl
```

### Production Considerations

#### Resource Sizing

| Component | CPU Request | Memory Request | CPU Limit | Memory Limit |
|-----------|-------------|----------------|-----------|--------------|
| Server | 500m | 1Gi | 2 | 4Gi |
| Python Worker | 250m | 512Mi | 1 | 2Gi |
| Rust Worker Pool | 250m | 512Mi | 2 | 2Gi |

#### Autoscaling

```yaml
# Add HPA for worker-pool
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: noetl-worker-pool-hpa
  namespace: noetl
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: noetl-worker-pool
  minReplicas: 2
  maxReplicas: 20
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

#### Monitoring

```bash
# Deploy Prometheus/Grafana for monitoring
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace
```

### Troubleshooting

#### Check Pod Status

```bash
kubectl get pods -n noetl -o wide
kubectl describe pod -n noetl <pod-name>
```

#### View Logs

```bash
# Worker pool logs
kubectl logs -n noetl -l app=noetl-worker-pool --tail=100 -f

# All components
kubectl logs -n noetl -l app=noetl-server --tail=50
kubectl logs -n noetl -l app=noetl-worker --tail=50
```

#### Debug Connectivity

```bash
# Test NATS connection
kubectl run nats-test --rm -it --restart=Never \
  --image=natsio/nats-box:latest \
  -- nats sub -s nats://nats.nats.svc.cluster.local:4222 ">"

# Test server connectivity
kubectl run curl-test --rm -it --restart=Never \
  --image=curlimages/curl:latest \
  -- curl -v http://noetl.noetl.svc.cluster.local:8082/api/health
```

#### Common Issues

| Issue | Solution |
|-------|----------|
| Pod stuck in Pending | Check resource quotas, node capacity |
| CrashLoopBackOff | Check logs, verify NATS/server connectivity |
| ImagePullBackOff | Verify registry credentials, image exists |
| Connection refused | Check service endpoints, network policies |

---

## Configuration Reference

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `WORKER_ID` | Unique worker identifier | Auto-generated UUID |
| `WORKER_POOL_NAME` | Pool name for grouping workers | `default` |
| `NOETL_SERVER_URL` | Control plane server URL | `http://localhost:8082` |
| `NATS_URL` | NATS server connection URL | `nats://localhost:4222` |
| `NATS_STREAM` | JetStream stream name | `noetl_commands` |
| `NATS_CONSUMER` | Consumer name | `worker-pool` |
| `WORKER_HEARTBEAT_INTERVAL` | Heartbeat interval (seconds) | `15` |
| `WORKER_MAX_CONCURRENT` | Max concurrent tasks | `4` |
| `RUST_LOG` | Log level configuration | `info` |

### Helm Values

See [values.yaml](../../../automation/helm/noetl/values.yaml) for complete configuration options.

---

## API Reference

### Health Check

The worker pool exposes health information via the control plane API:

```bash
curl http://noetl-server:8082/api/workers
```

### Supported Tool Configurations

See individual tool documentation:
- [Shell Tool](./tools/shell)
- [HTTP Tool](./tools/http)
- [PostgreSQL Tool](./tools/postgres)
- [DuckDB Tool](./tools/duckdb)
- [Snowflake Tool](./tools/snowflake.md)
- [Transfer Tool](./tools/transfer.md)
- [Script Tool](./tools/script.md)
