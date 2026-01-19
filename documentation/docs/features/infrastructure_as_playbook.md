---
sidebar_position: 20
title: Infrastructure as Playbook (IaP)
description: Manage cloud infrastructure using NoETL playbooks - a Terraform/Crossplane alternative
---

# Infrastructure as Playbook (IaP)

Infrastructure as Playbook (IaP) is NoETL's approach to cloud infrastructure management, combining the declarative nature of Terraform with the Kubernetes-native reconciliation patterns of Crossplane, all within the familiar NoETL playbook DSL.

## Overview

IaP enables you to:

- **Provision cloud resources** using NoETL playbooks with direct cloud API calls
- **Track infrastructure state** in DuckDB with full snapshot history
- **Sync state to cloud storage** (GCS/S3) for durability and collaboration
- **Reconcile drift** like Git - compare snapshots, detect conflicts, apply sync
- **Bootstrap from scratch** - only a Google account is required as a prerequisite

## Quick Start

```bash
# Initialize IaP state
noetl iap init --project my-gcp-project --bucket my-state-bucket --workspace dev

# Create a GKE cluster
noetl run automation/iap/gcp/gke_autopilot.yaml --set action=create -v

# View managed resources
noetl iap state list

# Sync state to GCS
noetl iap sync push

# Destroy the cluster
noetl run automation/iap/gcp/gke_autopilot.yaml --set action=destroy -v
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Infrastructure as Playbook                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌───────────────┐    ┌──────────────────┐    ┌────────────────────────┐   │
│  │   noetl CLI   │───▶│  Local Playbook  │───▶│   Cloud APIs (GCP)     │   │
│  │  (Rust-based) │    │    Execution     │    │   - GKE, Compute, IAM  │   │
│  └───────────────┘    └──────────────────┘    └────────────────────────┘   │
│         │                      │                         │                  │
│         │                      │                         │                  │
│         ▼                      ▼                         ▼                  │
│  ┌───────────────┐    ┌──────────────────┐    ┌────────────────────────┐   │
│  │  GCP OAuth    │    │     DuckDB       │    │    GCS Bucket          │   │
│  │  (ADC Token)  │    │  State Storage   │    │  (State Persistence)   │   │
│  └───────────────┘    └──────────────────┘    └────────────────────────┘   │
│                                │                         ▲                  │
│                                │    ┌────────────────────┘                  │
│                                ▼    ▼                                       │
│                       ┌──────────────────┐                                  │
│                       │  State Sync &    │                                  │
│                       │  Reconciliation  │                                  │
│                       └──────────────────┘                                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Key Concepts

### 1. State Management

IaP uses DuckDB as the local state engine with a structured schema:

- **Snapshots**: Point-in-time captures of cloud resource state
- **Current State**: Latest known state of each resource
- **Desired State**: Target configuration from playbook definitions
- **Drift Detection**: Comparison between current and desired states

### 2. Authentication Model

For bootstrap scenarios (no existing infrastructure), IaP leverages:

- **GCP Application Default Credentials (ADC)**: Uses `gcloud auth application-default login` token
- **OAuth Token Injection**: The Rust CLI extracts ADC tokens and injects them into playbook context
- **Credential-Free Bootstrap**: No secrets management required for initial provisioning

### 3. Git-Like Workflow

```bash
# Initialize new infrastructure project
noetl iap init --project my-gcp-project --bucket my-state-bucket --workspace dev-alice

# Execute infrastructure playbooks
noetl run automation/iap/gcp/gke_autopilot.yaml --set action=create -v

# View managed resources
noetl iap state list
noetl iap state list --resource-type gke_cluster --format json
noetl iap state show my-cluster

# Execute raw SQL against state database
noetl iap state query "SELECT * FROM resources WHERE status = 'running'"

# Remove resource from state (does not destroy actual resource)
noetl iap state rm my-old-cluster --force

# Sync state to/from GCS
noetl iap sync push
noetl iap sync pull
noetl iap sync status

# Detect and report drift
noetl iap drift detect --resource-type gke_cluster
noetl iap drift report --format json
```

### 4. Workspace Management

Workspaces provide isolation for different environments or developers working on the same infrastructure:

```bash
# Show current workspace
noetl iap workspace current

# List all registered workspaces
noetl iap workspace list

# Include remote workspaces from GCS
noetl iap workspace list --remote

# Create a new workspace (inherits config from current)
noetl iap workspace create dev-bob

