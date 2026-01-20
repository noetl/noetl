---
sidebar_position: 21
title: IaP Development Plan
description: Detailed development plan for Infrastructure as Playbook implementation
---

# Infrastructure as Playbook (IaP) - Development Plan

This document outlines the complete development plan for implementing Infrastructure as Playbook (IaP) functionality in NoETL.

## Executive Summary

IaP transforms NoETL into a cloud infrastructure management tool by enhancing the Rust CLI (`noetlctl`) to support:
- GCP authentication via Application Default Credentials (ADC)
- HTTP calls to cloud provider APIs with automatic token injection
- DuckDB integration for state management
- GCS synchronization for state persistence
- Conditional logic for drift detection and reconciliation

## Current State Analysis

### Existing Capabilities

| Component | Current State | IaP Requirement |
|-----------|--------------|-----------------|
| `noetlctl` CLI | Shell, HTTP (curl), Playbook tools | Add auth, DuckDB, sink handlers |
| Authentication | None in local mode | ADC token extraction, Bearer injection |
| State Management | None | DuckDB with snapshot schema |
| Cloud Storage | None in local mode | GCS read/write via HTTP + auth |
| Conditional Logic | Basic `case/when/then` | Enhanced with `else` support |

### Files to Modify

```
crates/noetlctl/
├── src/
│   ├── main.rs              # Add IaP subcommands, tool enum extensions
│   ├── playbook_runner.rs   # Add DuckDB, auth, sink handlers
│   ├── config.rs            # Auth configuration
│   ├── auth/                 # NEW: Authentication module
│   │   ├── mod.rs
│   │   ├── gcp.rs           # GCP ADC implementation
│   │   └── token.rs         # Token caching
│   ├── tools/               # NEW: Tool implementations
│   │   ├── mod.rs
│   │   ├── duckdb.rs        # DuckDB handler
│   │   └── sink.rs          # Sink handler
│   └── iap/                  # NEW: IaP specific commands
│       ├── mod.rs
│       ├── init.rs
│       ├── plan.rs
│       ├── apply.rs
│       └── sync.rs
└── Cargo.toml               # Add dependencies
```

## Phase 1: Authentication Foundation (Week 1-2)

### 1.1 GCP ADC Token Handler

**File: `crates/noetlctl/src/auth/gcp.rs`**

```rust
use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::process::Command;
use std::time::{Duration, Instant};

#[derive(Debug, Clone)]
pub struct GcpAdcAuth {
    token: Option<String>,
    expires_at: Option<Instant>,
}

impl GcpAdcAuth {
    pub fn new() -> Self {
        Self {
            token: None,
            expires_at: None,
        }
    }

    /// Get access token, refreshing if expired or not cached
    pub fn get_access_token(&mut self) -> Result<String> {
        // Check if we have a valid cached token
        if let (Some(token), Some(expires)) = (&self.token, self.expires_at) {
            if Instant::now() < expires {
                return Ok(token.clone());
            }
        }

        // Fetch new token using gcloud CLI
        let output = Command::new("gcloud")
            .args(["auth", "application-default", "print-access-token"])
            .output()
            .context("Failed to execute gcloud CLI. Is it installed?")?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            anyhow::bail!(
                "gcloud auth failed: {}. Run 'gcloud auth application-default login' first.",
                stderr
            );
        }

        let token = String::from_utf8(output.stdout)
            .context("Invalid UTF-8 in gcloud output")?
            .trim()
            .to_string();

        // Cache token with 50-minute expiry (tokens are valid for 60 minutes)
        self.token = Some(token.clone());
        self.expires_at = Some(Instant::now() + Duration::from_secs(50 * 60));

        Ok(token)
    }

    /// Get project ID from ADC or environment
    pub fn get_project_id() -> Result<String> {
        // Try environment variable first
        if let Ok(project) = std::env::var("GOOGLE_CLOUD_PROJECT") {
            return Ok(project);
        }
        if let Ok(project) = std::env::var("GCLOUD_PROJECT") {
            return Ok(project);
        }

        // Fall back to gcloud config
        let output = Command::new("gcloud")
            .args(["config", "get-value", "project"])
            .output()
            .context("Failed to get project from gcloud")?;

        Ok(String::from_utf8(output.stdout)?.trim().to_string())
    }
}

#[derive(Debug, Deserialize)]
#[serde(tag = "source", rename_all = "lowercase")]
pub enum AuthConfig {
    /// Use Application Default Credentials
    Adc,
    /// Use service account key file
    ServiceAccount { key_file: String },
    /// Use environment variable
    Env { var_name: String },
    /// Use explicit token
    Token { value: String },
}
```

