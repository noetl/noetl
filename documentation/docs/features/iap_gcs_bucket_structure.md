---
sidebar_position: 22
title: IaP GCS Bucket Structure
description: GCS bucket folder structure for Infrastructure as Playbook state management
---

# GCS Bucket Structure for Infrastructure as Playbook

This document defines the Google Cloud Storage bucket folder structure used by NoETL Infrastructure as Playbook (IaP) for state persistence, supporting both Terraform-like and Crossplane-like operational modes.

## Overview

IaP uses GCS as the persistent storage backend for infrastructure state. The bucket structure is designed to support:

1. **Multiple workspaces** (like Terraform workspaces)
2. **State versioning** with snapshot history
3. **Concurrent access** with lock files
4. **Multi-tenant** deployments with isolated state
5. **Crossplane-style** continuous reconciliation patterns

## Bucket Naming Convention

```
{project_id}-noetl-state
```

Example: `mestumre-dev-noetl-state`

## Root Structure

```
gs://{project}-noetl-state/
├── terraform/                    # Terraform-like workloads (mutable state)
├── crossplane/                   # Crossplane-like workloads (reconciliation)
├── shared/                       # Shared resources across workspaces
└── metadata/                     # Bucket-level metadata
```

## Terraform Mode Structure

Used for traditional infrastructure provisioning with explicit state management.

```
gs://{project}-noetl-state/
└── terraform/
    ├── {workspace}/              # Workspace isolation (default, staging, production)
    │   ├── state.duckdb          # Current state database
    │   ├── state.duckdb.lock     # Lock file for concurrent access
    │   ├── state.duckdb.backup   # Last known good state
    │   │
    │   ├── history/              # Snapshot history
    │   │   ├── snapshot_{timestamp}.parquet     # Full state export
    │   │   ├── snapshot_{timestamp}.meta.json   # Snapshot metadata
    │   │   └── ...
    │   │
    │   ├── plans/                # Saved plan files
    │   │   ├── plan_{timestamp}.json
    │   │   └── ...
    │   │
    │   └── imports/              # Imported resource state
    │       ├── import_{resource_type}_{timestamp}.json
    │       └── ...
    │
    ├── default/                  # Default workspace
    │   └── ...
    │
    ├── staging/                  # Staging environment
    │   └── ...
    │
    └── production/               # Production environment
        └── ...
```

### File Formats

#### state.duckdb
Primary state database file containing all resource tracking tables.

#### state.duckdb.lock
```json
{
  "lock_id": "uuid-v4",
  "workspace": "default",
  "acquired_at": "2026-01-18T10:30:00Z",
  "acquired_by": "user@example.com",
  "host": "workstation-1",
  "operation": "apply",
  "expires_at": "2026-01-18T11:30:00Z"
}
```

#### `snapshot_{timestamp}.meta.json`
```json
{
  "snapshot_id": "snapshot-20260118103000",
  "workspace": "default",
  "created_at": "2026-01-18T10:30:00Z",
  "created_by": "user@example.com",
  "description": "Pre-deployment snapshot",
  "resource_count": 42,
  "checksum": "sha256:abc123...",
  "size_bytes": 1048576,
  "tags": ["v1.2.0", "pre-deploy"],
  "parent_snapshot_id": "snapshot-20260117093000"
}
```

## Crossplane Mode Structure

Used for Kubernetes-native continuous reconciliation patterns.