# Create workspace cloned from another
noetl iap workspace create staging --from dev-alice

# Switch to a different workspace
noetl iap workspace switch staging

# Switch and pull latest state
noetl iap workspace switch production --pull

# Delete a workspace from registry
noetl iap workspace delete dev-old --force

# Delete workspace and remote state
noetl iap workspace delete dev-old --remote --force
```

**Multi-Developer Workflow:**

```bash
# Developer Alice sets up her workspace
noetl iap init --project team-project --bucket team-state --workspace dev-alice
noetl run automation/iap/gcp/gke_autopilot.yaml --set action=create -v
noetl iap sync push

# Developer Bob creates his workspace from Alice's config
noetl iap workspace create dev-bob --from dev-alice --switch

# Shared environments use dedicated workspaces
noetl iap workspace create staging --switch
noetl run automation/iap/gcp/gke_autopilot.yaml --set action=create -v
noetl iap sync push

# Team members can pull shared state
noetl iap workspace switch staging --pull
```

**Workspace Registry Structure (`.noetl/workspaces.json`):**

```json
{
  "dev-alice": {
    "name": "dev-alice",
    "project": "team-project",
    "region": "us-central1",
    "bucket": "team-state",
    "state_path_template": "workspaces/{workspace}/state.duckdb",
    "remote_path": "gs://team-state/workspaces/dev-alice/state.duckdb",
    "created_at": "2026-01-19T03:12:22.762842+00:00",
    "last_used": "2026-01-19T03:12:22.762854+00:00"
  }
}
```

### 5. GCS Bucket Structure

State files are organized in GCS following a structure that supports both imperative (apply-once) and declarative (continuous reconciliation) patterns:

```
gs://{project}-noetl-state/
├── workspaces/                   # Workspace-scoped state (imperative execution)
│   ├── {workspace}/
│   │   ├── state.duckdb         # Current state database
│   │   ├── state.duckdb.lock    # Lock file for concurrency
│   │   └── history/
│   │       ├── snapshot_{timestamp}.parquet
│   │       └── ...
│   └── default/
│       └── state.duckdb
│
├── managed/                      # Managed resources (declarative reconciliation)
│   ├── {cluster}/{namespace}/
│   │   ├── resources/
│   │   │   ├── {resource_kind}_{name}.yaml
│   │   │   └── ...
│   │   └── status/
│   │       └── {resource_kind}_{name}.status.json
│   └── global/
│       └── provider_configs/
│
└── shared/                       # Shared resources
    ├── playbooks/                # Reusable playbook modules
    └── policies/                 # Policy definitions
```

## Playbook Structure for IaP

IaP playbooks use local runtime with the `executor` section and Rhai scripting for complex operations like polling:

### Resource Definition

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: gke_autopilot_cluster
  path: iap/gcp/gke-autopilot
  labels:
    iap.noetl.io/provider: gcp
    iap.noetl.io/resource-type: container.googleapis.com/Cluster

executor:
  profile: local           # IaP uses local runtime
  version: noetl-runtime/1

workload:
  # Action: create or destroy
  action: create
  
  # Project configuration
  project_id: mestumre-dev
  region: us-central1
  
  # Cluster configuration
  cluster_name: noetl-test-cluster
  network: default
  subnetwork: default

workflow:
  - step: start
    desc: Route based on action
    case:
      - when: "{{ workload.action == 'create' }}"
        then:
          - step: create_cluster
      - when: "{{ workload.action == 'destroy' }}"
        then:
          - step: destroy_cluster
    next:
      - step: end
      - step: fetch_state

  - step: fetch_state
    desc: Pull current state from GCS
    tool:
      kind: http
      method: GET
      url: https://storage.googleapis.com/{{ workload.state_bucket }}/terraform/{{ workload.workspace }}/state.duckdb
      auth:
        source: adc  # Application Default Credentials
    sink:
      file: /tmp/state.duckdb
    next:
      - step: get_snapshot

  - step: get_snapshot
    desc: Capture current cloud state
    tool:
      kind: http
      method: GET
      url: https://container.googleapis.com/v1/projects/{{ workload.project_id }}/locations/{{ workload.region }}/clusters/{{ workload.cluster_name }}
      auth:
        source: adc
    vars:
      current_cluster: "{{ result }}"
    next:
      - step: compare_state

  - step: compare_state
    desc: Compare current vs desired state
    tool:
      kind: duckdb
      commands: |
        -- Load current state
        CREATE TABLE IF NOT EXISTS current_state AS
        SELECT * FROM read_json_auto('/dev/stdin');
        
        -- Compare with desired
        SELECT 
          CASE 
            WHEN current_state.status = 'RUNNING' AND desired.autopilot = TRUE 
            THEN 'no_change'
            ELSE 'update_required'
          END as action
        FROM current_state, desired_state;
    next:
      - case:
          - when: "{{ compare_state.action }} == no_change"
            then:
              - step: end
          - when: "{{ compare_state.action }} == update_required"
            then:
              - step: apply_changes

  - step: apply_changes
    desc: Apply infrastructure changes
    tool:
      kind: http
      method: PATCH
      url: https://container.googleapis.com/v1/projects/{{ workload.project_id }}/locations/{{ workload.region }}/clusters/{{ workload.cluster_name }}
      auth:
        source: adc
      body: |
        {
          "autopilot": {
            "enabled": true
          }
        }
    next:
      - step: save_state

  - step: save_state
    desc: Persist state to DuckDB and sync to GCS
    tool:
      kind: duckdb
      commands: |
        INSERT INTO snapshots (timestamp, resource_type, resource_id, state)
        VALUES (NOW(), 'gke_cluster', '{{ workload.cluster_name }}', '{{ apply_changes.result }}');
    sink:
      tool:
        kind: gcs
        destination: gs://{{ workload.state_bucket }}/terraform/{{ workload.workspace }}/state.duckdb
    next:
      - step: end

  - step: end
    desc: Execution complete
```

