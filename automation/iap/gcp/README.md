# Infrastructure as Playbook (IaP) - GCP Provider

This directory contains NoETL playbooks for managing Google Cloud Platform infrastructure using the Infrastructure as Playbook (IaP) pattern.

## Overview

IaP allows you to manage cloud infrastructure using familiar NoETL playbook YAML syntax, similar to Terraform but with the flexibility of NoETL's workflow engine. All IaP playbooks run locally using the Rust interpreter.

## Prerequisites

1. **Google Cloud SDK** installed and configured:
   ```bash
   # Install gcloud CLI
   brew install google-cloud-sdk

   # Authenticate with Application Default Credentials
   gcloud auth application-default login
   ```

2. **NoETL CLI** installed:
   ```bash
   brew install noetl/tap/noetl
   ```

3. **DuckDB CLI** (optional, for state inspection):
   ```bash
   brew install duckdb
   ```

## CLI Usage

### Runtime Mode

All IaP playbooks run locally using the embedded Rust interpreter:

```bash
# Run with local runtime (default for IaP)
noetl iap apply iap/gcp/gke_autopilot.yaml --auto-approve --var project_id=my-project

# With verbose output
noetl iap apply iap/gcp/gke_autopilot.yaml --auto-approve --var project_id=my-project --verbose
```

### Context Management

Set up a context for GCP projects:

```bash
# Add GCP context
noetl context add gcp-dev
noetl context set-runtime local  # IaP always runs locally

# Use the context
noetl context use gcp-dev

# Check current context
noetl context current
```

### Variable Passing

Pass playbook variables with `--var key=value`:

```bash
# Single variable
noetl iap apply gke_autopilot.yaml --auto-approve --var project_id=my-project

# Multiple variables
noetl iap apply gke_autopilot.yaml \
  --auto-approve \
  --var project_id=mestumre-dev \
  --var cluster_name=noetl-test \
  --var region=us-central1 \
  --var action=create
```

## Quick Start

### Deploy Complete NoETL Stack to GKE

The fastest way to deploy the entire stack:

```bash
noetl run automation/iap/gcp/deploy_gke_stack.yaml \
  --set project_id=noetl-demo-19700101
```

This creates:
- GKE Autopilot cluster
- Artifact Registry repository
- **Builds and pushes all container images** (NoETL server, Gateway, Worker Pool)
- PostgreSQL (Bitnami Helm chart) with NoETL schema initialized
- NATS JetStream
- ClickHouse (IPv4-compatible for GKE Autopilot)
- NoETL server and workers
- NoETL Gateway
- In-cluster credentials automatically registered (pg_demo, pg_k8s, nats_k8s, clickhouse_k8s)

To skip image building (if images already exist):
```bash
noetl run automation/iap/gcp/deploy_gke_stack.yaml \
  --set project_id=noetl-demo-19700101 \
  --set build_images=false
```

### Initialize State Bucket

Create the GCS bucket for state storage:

```bash
noetl run automation/iap/gcp/init_state_bucket.yaml \
  --set project_id=noetl-demo-19700101
```

### Provision GKE Autopilot Cluster Only

```bash
noetl run automation/iap/gcp/gke_autopilot.yaml \
  --set action=create \
  --set project_id=noetl-demo-19700101 \
  --set cluster_name=noetl-cluster
```

### Build and Push Container Images

Images are built automatically by the deployment playbook. You can choose between:

**Option 1: Google Cloud Build (Recommended for ARM Mac)**

Cloud Build runs on native AMD64 machines, making Rust compilation fast (~5-10 minutes instead of ~2 hours):

```bash
noetl run automation/iap/gcp/deploy_gke_stack.yaml \
  --set project_id=noetl-demo-19700101 \
  --set use_cloud_build=true
```

**Option 2: Local Docker Build**

If you're on an AMD64 machine or have time to spare:

```bash
noetl run automation/iap/gcp/deploy_gke_stack.yaml \
  --set project_id=noetl-demo-19700101 \
  --set use_cloud_build=false
```

**Option 3: Skip Image Building**

If images already exist in the registry:

```bash
noetl run automation/iap/gcp/deploy_gke_stack.yaml \
  --set project_id=noetl-demo-19700101 \
  --set build_images=false
```

**Manual Build (if needed):**

```bash
# Configure Docker for Artifact Registry
gcloud auth configure-docker us-central1-docker.pkg.dev

# Set environment variables
export PROJECT_ID=noetl-demo-19700101
export REGION=us-central1
export REGISTRY=${REGION}-docker.pkg.dev/${PROJECT_ID}/noetl
export TAG=$(date +%Y%m%d%H%M%S)

# IMPORTANT: Use --platform linux/amd64 when building on ARM Mac (M1/M2/M3)
# GKE Autopilot runs AMD64 nodes

# Build and push NoETL server (Python - fast)
docker build --platform linux/amd64 -t ${REGISTRY}/noetl:${TAG} \
  -f docker/noetl/pip/Dockerfile --build-arg NOETL_VERSION=latest .
docker push ${REGISTRY}/noetl:${TAG}

# Build and push Gateway (Rust - use Cloud Build on ARM Mac)
gcloud builds submit --project $PROJECT_ID \
  --tag ${REGISTRY}/noetl-gateway:${TAG} \
  --timeout=3600 \
  --machine-type=e2-highcpu-32 \
  -f crates/gateway/Dockerfile .
```

