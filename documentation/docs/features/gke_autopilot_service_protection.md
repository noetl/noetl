---
sidebar_position: 36
title: GKE Autopilot Service Protection
---

# GKE Autopilot Service Protection

This guide documents how NoETL and Gateway public exposure was removed, how to publish access under mestumre.dev, and how to delete or reprovision the stack.

## What changed

Public LoadBalancer services were replaced with internal ClusterIP services:

- NoETL external service disabled
- Gateway service type set to ClusterIP

This removes public internet access for both services.

## Validate exposure

Check services:

- noetl/noetl
- gateway/gateway

Both should show `TYPE: ClusterIP` and no external IPs.

## Publish under mestumre.dev

### Summary

Public access is exposed via GKE Ingress with TLS using a managed certificate.

Recommended subdomains:

- Gateway: gateway.mestumre.dev
- NoETL API: api.mestumre.dev

### Deploy ingress

Enable ingress in the Helm charts and set hosts.

Gateway:

- ingress.enabled=true
- ingress.host=gateway.mestumre.dev
- ingress.managedCertificate.enabled=true
- ingress.managedCertificate.name=gateway-managed-cert

NoETL API:

- ingress.enabled=true
- ingress.host=api.mestumre.dev
- ingress.managedCertificate.enabled=true
- ingress.managedCertificate.name=noetl-managed-cert

### DNS records

After the Ingress objects are created, find the external IP for each ingress and create DNS A records.

Steps:

1. Get ingress addresses for both namespaces.
2. Create DNS A records in the mestumre.dev DNS zone:
   - gateway.mestumre.dev → Gateway ingress IP
   - api.mestumre.dev → NoETL ingress IP
3. Wait for DNS propagation.

When addresses appear, the ingress objects should show a non-empty ADDRESS field.

### TLS status

GKE ManagedCertificate provisioning can take several minutes. Validate status in the GKE console or by describing the ManagedCertificate resources.

Expected status flow:

- Provisioning → Active

If status remains Provisioning, verify DNS A records and that the ingress ADDRESS fields match the DNS targets.

## Developer usage

Gateway usage:

- Base URL: https://gateway.mestumre.dev
- This should be the public entry point for developers to upload playbooks, credentials, and run executions.

NoETL API usage:

- Base URL: https://api.mestumre.dev
- Use this for direct NoETL API calls if required by internal tooling.

## Re-enable public access (LoadBalancer)

If you need direct LoadBalancer services instead of ingress:

- NoETL: set externalService.enabled=true and externalService.type=LoadBalancer
- Gateway: set service.type=LoadBalancer

## Delete stack

Run these steps in the GKE context:

1. Uninstall Helm releases:
   - noetl (namespace: noetl)
   - noetl-gateway (namespace: gateway)
   - nats (namespace: nats)
   - postgres (namespace: postgres)
2. Delete namespaces if desired:
   - noetl, gateway, nats, postgres
3. Delete PVCs if you want to remove data:
   - noetl PVCs (if enabled)
   - postgres PVCs

## Destroy cluster

Use the IaP playbook to remove the GKE cluster:

Command:

noetl iap apply automation/iap/gcp/gke_autopilot.yaml \
   --auto-approve \
   --var action=destroy \
   --var project_id=mestumre-dev \
   --var region=us-central1 \
   --var cluster_name=noetl-test-cluster

After deletion, verify state:

- noetl iap state list

## Create cluster and deploy everything

1. Create the cluster and deploy the stack in one command:

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

2. If the cluster already exists, deploy only:

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

3. Build and push images to Artifact Registry:
   - noetl image
   - noetl-gateway image
4. Deploy PostgreSQL using the mirrored Bitnami image.
5. Deploy NATS with JetStream and auth users.
6. Schema initialization runs during deployment when `init_noetl_schema=true` (default).
7. Deploy NoETL and Gateway Helm charts.
8. Enable ingress for api.mestumre.dev and gateway.mestumre.dev.
9. Create DNS A records that point to the ingress IPs.
10. Wait for ManagedCertificate status to become Active.

## Reprovision stack

1. Verify Artifact Registry images exist:
   - us-central1-docker.pkg.dev/mestumre-dev/noetl/noetl:latest
   - us-central1-docker.pkg.dev/mestumre-dev/noetl/noetl-gateway:latest
2. Deploy PostgreSQL:
   - Use the Bitnami chart with the mirrored image tag in Artifact Registry.
3. Deploy NATS with JetStream enabled and auth users:
   - user: noetl
   - password: noetl
4. Schema initialization runs during deployment when `init_noetl_schema=true` (default).
5. Deploy NoETL and Gateway Helm charts.
6. Verify pods are ready in namespaces:
   - postgres, nats, noetl, gateway

## Notes

- If NoETL PVCs are disabled, server and workers rely on Postgres and NATS only.
- For persistence, re-enable PVCs with a storage class that supports your node pool and access mode.
- Schema initialization runs during deployment when `init_noetl_schema=true` (default).