## CLI Enhancements Required

The NoETL Rust CLI needs the following enhancements:

### 1. Authentication Handler

```rust
// New auth module in playbook_runner.rs
enum AuthSource {
    ADC,                    // GCP Application Default Credentials
    ServiceAccount(String), // Service account key path
    OAuth(OAuthConfig),     // OAuth2 configuration
    EnvVar(String),         // Environment variable
}

struct AuthHandler {
    source: AuthSource,
    token_cache: Option<String>,
    expires_at: Option<DateTime<Utc>>,
}

impl AuthHandler {
    fn get_bearer_token(&mut self) -> Result<String> {
        match &self.source {
            AuthSource::ADC => self.get_adc_token(),
            AuthSource::ServiceAccount(path) => self.get_sa_token(path),
            _ => unimplemented!()
        }
    }
    
    fn get_adc_token(&self) -> Result<String> {
        // Execute: gcloud auth application-default print-access-token
        let output = Command::new("gcloud")
            .args(["auth", "application-default", "print-access-token"])
            .output()?;
        Ok(String::from_utf8(output.stdout)?.trim().to_string())
    }
}
```

### 2. HTTP Tool Enhancement

```rust
Tool::Http {
    method,
    url,
    headers,
    auth,      // NEW: auth configuration
    body,
} => {
    // Resolve auth and inject Bearer token
    if let Some(auth_config) = auth {
        let token = auth_handler.get_bearer_token()?;
        headers.insert("Authorization", format!("Bearer {}", token));
    }
    // ... existing HTTP execution
}
```

### 3. DuckDB Tool Handler

```rust
Tool::DuckDB {
    database,   // Path to .duckdb file
    commands,   // SQL commands to execute
} => {
    // Use embedded DuckDB or shell out to duckdb CLI
    let db_path = database.unwrap_or(":memory:".to_string());
    let rendered_commands = self.render_template(commands, context)?;
    
    let output = Command::new("duckdb")
        .args([&db_path, "-c", &rendered_commands])
        .output()?;
    
    Ok(Some(String::from_utf8_lossy(&output.stdout).to_string()))
}
```

### 4. Sink Handler

```rust
#[derive(Debug, Deserialize)]
struct Sink {
    tool: SinkTool,
}

#[derive(Debug, Deserialize)]
#[serde(tag = "kind")]
enum SinkTool {
    #[serde(rename = "gcs")]
    GCS { destination: String },
    #[serde(rename = "file")]
    File { path: String },
    #[serde(rename = "duckdb")]
    DuckDB { table: String },
}
```

## Implementation Phases

### Phase 1: Foundation (Week 1-2)
- Enhance NoETL CLI with auth handler (ADC support)
- Add DuckDB tool to local playbook runner
- Implement basic sink functionality

### Phase 2: State Management (Week 3-4)
- Define DuckDB schema for state tracking
- Implement snapshot creation and comparison
- Add GCS sync capabilities