### 1.2 HTTP Tool Enhancement

**Modifications to `crates/noetlctl/src/playbook_runner.rs`**

```rust
// Add to Tool enum
#[derive(Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "lowercase")]
enum Tool {
    // ... existing variants
    Http {
        #[serde(default = "default_method")]
        method: String,
        url: String,
        #[serde(default)]
        headers: HashMap<String, String>,
        #[serde(default)]
        params: HashMap<String, String>,
        body: Option<String>,
        #[serde(default)]
        auth: Option<AuthConfig>,  // NEW
    },
    // ... other variants
}

// In execute_tool function, modify HTTP handling:
fn execute_http_with_auth(
    &self,
    method: &str,
    url: &str,
    headers: &HashMap<String, String>,
    params: &HashMap<String, String>,
    body: Option<&str>,
    auth: Option<&AuthConfig>,
    context: &mut ExecutionContext,
) -> Result<String> {
    let mut final_headers = headers.clone();

    // Inject auth token if configured
    if let Some(auth_config) = auth {
        match auth_config {
            AuthConfig::Adc => {
                let token = context.gcp_auth.get_access_token()?;
                final_headers.insert("Authorization".to_string(), format!("Bearer {}", token));
            }
            AuthConfig::ServiceAccount { key_file } => {
                // Implement service account auth
                unimplemented!("Service account auth not yet implemented")
            }
            AuthConfig::Env { var_name } => {
                let token = std::env::var(var_name)?;
                final_headers.insert("Authorization".to_string(), format!("Bearer {}", token));
            }
            AuthConfig::Token { value } => {
                final_headers.insert("Authorization".to_string(), format!("Bearer {}", value));
            }
        }
    }

    // Continue with existing curl execution...
    self.execute_http_request(method, url, Some(&final_headers), Some(params), body, context)
}
```

### 1.3 Playbook Auth Configuration

Support auth configuration at playbook level for inheritance:

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: gcp_infrastructure
  
# Global auth configuration (inherited by steps)
auth:
  default:
    source: adc
  gcs:
    source: adc
    scope: https://www.googleapis.com/auth/devstorage.read_write

workload:
  project_id: mestumre-dev

workflow:
  - step: start
    tool:
      kind: http
      method: GET
      url: https://compute.googleapis.com/compute/v1/projects/{{ workload.project_id }}
      auth:
        source: adc  # Can override default
```

## Phase 2: DuckDB Integration (Week 3-4)

### 2.1 DuckDB Tool Handler

**File: `crates/noetlctl/src/tools/duckdb.rs`**

```rust
use anyhow::{Context, Result};
use std::path::PathBuf;
use std::process::Command;

pub struct DuckDbHandler {
    database_path: PathBuf,
}

impl DuckDbHandler {
    pub fn new(database_path: Option<PathBuf>) -> Self {
        Self {
            database_path: database_path.unwrap_or_else(|| PathBuf::from(":memory:")),
        }
    }

    pub fn execute(&self, commands: &str) -> Result<String> {
        let db_arg = self.database_path.to_string_lossy();

        // Try DuckDB CLI first
        let output = Command::new("duckdb")
            .args([db_arg.as_ref(), "-json", "-c", commands])
            .output();

        match output {
            Ok(out) if out.status.success() => {
                Ok(String::from_utf8_lossy(&out.stdout).to_string())
            }
            Ok(out) => {
                let stderr = String::from_utf8_lossy(&out.stderr);
                anyhow::bail!("DuckDB execution failed: {}", stderr)
            }
            Err(_) => {
                // Fall back to Python with duckdb module
                self.execute_via_python(commands)
            }
        }
    }

