---
sidebar_position: 35
title: "GCP IaP: Autopilot Deploy Flow"
---

# GCP IaP: Autopilot Deploy Flow

This guide covers how to register a pre-existing GKE Autopilot cluster in IaP state, create a GCP Artifact Registry image repository, and sync state to GCS.

## Prerequisites

- Google Application Default Credentials (ADC) configured
- GCP project and region selected
- IaP state bucket created (or use `noetl iap init`)

## Initialize IaP State

```bash
noetl iap init --project mestumre-dev --bucket mestumre-dev-noetl-state
```

## Create Artifact Registry Repository

Use the IaP playbook to create a Docker image repository.

```bash
noetl iap apply automation/iap/gcp/artifact_registry.yaml \
  --auto-approve \
  --var action=create \
  --var project_id=mestumre-dev \
  --var region=us-central1 \
  --var repository_id=noetl
```

## Register an Existing Autopilot Cluster

If the cluster was created using `noetl run`, register it in IaP state with `noetl iap apply`.

```bash
noetl iap apply automation/iap/gcp/gke_autopilot.yaml \
  --auto-approve \
  --var action=create \
  --var project_id=mestumre-dev \
  --var region=us-central1 \
  --var cluster_name=noetl-test-cluster \
  --var deploy_stack=false
```

## Sync State to GCS

```bash
noetl iap sync push
```

## Verify State

```bash
noetl iap state list
```

The IaP CLI uses the local state database at `.noetl/state.duckdb` by default.

If no resources appear, verify the active IaP workspace and state database path. Use `noetl iap workspace list` and `noetl iap workspace use <name>` to select the correct workspace.