### Phase 3: GCP Provider (Week 5-6)
- Create GKE Autopilot provisioning playbooks
- Add support for common GCP resources
- Implement drift detection

### Phase 4: CLI Commands (Week 7-8)
- Add `noetl iap init/plan/apply/sync` commands
- Implement conflict resolution UI
- Add state inspection commands

## Comparison with Alternatives

| Feature | Terraform | Crossplane | NoETL IaP |
|---------|-----------|------------|-----------|
| State Storage | S3/GCS (tfstate) | etcd (in-cluster) | DuckDB + GCS |
| Execution | CLI or Cloud | Kubernetes Controller | CLI or Distributed |
| Language | HCL | YAML (CRDs) | YAML (Playbooks) |
| Drift Detection | Plan command | Continuous | On-demand or Scheduled |
| Dependencies | Provider plugins | Providers (containers) | HTTP + Python + DuckDB |
| Learning Curve | Moderate | High (K8s required) | Low (familiar YAML) |

## Getting Started

### Prerequisites

1. Google Cloud account with project access
2. `gcloud` CLI installed and authenticated:
   ```bash
   gcloud auth application-default login
   ```
3. NoETL CLI installed:
   ```bash
   brew install noetl/tap/noetl
   ```

### Quick Start

```bash
# Clone the IaP examples
cd automation/iap/gcp

# Initialize IaP for your GCP project with a workspace
noetl iap init --project my-gcp-project --bucket my-state-bucket --workspace my-cluster

# Check current workspace
noetl iap workspace current

# Create GKE Autopilot cluster using local runtime
noetl run gke_autopilot.yaml --set action=create -v

# View managed resources
noetl iap state list

# Query state database directly
noetl iap state query "SELECT * FROM iap_config"

# Sync state to GCS for team collaboration
noetl iap sync push

# Pull state from GCS (e.g., on another machine)
noetl iap sync pull

# Destroy the cluster
noetl run gke_autopilot.yaml --set action=destroy -v

# Create a workspace for another developer
noetl iap workspace create dev-bob --switch

# List all workspaces
noetl iap workspace list
```

### Rhai Scripting for Polling

IaP playbooks use Rhai embedded scripting for operations that require polling (like waiting for a GKE cluster to become ready):

```yaml
- step: wait_for_cluster
  desc: Poll GKE cluster status until RUNNING
  tool:
    kind: rhai
    code: |
      // Get GCP authentication token
      let token = get_gcp_token();
      
      // Build API URL
      let url = "https://container.googleapis.com/v1/projects/" 
        + project_id + "/locations/" + region + "/clusters/" + cluster_name;
      
      // Poll until cluster is running
      let max_attempts = 60;
      let attempt = 0;
      let status = "";
      
      while attempt < max_attempts {
        attempt += 1;
        log("Poll attempt " + attempt + "/" + max_attempts);
        
        // Make authenticated HTTP request
        let response = http_get_auth(url, token);
        let data = parse_json(response);
        
        status = data["status"];
        log("Cluster status: " + status);
        
        if status == "RUNNING" {
          break;
        }
        
        // Wait 10 seconds before next poll
        sleep(10000);
      }
      
      // Return result
      #{
        "status": status,
        "attempts": attempt,
        "endpoint": if status == "RUNNING" { data["endpoint"] } else { "" }
      }
```

**Rhai Built-in Functions**:
- `http_get_auth(url, token)`: Make authenticated GET request
- `http_post_auth(url, body, token)`: Make authenticated POST request
- `http_delete_auth(url, token)`: Make authenticated DELETE request
- `get_gcp_token()`: Get GCP Application Default Credentials token
- `parse_json(string)`: Parse JSON string to object
- `sleep(ms)`: Sleep for milliseconds
- `log(message)`: Print log message

## Security Considerations

- **Token Handling**: ADC tokens are short-lived and never persisted
- **State Encryption**: DuckDB files can be encrypted at rest
- **GCS Access**: State bucket should have restricted IAM policies
- **Audit Trail**: All state changes are recorded with timestamps

## Future Enhancements

1. **Multi-Provider Support**: AWS, Azure providers
2. **Policy Engine**: OPA integration for resource validation
3. **Cost Estimation**: Integrate with cloud pricing APIs
4. **Terraform Import**: Convert existing tfstate to IaP format
5. **Visual State Explorer**: UI for browsing infrastructure state