    fn execute_via_python(&self, commands: &str) -> Result<String> {
        let db_path = self.database_path.to_string_lossy();
        let python_script = format!(
            r#"
import duckdb
import json

conn = duckdb.connect('{}')
result = conn.execute('''{}''').fetchall()
columns = [desc[0] for desc in conn.description] if conn.description else []
output = [{dict(zip(columns, row)) for row in result}]
print(json.dumps(output))
conn.close()
"#,
            db_path, commands
        );

        let output = Command::new("python3")
            .args(["-c", &python_script])
            .output()
            .context("Failed to execute DuckDB via Python")?;

        if output.status.success() {
            Ok(String::from_utf8_lossy(&output.stdout).to_string())
        } else {
            let stderr = String::from_utf8_lossy(&output.stderr);
            anyhow::bail!("DuckDB Python execution failed: {}", stderr)
        }
    }
}
```

### 2.2 Add to Tool Enum

```rust
#[derive(Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "lowercase")]
enum Tool {
    // ... existing
    DuckDB {
        /// Database file path (default: :memory:)
        #[serde(default)]
        database: Option<String>,
        /// SQL commands to execute
        commands: String,
        /// Optional output format: json, csv, table
        #[serde(default = "default_format")]
        format: String,
    },
}

fn default_format() -> String {
    "json".to_string()
}
```

### 2.3 State Schema Definition

**File: `automation/iap/schema/state_schema.sql`**

```sql
-- NoETL Infrastructure as Playbook - State Schema

-- Resource types registry
CREATE TABLE IF NOT EXISTS resource_types (
    type_id VARCHAR PRIMARY KEY,
    provider VARCHAR NOT NULL,          -- gcp, aws, azure
    api_version VARCHAR NOT NULL,
    kind VARCHAR NOT NULL,
    plural_name VARCHAR NOT NULL,
    description VARCHAR,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Current state of all managed resources
CREATE TABLE IF NOT EXISTS resources (
    resource_id VARCHAR PRIMARY KEY,    -- provider-specific ID
    type_id VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    namespace VARCHAR DEFAULT 'default',
    project VARCHAR,                    -- GCP project / AWS account
    region VARCHAR,
    zone VARCHAR,
    
    -- State
    desired_state JSON NOT NULL,        -- What the playbook defines
    current_state JSON,                 -- Last observed state from API
    status VARCHAR DEFAULT 'pending',   -- pending, creating, running, updating, deleting, error
    
    -- Metadata
    labels JSON DEFAULT '{}',
    annotations JSON DEFAULT '{}',
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_synced_at TIMESTAMP,
    
    FOREIGN KEY (type_id) REFERENCES resource_types(type_id)
);

-- Snapshot history for versioning and rollback
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id VARCHAR PRIMARY KEY,
    workspace VARCHAR NOT NULL DEFAULT 'default',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR,
    description VARCHAR,
    
    -- Snapshot content (exported as parquet for GCS sync)
    resource_count INTEGER,
    checksum VARCHAR,
    
    -- Metadata
    tags JSON DEFAULT '[]',
    parent_snapshot_id VARCHAR,
    
    FOREIGN KEY (parent_snapshot_id) REFERENCES snapshots(snapshot_id)
);

-- Resource states within each snapshot
CREATE TABLE IF NOT EXISTS snapshot_resources (
    snapshot_id VARCHAR NOT NULL,
    resource_id VARCHAR NOT NULL,
    state JSON NOT NULL,
    
    PRIMARY KEY (snapshot_id, resource_id),
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(snapshot_id)
);