```
gs://{project}-noetl-state/
└── crossplane/
    ├── {cluster}/                # Kubernetes cluster identifier
    │   ├── {namespace}/          # Kubernetes namespace
    │   │   ├── resources/        # Managed resource manifests
    │   │   │   ├── Cluster_{name}.yaml
    │   │   │   ├── Instance_{name}.yaml
    │   │   │   └── ...
    │   │   │
    │   │   └── status/           # Resource status (synced from cloud)
    │   │       ├── Cluster_{name}.status.json
    │   │       ├── Instance_{name}.status.json
    │   │       └── ...
    │   │
    │   └── default/              # Default namespace
    │       └── ...
    │
    ├── global/                   # Cluster-scoped resources
    │   ├── provider_configs/     # Provider configurations
    │   │   ├── gcp-default.yaml
    │   │   ├── gcp-production.yaml
    │   │   └── ...
    │   │
    │   ├── composition/          # XRD and Compositions
    │   │   ├── xrd_gkeautopilot.yaml
    │   │   ├── composition_gkeautopilot.yaml
    │   │   └── ...
    │   │
    │   └── claims/               # Composite Resource Claims
    │       └── ...
    │
    └── events/                   # Event history for debugging
        ├── events_{date}.jsonl   # JSON Lines format
        └── ...
```

### Resource Manifest Format

```yaml
# resources/Cluster_my-cluster.yaml
apiVersion: container.gcp.noetl.io/v1alpha1
kind: Cluster
metadata:
  name: my-cluster
  namespace: default
  labels:
    app.kubernetes.io/managed-by: noetl-iap
spec:
  forProvider:
    location: us-central1
    autopilot:
      enabled: true
    releaseChannel:
      channel: REGULAR
  providerConfigRef:
    name: gcp-default
  writeConnectionSecretToRef:
    name: my-cluster-connection
    namespace: default
```

### Status File Format

```json
{
  "apiVersion": "container.gcp.noetl.io/v1alpha1",
  "kind": "Cluster",
  "metadata": {
    "name": "my-cluster",
    "namespace": "default"
  },
  "status": {
    "conditions": [
      {
        "type": "Ready",
        "status": "True",
        "lastTransitionTime": "2026-01-18T10:30:00Z",
        "reason": "Available",
        "message": "Cluster is running"
      },
      {
        "type": "Synced",
        "status": "True",
        "lastTransitionTime": "2026-01-18T10:25:00Z",
        "reason": "ReconcileSuccess"
      }
    ],
    "atProvider": {
      "endpoint": "34.123.45.67",
      "status": "RUNNING",
      "currentMasterVersion": "1.27.3-gke.1700"
    }
  }
}
```

## Shared Resources Structure

Common resources shared across workspaces and modes.

```
gs://{project}-noetl-state/
└── shared/
    ├── modules/                  # Reusable playbook modules
    │   ├── gke/
    │   │   ├── autopilot.yaml
    │   │   ├── standard.yaml
    │   │   └── README.md
    │   │
    │   ├── networking/
    │   │   ├── vpc.yaml
    │   │   ├── firewall.yaml
    │   │   └── ...
    │   │
    │   └── iam/
    │       ├── service_account.yaml
    │       └── ...
    │
    ├── policies/                 # OPA/Rego policy definitions
    │   ├── naming.rego
    │   ├── labels.rego
    │   ├── security.rego
    │   └── ...
    │
    ├── schemas/                  # JSON schemas for validation
    │   ├── gke_cluster.schema.json
    │   ├── vpc_network.schema.json
    │   └── ...
    │
    └── templates/                # Reusable configuration templates
        ├── autopilot_defaults.yaml
        ├── production_labels.yaml
        └── ...
```

## Metadata Structure

Bucket-level metadata and configuration.

```
gs://{project}-noetl-state/
└── metadata/
    ├── config.yaml               # Global IaP configuration
    ├── providers.yaml            # Provider registry
    ├── workspaces.yaml           # Workspace registry
    └── audit/                    # Audit logs
        ├── audit_{date}.jsonl
        └── ...
```

### config.yaml
```yaml
version: "1.0"
project_id: mestumre-dev
created_at: "2026-01-18T10:00:00Z"

default_workspace: default
default_region: us-central1

features:
  versioning: true
  encryption: true
  audit_logging: true

retention:
  snapshots_days: 90
  audit_days: 365
  plan_days: 30

notifications:
  drift_detected:
    enabled: true
    channels: ["email", "slack"]
```

## Access Patterns

### Read Operations

