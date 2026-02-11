# NoETL GCP GKE Fresh Provisioning

This folder contains a **new, isolated** automation flow for provisioning GKE and deploying the full NoETL stack:

- PostgreSQL
- NATS
- ClickHouse (optional)
- NoETL server + workers
- NoETL Gateway
- NoETL GUI

It does **not** modify existing kind-based automation and does not use `ci/` assets.

## Playbook

- `automation/gcp_gke/noetl_gke_fresh_stack.yaml`

## Assets in this folder

- `automation/gcp_gke/helm/gui/*` - Helm chart for GUI deployment
- `automation/gcp_gke/assets/gui/Dockerfile` - GUI image build (gateway-only)
- `automation/gcp_gke/assets/gui/nginx.conf` - SPA nginx config

## Quick start

```bash
noetl run automation/gcp_gke/noetl_gke_fresh_stack.yaml \
  --set action=provision-deploy \
  --set project_id=<gcp-project-id> \
  --set region=us-central1 \
  --set cluster_name=noetl-gke \
  --set gui_gateway_public_url=https://gateway.example.com \
  --set noetl_public_host=api.example.com \
  --set gateway_public_host=gateway.example.com \
  --set gui_public_host=gui.example.com
```

## Actions

- `provision` - enable APIs, optional Artifact Registry, create GKE cluster
- `deploy` - deploy full stack to existing cluster
- `provision-deploy` - provision cluster then deploy stack
- `status` - show stack status in cluster
- `destroy` - uninstall stack and optionally delete cluster