### Deploy Stack to Existing Cluster

```bash
noetl run automation/iap/gcp/gke_autopilot.yaml \
  --set action=deploy \
  --set project_id=noetl-demo-19700101 \
  --set noetl_image_repository=us-central1-docker.pkg.dev/noetl-demo-19700101/noetl/noetl
```

### Check State

```bash
noetl run automation/iap/gcp/state_inspect.yaml \
  --set project_id=noetl-demo-19700101
```

### Destroy Resources

```bash
# Destroy entire stack
noetl run automation/iap/gcp/deploy_gke_stack.yaml \
  --set action=destroy \
  --set project_id=noetl-demo-19700101

# Or destroy cluster only
noetl run automation/iap/gcp/gke_autopilot.yaml \
  --set action=destroy \
  --set project_id=noetl-demo-19700101
```

## Directory Structure

```
iap/gcp/
├── README.md                    # This file
├── deploy_gke_stack.yaml        # Complete stack deployment (recommended)
├── gke_autopilot.yaml           # GKE Autopilot cluster management
├── artifact_registry.yaml       # Artifact Registry repository management
├── init_state_bucket.yaml       # Initialize GCS state bucket
├── state_inspect.yaml           # Inspect current state
├── state_sync.yaml              # Sync state to/from GCS
├── test_rhai.yaml               # Rhai scripting test
└── schema/                      # DuckDB schema definitions
    └── state_schema.sql        # State management schema
```

## Authentication

IaP uses GCP Application Default Credentials (ADC) for authentication. The NoETL CLI extracts the ADC token via Rhai scripting and injects it into HTTP requests.

### Rhai Token Resolution

IaP playbooks use embedded Rhai scripting for dynamic GCP token retrieval:

```yaml
# Rhai script block for token retrieval
- step: get_token
  tool:
    kind: rhai
    code: |
      let token = get_gcp_token();
      log("info", "Token retrieved successfully");
      #{ gcp_token: token }
  next:
    - step: use_token

- step: use_token
  tool:
    kind: http
    method: GET
    url: https://container.googleapis.com/v1/projects/{{ workload.project_id }}/locations
    headers:
      Authorization: "Bearer {{ get_token.gcp_token }}"
```

### Auth Configuration in Playbooks

```yaml
# Use ADC (default for GCP)
auth:
  source: adc

# Use service account key file
auth:
  source: service_account
  key_file: /path/to/service-account.json

# Use environment variable
auth:
  source: env
  var_name: GCP_ACCESS_TOKEN
```

## State Management

State is stored in DuckDB with the following key tables:

- **resources**: Current state of all managed resources
- **snapshots**: Point-in-time snapshots for versioning
- **operations**: Audit log of all operations
- **drift_records**: Detected drift between desired and actual state

### State File Location

By default, state is stored at:
- Local: `/tmp/noetl-iap-state.duckdb`
- Remote: `gs://{project}-noetl-state/terraform/{workspace}/state.duckdb`

## GCS Bucket Structure

```
gs://{project}-noetl-state/
├── terraform/                    # Terraform-like mutable state
│   ├── default/                  # Default workspace
│   │   ├── state.duckdb
│   │   ├── state.duckdb.lock
│   │   └── history/
│   │       ├── snapshot_20260118_120000.parquet
│   │       └── ...
│   └── production/               # Production workspace
│       └── ...
└── crossplane/                   # Crossplane-like reconciliation
    └── ...
```

## Example: GKE Autopilot Cluster

```yaml
# gke_autopilot.yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: gke_autopilot_cluster
  path: iap/gcp/gke-autopilot

# Executor section specifies local runtime
executor:
  profile: local
  version: noetl-runtime/1
  requires:
    features:
      - http
      - rhai

workload:
  project_id: mestumre-dev
  region: us-central1
  cluster_name: my-cluster
  action: create  # create, update, destroy

workflow:
  - step: start
    case:
      - when: "{{ workload.action }} == create"
        then:
          - step: get_token
      - when: "{{ workload.action }} == destroy"
        then:
          - step: delete_cluster
    next:
      - step: end

  - step: get_token
    tool:
      kind: rhai
      code: |
        let token = get_gcp_token();
        #{ gcp_token: token }
    next:
      - step: create_cluster

  - step: create_cluster
    tool:
      kind: http
      method: POST
      url: https://container.googleapis.com/v1/projects/{{ workload.project_id }}/locations/{{ workload.region }}/clusters
      headers:
        Authorization: "Bearer {{ get_token.gcp_token }}"
        Content-Type: application/json
      body: |
        {
          "cluster": {
            "name": "{{ workload.cluster_name }}",
            "autopilot": {"enabled": true}
          }
        }
    next:
      - step: save_state

  # ... more steps
```

Execute with:

```bash
noetl iap apply iap/gcp/gke_autopilot.yaml \
  --auto-approve \
  --var project_id=mestumre-dev \
  --var cluster_name=my-cluster \
  --var action=create \
  --verbose
```

## Supported Resources

| Resource Type | API/Method | Status |
|--------------|------------|--------|
| GKE Autopilot Cluster | container.googleapis.com | Implemented |
| Artifact Registry | artifactregistry.googleapis.com | Implemented |
| GCS Bucket | storage.googleapis.com | Implemented |
| PostgreSQL (Helm) | bitnami/postgresql | Implemented |
| NATS JetStream (Helm) | nats/nats | Implemented |
| ClickHouse | Kubernetes manifests | Implemented |
| NoETL (Helm) | automation/helm/noetl | Implemented |
| Gateway (Helm) | automation/helm/gateway | Implemented |

### Components Deployed

The `deploy_gke_stack.yaml` playbook deploys:

| Component | Namespace | Description |
|-----------|-----------|-------------|
| PostgreSQL | postgres | Primary database for NoETL |
| NATS JetStream | nats | Message queue for event-driven workflows |
| ClickHouse | clickhouse | Analytics database for observability |
| NoETL Server | noetl | FastAPI server for playbook orchestration |
| NoETL Worker | noetl | Python workers for step execution |
| Gateway | gateway | Rust-based API gateway |

## Troubleshooting

### exec format error (CrashLoopBackOff)

This indicates an architecture mismatch (ARM64 image on AMD64 cluster):

```bash
# Rebuild with correct platform
docker build --platform linux/amd64 -t ${REGISTRY}/noetl:${TAG} \
  -f docker/noetl/pip/Dockerfile .
docker push ${REGISTRY}/noetl:${TAG}

# Update deployment
kubectl set image deployment/noetl-server noetl=${REGISTRY}/noetl:${TAG} -n noetl
```

### PostgreSQL Schema Not Initialized

If NoETL server fails with "relation does not exist":

```bash
POSTGRES_POD=$(kubectl get pods -n postgres -l app.kubernetes.io/instance=postgres -o jsonpath='{.items[0].metadata.name}')

# Create schema and apply DDL
kubectl exec -n postgres $POSTGRES_POD -- /bin/sh -c \
  "PGPASSWORD=demo psql -U postgres -d noetl -c 'CREATE SCHEMA IF NOT EXISTS noetl'"
kubectl exec -i -n postgres $POSTGRES_POD -- /bin/sh -c \
  "PGPASSWORD=demo psql -U postgres -d noetl" < noetl/database/ddl/postgres/schema_ddl.sql
kubectl exec -n postgres $POSTGRES_POD -- /bin/sh -c \
  "PGPASSWORD=demo psql -U postgres -d noetl -c 'GRANT ALL ON SCHEMA noetl TO noetl; GRANT ALL ON ALL TABLES IN SCHEMA noetl TO noetl; GRANT ALL ON ALL SEQUENCES IN SCHEMA noetl TO noetl;'"

# Restart NoETL
kubectl rollout restart deployment/noetl-server -n noetl
```

### ClickHouse IPv6 Error

If ClickHouse fails with IPv6 errors on GKE Autopilot:

```bash
kubectl delete statefulset clickhouse -n clickhouse
kubectl delete configmap clickhouse-config -n clickhouse
kubectl apply -f ci/manifests/clickhouse/clickhouse-gke.yaml
```

### Authentication Errors

```bash
# Check if ADC is configured
gcloud auth application-default print-access-token

# Re-authenticate if needed
gcloud auth application-default login

# Run playbook with verbose output
noetl iap apply iap/gcp/gke_autopilot.yaml --auto-approve --var project_id=my-project --verbose
```

### State Errors

```bash
# Inspect local state
duckdb /tmp/noetl-iap-state.duckdb "SELECT * FROM resources"

# Reset local state
rm /tmp/noetl-iap-state.duckdb

# Inspect IaP state via CLI
noetl iap state list
noetl iap state show my-resource
```

### API Errors

Check GCP API is enabled:
```bash
gcloud services enable container.googleapis.com --project=mestumre-dev
gcloud services enable compute.googleapis.com --project=mestumre-dev
```

### Runtime Errors

If you encounter runtime errors:
```bash
# Verify local runtime is being used
noetl context current

# Force local runtime
noetl run iap/gcp/playbook.yaml -r local --set project_id=my-project -v

# Check CLI version
noetl --version
```

## IaP CLI Commands

Additional IaP-specific commands:

```bash
# Initialize IaP workspace
noetl iap init

# State management
noetl iap state list                    # List all resources
noetl iap state show <resource-id>      # Show resource details
noetl iap state query "SELECT * FROM resources WHERE type='gke'"

# Sync state
noetl iap sync push                     # Push local state to GCS
noetl iap sync pull                     # Pull state from GCS

# Workspace management
noetl iap workspace list                # List workspaces
noetl iap workspace use production      # Switch workspace
```

## Contributing

See the [IaP Development Plan](../../../documentation/docs/features/iap_development_plan.md) for implementation details and contribution guidelines.