-- Operations log for auditing
CREATE TABLE IF NOT EXISTS operations (
    operation_id VARCHAR PRIMARY KEY,
    resource_id VARCHAR NOT NULL,
    operation_type VARCHAR NOT NULL,    -- create, update, delete, sync
    status VARCHAR NOT NULL,            -- pending, in_progress, completed, failed
    
    -- Change tracking
    before_state JSON,
    after_state JSON,
    diff JSON,
    
    -- Execution details
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    error_message VARCHAR,
    
    -- Context
    playbook_name VARCHAR,
    execution_id VARCHAR,
    user VARCHAR,
    
    FOREIGN KEY (resource_id) REFERENCES resources(resource_id)
);

-- Drift detection results
CREATE TABLE IF NOT EXISTS drift_records (
    drift_id VARCHAR PRIMARY KEY,
    resource_id VARCHAR NOT NULL,
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Drift details
    drift_type VARCHAR NOT NULL,        -- added, removed, modified
    field_path VARCHAR,                 -- JSON path of changed field
    expected_value JSON,
    actual_value JSON,
    
    -- Resolution
    resolved_at TIMESTAMP,
    resolution_action VARCHAR,          -- accept, revert, ignore
    
    FOREIGN KEY (resource_id) REFERENCES resources(resource_id)
);

-- Locks for concurrent access prevention
CREATE TABLE IF NOT EXISTS locks (
    lock_id VARCHAR PRIMARY KEY,
    workspace VARCHAR NOT NULL,
    acquired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    acquired_by VARCHAR NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    
    UNIQUE (workspace)
);

-- Views for common queries
CREATE VIEW IF NOT EXISTS resource_summary AS
SELECT 
    r.type_id,
    rt.provider,
    rt.kind,
    COUNT(*) as count,
    SUM(CASE WHEN r.status = 'running' THEN 1 ELSE 0 END) as healthy,
    SUM(CASE WHEN r.status = 'error' THEN 1 ELSE 0 END) as error
FROM resources r
JOIN resource_types rt ON r.type_id = rt.type_id
GROUP BY r.type_id, rt.provider, rt.kind;

CREATE VIEW IF NOT EXISTS pending_drift AS
SELECT 
    d.*,
    r.name as resource_name,
    r.type_id,
    r.project
FROM drift_records d
JOIN resources r ON d.resource_id = r.resource_id
WHERE d.resolved_at IS NULL;

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_resources_type ON resources(type_id);
CREATE INDEX IF NOT EXISTS idx_resources_status ON resources(status);
CREATE INDEX IF NOT EXISTS idx_resources_project ON resources(project);
CREATE INDEX IF NOT EXISTS idx_snapshots_workspace ON snapshots(workspace);
CREATE INDEX IF NOT EXISTS idx_operations_resource ON operations(resource_id);
CREATE INDEX IF NOT EXISTS idx_drift_resource ON drift_records(resource_id);
```

## Phase 3: Sink Handler (Week 4-5)

### 3.1 Sink Implementation

**File: `crates/noetlctl/src/tools/sink.rs`**

```rust
use anyhow::{Context, Result};
use serde::Deserialize;
use std::fs;
use std::path::PathBuf;

#[derive(Debug, Deserialize)]
pub struct Sink {
    #[serde(flatten)]
    pub tool: SinkTool,
}

#[derive(Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "lowercase")]
pub enum SinkTool {
    /// Write to local file
    File { path: String },
    
    /// Upload to GCS
    Gcs {
        destination: String,
        #[serde(default)]
        content_type: Option<String>,
    },
    
    /// Insert into DuckDB table
    DuckDB {
        database: String,
        table: String,
        #[serde(default = "default_mode")]
        mode: String,  // append, replace, upsert
    },
}

fn default_mode() -> String {
    "append".to_string()
}

pub struct SinkHandler {
    gcp_auth: Option<GcpAdcAuth>,
}

impl SinkHandler {
    pub fn new(gcp_auth: Option<GcpAdcAuth>) -> Self {
        Self { gcp_auth }
    }