| Operation | Path Pattern | Method |
|-----------|--------------|--------|
| Get current state | `terraform/{workspace}/state.duckdb` | GET |
| List snapshots | `terraform/{workspace}/history/*.meta.json` | LIST |
| Get specific snapshot | `terraform/{workspace}/history/snapshot_{ts}.parquet` | GET |
| Get resource manifest | `crossplane/{cluster}/{ns}/resources/{kind}_{name}.yaml` | GET |
| Get resource status | `crossplane/{cluster}/{ns}/status/{kind}_{name}.status.json` | GET |

### Write Operations

| Operation | Path Pattern | Method |
|-----------|--------------|--------|
| Update state | `terraform/{workspace}/state.duckdb` | PUT |
| Acquire lock | `terraform/{workspace}/state.duckdb.lock` | PUT (conditional) |
| Release lock | `terraform/{workspace}/state.duckdb.lock` | DELETE |
| Create snapshot | `terraform/{workspace}/history/snapshot_{ts}.*` | PUT |
| Update resource | `crossplane/{cluster}/{ns}/resources/{kind}_{name}.yaml` | PUT |
| Update status | `crossplane/{cluster}/{ns}/status/{kind}_{name}.status.json` | PUT |

## IAM Permissions

### Recommended IAM Roles

| Role | Purpose |
|------|---------|
| `roles/storage.objectViewer` | Read state and snapshots |
| `roles/storage.objectCreator` | Create snapshots and exports |
| `roles/storage.objectAdmin` | Full state management |

### Fine-grained Permissions

```json
{
  "bindings": [
    {
      "role": "roles/storage.objectViewer",
      "members": ["group:developers@example.com"],
      "condition": {
        "expression": "resource.name.startsWith('terraform/production/') == false"
      }
    },
    {
      "role": "roles/storage.objectAdmin",
      "members": ["group:platform-team@example.com"]
    }
  ]
}
```

## Lifecycle Rules

Recommended GCS lifecycle rules:

```json
{
  "lifecycle": {
    "rule": [
      {
        "action": {"type": "Delete"},
        "condition": {
          "age": 90,
          "matchesPrefix": ["terraform/"],
          "matchesSuffix": [".parquet"]
        }
      },
      {
        "action": {"type": "Delete"},
        "condition": {
          "age": 30,
          "matchesPrefix": ["terraform/"],
          "matchesSuffix": ["/plans/"]
        }
      },
      {
        "action": {"type": "SetStorageClass", "storageClass": "NEARLINE"},
        "condition": {
          "age": 30,
          "matchesPrefix": ["terraform/"],
          "matchesSuffix": [".parquet"]
        }
      },
      {
        "action": {"type": "Delete"},
        "condition": {
          "numNewerVersions": 5
        }
      }
    ]
  }
}
```

## Migration from Terraform

If migrating from existing Terraform state:

```
gs://{project}-noetl-state/
└── terraform/
    └── imported/
        ├── terraform.tfstate         # Original Terraform state
        ├── terraform.tfstate.backup
        └── migration_report.json     # Migration analysis
```

## Security Considerations

1. **Encryption**: Enable default encryption with customer-managed keys (CMEK)
2. **Versioning**: Enable object versioning for state recovery
3. **Access Logging**: Enable GCS access logs for audit
4. **Lock Timeouts**: Use short TTL (1 hour) for lock files
5. **Backup Strategy**: Regular exports to separate bucket/project

## Example Bucket Creation

```bash
# Create bucket with recommended settings
gsutil mb -p mestumre-dev \
  -l us-central1 \
  -c STANDARD \
  gs://mestumre-dev-noetl-state

# Enable versioning
gsutil versioning set on gs://mestumre-dev-noetl-state

# Enable uniform bucket-level access
gsutil uniformbucketlevelaccess set on gs://mestumre-dev-noetl-state

# Apply lifecycle rules
gsutil lifecycle set lifecycle.json gs://mestumre-dev-noetl-state
```
