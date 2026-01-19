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

All IaP playbooks are designed for **local runtime** execution using the embedded Rust interpreter:

```bash
# Run with local runtime (default for IaP)
noetl run iap/gcp/gke_autopilot.yaml --set project_id=my-project

# Explicitly specify local runtime
noetl run iap/gcp/gke_autopilot.yaml -r local --set project_id=my-project

# With verbose output
noetl run iap/gcp/gke_autopilot.yaml -v --set project_id=my-project
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

Pass playbook variables with `--set key=value`:

```bash
# Single variable
noetl run gke_autopilot.yaml --set project_id=my-project

# Multiple variables
noetl run gke_autopilot.yaml \
  --set project_id=mestumre-dev \
  --set cluster_name=noetl-test \
  --set region=us-central1 \
  --set action=create
```

## Quick Start

### Initialize State Bucket

First, create the GCS bucket for state storage:

```bash
noetl run iap/gcp/init_state_bucket.yaml \
  --set project_id=mestumre-dev \
  --set bucket_name=mestumre-dev-noetl-state \
  --set region=us-central1
```

### Provision GKE Autopilot Cluster

```bash
noetl run iap/gcp/gke_autopilot.yaml \
  --set project_id=mestumre-dev \
  --set cluster_name=noetl-test-cluster \
  --set region=us-central1
```

### Check State

```bash
noetl run iap/gcp/state_inspect.yaml
```

### Destroy Resources

```bash
noetl run iap/gcp/gke_autopilot.yaml \
  --set action=destroy \
  --set project_id=mestumre-dev \
  --set cluster_name=noetl-test-cluster
```

## Directory Structure

```
iap/gcp/
├── README.md                    # This file
├── init_state_bucket.yaml       # Initialize GCS state bucket
├── gke_autopilot.yaml           # GKE Autopilot cluster management
├── state_inspect.yaml           # Inspect current state
├── state_sync.yaml              # Sync state to/from GCS
├── resources/                   # Reusable resource playbooks
│   ├── gke_autopilot.yaml      # GKE Autopilot resource
│   ├── vpc_network.yaml        # VPC network resource
│   └── service_account.yaml    # Service account resource
├── schema/                      # DuckDB schema definitions
│   └── state_schema.sql        # State management schema
└── tests/                       # Integration tests
    └── test_gke_lifecycle.yaml # GKE lifecycle test
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
noetl run iap/gcp/gke_autopilot.yaml \
  --set project_id=mestumre-dev \
  --set cluster_name=my-cluster \
  --set action=create \
  -v
```

## Supported Resources

| Resource Type | API | Status |
|--------------|-----|--------|
| GKE Autopilot Cluster | container.googleapis.com | Implemented |
| VPC Network | compute.googleapis.com | Planned |
| Firewall Rules | compute.googleapis.com | Planned |
| Service Account | iam.googleapis.com | Planned |
| Cloud SQL Instance | sqladmin.googleapis.com | Planned |
| GCS Bucket | storage.googleapis.com | Planned |

## Troubleshooting

### Authentication Errors

```bash
# Check if ADC is configured
gcloud auth application-default print-access-token

# Re-authenticate if needed
gcloud auth application-default login

# Run playbook with verbose output
noetl run iap/gcp/gke_autopilot.yaml --set project_id=my-project -v
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