    pub fn write(&mut self, sink: &Sink, data: &str) -> Result<()> {
        match &sink.tool {
            SinkTool::File { path } => {
                fs::write(path, data).context(format!("Failed to write to {}", path))?;
                println!("   Wrote {} bytes to {}", data.len(), path);
            }
            
            SinkTool::Gcs { destination, content_type } => {
                self.upload_to_gcs(destination, data, content_type.as_deref())?;
            }
            
            SinkTool::DuckDB { database, table, mode } => {
                self.insert_to_duckdb(database, table, data, mode)?;
            }
        }
        Ok(())
    }

    fn upload_to_gcs(&mut self, destination: &str, data: &str, content_type: Option<&str>) -> Result<()> {
        let auth = self.gcp_auth.as_mut()
            .context("GCP auth required for GCS sink")?;
        let token = auth.get_access_token()?;

        // Parse gs:// URI
        let dest = destination.strip_prefix("gs://")
            .context("GCS destination must start with gs://")?;
        let parts: Vec<&str> = dest.splitn(2, '/').collect();
        let bucket = parts[0];
        let object = parts.get(1).unwrap_or(&"");

        // Use GCS JSON API
        let url = format!(
            "https://storage.googleapis.com/upload/storage/v1/b/{}/o?uploadType=media&name={}",
            bucket, object
        );

        let ct = content_type.unwrap_or("application/octet-stream");

        let output = std::process::Command::new("curl")
            .args([
                "-s", "-X", "POST",
                "-H", &format!("Authorization: Bearer {}", token),
                "-H", &format!("Content-Type: {}", ct),
                "--data-binary", data,
                &url,
            ])
            .output()
            .context("Failed to upload to GCS")?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            anyhow::bail!("GCS upload failed: {}", stderr);
        }

        println!("   Uploaded {} bytes to {}", data.len(), destination);
        Ok(())
    }

    fn insert_to_duckdb(&self, database: &str, table: &str, data: &str, mode: &str) -> Result<()> {
        let handler = DuckDbHandler::new(Some(PathBuf::from(database)));

        let insert_sql = match mode {
            "replace" => format!(
                "DELETE FROM {}; INSERT INTO {} SELECT * FROM read_json_auto('{}');",
                table, table, data
            ),
            "upsert" => {
                // Requires primary key knowledge - simplified version
                format!("INSERT OR REPLACE INTO {} SELECT * FROM read_json_auto('{}');", table, data)
            }
            _ => format!("INSERT INTO {} SELECT * FROM read_json_auto('{}');", table, data),
        };

        handler.execute(&insert_sql)?;
        println!("   Inserted data into {}.{}", database, table);
        Ok(())
    }
}
```

### 3.2 Step Sink Integration

```rust
// In Step struct
#[derive(Debug, Deserialize)]
struct Step {
    step: String,
    desc: Option<String>,
    tool: Option<Tool>,
    sink: Option<Sink>,  // NEW
    next: Option<Vec<NextStep>>,
    // ...
}

// In execute_step function
fn execute_step(&self, playbook: &Playbook, step_name: &str, context: &mut ExecutionContext) -> Result<()> {
    // ... existing tool execution ...

    // Handle sink if present
    if let Some(sink) = &step.sink {
        if let Some(result) = &step_result {
            let mut sink_handler = SinkHandler::new(Some(context.gcp_auth.clone()));
            sink_handler.write(sink, result)?;
        }
    }

    // ... rest of step execution ...
}
```

## Phase 4: IaP CLI Commands (Week 6-7)

### 4.1 New Subcommands

**Modifications to `crates/noetlctl/src/main.rs`**

```rust
#[derive(Subcommand)]
enum Commands {
    // ... existing commands ...

    /// Infrastructure as Playbook commands
    /// Examples:
    ///     noetl iap init --provider gcp --project mestumre-dev
    ///     noetl iap plan
    ///     noetl iap apply
    ///     noetl iap state list
    ///     noetl iap sync push
    #[command(verbatim_doc_comment)]
    Iap {
        #[command(subcommand)]
        command: IapCommand,
    },
}

