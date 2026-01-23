---
sidebar_position: 37
title: GKE Autopilot Full Provisioning
---

# GKE Autopilot Full Provisioning

This document describes each step to provision a GKE Autopilot cluster and deploy the NoETL stack using the automation playbooks.

## Scope

- GKE Autopilot cluster lifecycle
- PostgreSQL, NATS JetStream, NoETL server/workers, Gateway
- Ingress publishing for mestumre.dev
- DNS and TLS validation

## Prerequisites

- Google Application Default Credentials configured
- GCP project: mestumre-dev
- Region: us-central1
- Artifact Registry repository created: noetl

## Step 1: Create or verify Artifact Registry

If the repository is not present, create it:

noetl iap apply automation/iap/gcp/artifact_registry.yaml \
  --auto-approve \
  --var action=create \
  --var project_id=mestumre-dev \
  --var region=us-central1 \
  --var repository_id=noetl

## Step 2: Build and push images

Publish these images to Artifact Registry:

- us-central1-docker.pkg.dev/mestumre-dev/noetl/noetl:latest
- us-central1-docker.pkg.dev/mestumre-dev/noetl/noetl-gateway:latest

If PostgreSQL needs a mirrored image:

- us-central1-docker.pkg.dev/mestumre-dev/noetl/bitnami-postgresql:multiarch

## Step 3: Destroy existing cluster (optional)

noetl iap apply automation/iap/gcp/gke_autopilot.yaml \
  --auto-approve \
  --var action=destroy \
  --var project_id=mestumre-dev \
  --var region=us-central1 \
  --var cluster_name=noetl-test-cluster

## Step 4: Create cluster and deploy stack

noetl iap apply automation/iap/gcp/gke_autopilot.yaml \
  --auto-approve \
  --var action=create \
  --var deploy_stack=true \
  --var project_id=mestumre-dev \
  --var region=us-central1 \
  --var cluster_name=noetl-test-cluster \
  --var noetl_image_repository=us-central1-docker.pkg.dev/mestumre-dev/noetl/noetl \
  --var noetl_image_tag=latest \
  --var gateway_image_repository=us-central1-docker.pkg.dev/mestumre-dev/noetl/noetl-gateway \
  --var gateway_image_tag=latest

If the cluster already exists, deploy only:

noetl iap apply automation/iap/gcp/gke_autopilot.yaml \
  --auto-approve \
  --var action=deploy \
  --var deploy_stack=true \
  --var project_id=mestumre-dev \
  --var region=us-central1 \
  --var cluster_name=noetl-test-cluster \
  --var noetl_image_repository=us-central1-docker.pkg.dev/mestumre-dev/noetl/noetl \
  --var noetl_image_tag=latest \
  --var gateway_image_repository=us-central1-docker.pkg.dev/mestumre-dev/noetl/noetl-gateway \
  --var gateway_image_tag=latest

## Step 5: Initialize database schema

Schema initialization runs during deployment when `init_noetl_schema=true` (default). To skip it, set `--var init_noetl_schema=false`.

If you run the playbook outside the repo root, set `--var noetl_schema_path=/absolute/path/to/noetl/database/ddl/postgres/schema_ddl.sql`.

If you skip initialization, apply the DDL manually:

- File: noetl/database/ddl/postgres/schema_ddl.sql
- Target schema: noetl

## Step 6: Validate stack health

Verify pods are running:

- postgres
- nats
- noetl server and workers
- gateway

## Step 7: Publish access under mestumre.dev

Ingress is enabled by the playbook with these hosts:

- api.mestumre.dev
- gateway.mestumre.dev

### DNS records

Create DNS A records in the mestumre.dev DNS zone:

- api.mestumre.dev → NoETL ingress IP
- gateway.mestumre.dev → Gateway ingress IP

### TLS

Wait for ManagedCertificate resources to reach Active.

## Step 8: Verify external access

- NoETL API: https://api.mestumre.dev
- Gateway: https://gateway.mestumre.dev

## Troubleshooting

- If PostgreSQL pods are Pending with volume errors, wait for CSI drivers to be ready and restart the pod.
- If NoETL server fails with missing tables, apply the schema DDL and restart the pods.
- If ingress address is empty, wait for the load balancer to be provisioned before creating DNS records.
- If certificates stay in Provisioning, confirm DNS A records match the ingress IPs.