#[derive(Subcommand)]
enum IapCommand {
    /// Initialize new IaP project
    Init {
        /// Cloud provider (gcp, aws, azure)
        #[arg(long)]
        provider: String,
        
        /// Project/Account ID
        #[arg(long)]
        project: String,
        
        /// Workspace name
        #[arg(long, default_value = "default")]
        workspace: String,
        
        /// State bucket name (auto-generated if not specified)
        #[arg(long)]
        state_bucket: Option<String>,
    },
    
    /// Plan infrastructure changes
    Plan {
        /// Playbook file or directory
        #[arg(default_value = ".")]
        path: PathBuf,
        
        /// Output format: text, json
        #[arg(long, default_value = "text")]
        format: String,
    },
    
    /// Apply planned changes
    Apply {
        /// Playbook file or directory
        #[arg(default_value = ".")]
        path: PathBuf,
        
        /// Auto-approve changes
        #[arg(long)]
        auto_approve: bool,
    },
    
    /// State management
    State {
        #[command(subcommand)]
        command: StateCommand,
    },
    
    /// Sync state with remote storage
    Sync {
        #[command(subcommand)]
        command: SyncCommand,
    },
    
    /// Drift detection and resolution
    Drift {
        #[command(subcommand)]
        command: DriftCommand,
    },
}

#[derive(Subcommand)]
enum StateCommand {
    /// List all managed resources
    List {
        #[arg(long)]
        type_filter: Option<String>,
    },
    
    /// Show resource details
    Show {
        resource_id: String,
    },
    
    /// Remove resource from state
    Remove {
        resource_id: String,
        #[arg(long)]
        force: bool,
    },
    
    /// Import existing resource
    Import {
        resource_type: String,
        resource_id: String,
    },
}

#[derive(Subcommand)]
enum SyncCommand {
    /// Push local state to GCS
    Push {
        #[arg(long)]
        force: bool,
    },
    
    /// Pull remote state from GCS
    Pull {
        #[arg(long)]
        force: bool,
    },
    
    /// Show sync status
    Status,
}

#[derive(Subcommand)]
enum DriftCommand {
    /// Detect drift between desired and current state
    Detect,
    
    /// Reconcile detected drift
    Reconcile {
        /// Resolution strategy: accept, revert
        #[arg(long, default_value = "accept")]
        strategy: String,
    },
    
    /// Show pending drift
    List,
}
```

## Phase 5: GCP Provider Implementation (Week 7-8)

### 5.1 GKE Autopilot Resource Handler

**File: `automation/iap/gcp/resources/gke_autopilot.yaml`**

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: gke_autopilot_resource
  path: iap/gcp/resources/gke-autopilot
  labels:
    iap.noetl.io/provider: gcp
    iap.noetl.io/resource-type: container.googleapis.com/Cluster
    iap.noetl.io/mode: terraform

workload:
  # Required parameters
  project_id: ""
  region: us-central1
  cluster_name: ""
  
  # Optional parameters with defaults
  network: default
  subnetwork: default
  master_ipv4_cidr: 172.16.0.0/28
  
  # Release channel: RAPID, REGULAR, STABLE
  release_channel: REGULAR
  
  # Private cluster settings
  enable_private_nodes: true
  enable_private_endpoint: false
  
  # State management
  state_database: /tmp/noetl-state.duckdb
  
workbook:
  - name: validate_inputs
    tool:
      kind: python
      code: |
        errors = []
        if not workload.get('project_id'):
            errors.append("project_id is required")
        if not workload.get('cluster_name'):
            errors.append("cluster_name is required")
        if errors:
            raise ValueError(f"Validation failed: {', '.join(errors)}")
        result = {"valid": True}

  - name: check_existing
    tool:
      kind: http
      method: GET
      url: https://container.googleapis.com/v1/projects/{{ workload.project_id }}/locations/{{ workload.region }}/clusters/{{ workload.cluster_name }}
      auth:
        source: adc
      
  - name: create_cluster
    tool:
      kind: http
      method: POST
      url: https://container.googleapis.com/v1/projects/{{ workload.project_id }}/locations/{{ workload.region }}/clusters
      auth:
        source: adc
      headers:
        Content-Type: application/json
      body: |
        {
          "cluster": {
            "name": "{{ workload.cluster_name }}",
            "autopilot": {
              "enabled": true
            },
            "network": "projects/{{ workload.project_id }}/global/networks/{{ workload.network }}",
            "subnetwork": "projects/{{ workload.project_id }}/regions/{{ workload.region }}/subnetworks/{{ workload.subnetwork }}",
            "releaseChannel": {
              "channel": "{{ workload.release_channel }}"
            },
            "privateClusterConfig": {
              "enablePrivateNodes": {{ workload.enable_private_nodes | lower }},
              "enablePrivateEndpoint": {{ workload.enable_private_endpoint | lower }},
              "masterIpv4CidrBlock": "{{ workload.master_ipv4_cidr }}"
            },
            "ipAllocationPolicy": {
              "useIpAliases": true
            }
          }
        }

  - name: wait_for_operation
    tool:
      kind: http
      method: GET
      url: "{{ vars.operation_url }}"
      auth:
        source: adc

  - name: save_state
    tool:
      kind: duckdb
      database: "{{ workload.state_database }}"
      commands: |
        INSERT INTO resources (resource_id, type_id, name, project, region, desired_state, current_state, status)
        VALUES (
          '{{ workload.project_id }}/{{ workload.region }}/{{ workload.cluster_name }}',
          'container.googleapis.com/Cluster',
          '{{ workload.cluster_name }}',
          '{{ workload.project_id }}',
          '{{ workload.region }}',
          '{{ create_cluster.body | tojson }}',
          '{{ vars.current_state | tojson }}',
          'running'
        )
        ON CONFLICT (resource_id) DO UPDATE SET
          current_state = EXCLUDED.current_state,
          status = EXCLUDED.status,
          updated_at = CURRENT_TIMESTAMP;

workflow:
  - step: start
    desc: Begin GKE Autopilot provisioning
    tool:
      kind: workbook
      name: validate_inputs
    next:
      - step: check_existing

  - step: check_existing
    desc: Check if cluster already exists
    tool:
      kind: workbook
      name: check_existing
    vars:
      cluster_exists: "{{ result.status == 200 }}"
      current_state: "{{ result.body if result.status == 200 else {} }}"
    case:
      - when: "{{ vars.cluster_exists }}"
        then:
          - step: update_state
      - else:
          - step: create_cluster

  - step: create_cluster
    desc: Create new GKE Autopilot cluster
    tool:
      kind: workbook
      name: create_cluster
    vars:
      operation_url: "https://container.googleapis.com/v1/{{ result.body.name }}"
    next:
      - step: wait_operation

  - step: wait_operation
    desc: Wait for cluster creation to complete
    tool:
      kind: workbook
      name: wait_for_operation
    case:
      - when: "{{ result.body.status == 'DONE' }}"
        then:
          - step: get_cluster_info
      - when: "{{ result.body.status == 'RUNNING' }}"
        then:
          - step: wait_sleep

  - step: wait_sleep
    desc: Sleep and retry operation check
    tool:
      kind: shell
      cmds:
        - sleep 30
    next:
      - step: wait_operation

  - step: get_cluster_info
    desc: Get final cluster state
    tool:
      kind: workbook
      name: check_existing
    vars:
      current_state: "{{ result.body }}"
    next:
      - step: save_state

  - step: update_state
    desc: Update existing cluster state
    tool:
      kind: workbook
      name: save_state
    next:
      - step: end

  - step: save_state
    desc: Save state to DuckDB
    tool:
      kind: workbook
      name: save_state
    sink:
      kind: file
      path: /tmp/cluster_state.json
    next:
      - step: end

  - step: end
    desc: Provisioning complete
    tool:
      kind: shell
      cmds:
        - |
          echo "GKE Autopilot cluster '{{ workload.cluster_name }}' provisioning complete"
          echo "Project: {{ workload.project_id }}"
          echo "Region: {{ workload.region }}"
```

## Dependency Updates

### Cargo.toml Additions

```toml
[dependencies]
# ... existing dependencies ...

# For authentication
jsonwebtoken = "9"
chrono = { version = "0.4", features = ["serde"] }

# For JSON handling
serde_json = "1.0"

# For HTTP (optional, if moving away from curl)
reqwest = { version = "0.11", features = ["json", "blocking"] }

# For DuckDB (optional embedded support)
# duckdb = "0.9"  # Consider for embedded support later
```

## Testing Strategy

### Unit Tests

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_gcp_adc_token_parsing() {
        let auth = GcpAdcAuth::new();
        // Mock gcloud output
        assert!(auth.token.is_none());
    }

    #[test]
    fn test_duckdb_command_rendering() {
        let handler = DuckDbHandler::new(None);
        let result = handler.execute("SELECT 1 as value");
        assert!(result.is_ok());
    }

    #[test]
    fn test_sink_gcs_uri_parsing() {
        let uri = "gs://my-bucket/path/to/file.json";
        let (bucket, object) = parse_gcs_uri(uri).unwrap();
        assert_eq!(bucket, "my-bucket");
        assert_eq!(object, "path/to/file.json");
    }
}
```

### Integration Tests

Located in `automation/iap/gcp/tests/`:

```yaml
# test_gke_lifecycle.yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: test_gke_lifecycle
  path: iap/gcp/tests/gke-lifecycle

workload:
  project_id: mestumre-dev
  cluster_name: test-cluster-{{ timestamp }}

workflow:
  - step: start
    next:
      - step: create

  - step: create
    desc: Create test cluster
    tool:
      kind: playbook
      path: ../resources/gke_autopilot.yaml
    args:
      project_id: "{{ workload.project_id }}"
      cluster_name: "{{ workload.cluster_name }}"
    next:
      - step: verify

  - step: verify
    desc: Verify cluster exists
    tool:
      kind: http
      method: GET
      url: https://container.googleapis.com/v1/projects/{{ workload.project_id }}/locations/us-central1/clusters/{{ workload.cluster_name }}
      auth:
        source: adc
    vars:
      cluster_status: "{{ result.body.status }}"
    case:
      - when: "{{ vars.cluster_status == 'RUNNING' }}"
        then:
          - step: cleanup
      - else:
          - step: fail

  - step: cleanup
    desc: Delete test cluster
    tool:
      kind: http
      method: DELETE
      url: https://container.googleapis.com/v1/projects/{{ workload.project_id }}/locations/us-central1/clusters/{{ workload.cluster_name }}
      auth:
        source: adc
    next:
      - step: end

  - step: fail
    desc: Test failed
    tool:
      kind: shell
      cmds:
        - echo "Test failed - cluster not in RUNNING state"
        - exit 1

  - step: end
    desc: Test complete
```

## Timeline Summary

| Week | Phase | Deliverables |
|------|-------|-------------|
| 1-2 | Authentication | GCP ADC handler, HTTP auth injection |
| 3-4 | DuckDB Integration | DuckDB tool, state schema |
| 4-5 | Sink Handler | File, GCS, DuckDB sinks |
| 6-7 | CLI Commands | `noetl iap` subcommands |
| 7-8 | GCP Provider | GKE Autopilot playbooks, tests |

## Success Criteria

1. **Authentication**: Successfully call GCP APIs using ADC tokens from `noetlctl`
2. **State Management**: Track resources in DuckDB with full CRUD operations
3. **GCS Sync**: Push/pull state files to GCS buckets
4. **Drift Detection**: Compare desired vs current state and report differences
5. **End-to-End**: Provision GKE Autopilot cluster using only `noetl run` commands

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| gcloud CLI dependency | Document as prerequisite; consider google-auth Rust crate later |
| DuckDB CLI availability | Fallback to Python with duckdb module |
| GCS authentication complexity | Start with ADC only; add service account support later |
| Complex state reconciliation | Start with simple replace; add upsert logic incrementally |
