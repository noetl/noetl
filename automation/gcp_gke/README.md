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
- `automation/gcp_gke/gke_cluster_recreate.yaml`

## Assets in this folder

- `automation/gcp_gke/helm/gui/*` - Helm chart for GUI deployment
- `automation/gcp_gke/assets/noetl/cloudbuild.yaml` - NoETL image build using local source (`docker/noetl/dev/Dockerfile`)
- `automation/gcp_gke/assets/gui/Dockerfile` - GUI image build (gateway-only)
- `automation/gcp_gke/assets/gui/nginx.conf` - SPA nginx config

## Quick start

```bash
noetl run automation/gcp_gke/noetl_gke_fresh_stack.yaml \
  --set action=provision-deploy \
  --set project_id=<gcp-project-id> \
  --set region=us-central1 \
  --set cluster_name=noetl-gke \
  --set gateway_service_type=LoadBalancer \
  --set gateway_load_balancer_ip=34.71.6.63 \
  --set gui_gateway_public_url=https://gateway.example.com \
  --set noetl_public_host=api.example.com \
  --set gateway_public_host=gateway.example.com \
  --set gui_public_host=gui.example.com
```

## Multi-domain CORS

Gateway CORS is now assembled from multiple inputs so it is easier to manage multiple GUI domains:

- `gateway_cors_include_localhost=true` adds `http://localhost:3001`
- `gateway_cors_include_public_hosts=true` adds `https://<gui_public_host>` and `https://<gateway_public_host>`
- `gateway_cors_allowed_origins` accepts comma/space/newline-separated origins or bare domains
- `gateway_cors_allowed_domains` accepts additional bare domains

Example:

```bash
noetl run automation/gcp_gke/noetl_gke_fresh_stack.yaml \
  --set action=deploy \
  --set project_id=<gcp-project-id> \
  --set build_images=false \
  --set gateway_cors_allowed_domains='mestumre.dev,staging.mestumre.dev' \
  --set gateway_cors_allowed_origins='https://preview.mestumre.dev'
```

## Actions

- `provision` - enable APIs, optional Artifact Registry, create GKE cluster
- `deploy` - deploy full stack to existing cluster
- `provision-deploy` - provision cluster then deploy stack
- `status` - show stack status in cluster
- `destroy` - uninstall stack and optionally delete cluster

## Image refresh behavior

- When `build_noetl_image=true`, the deploy playbook now forces `kubectl rollout restart` for:
  - `deployment/noetl-server`
  - `deployment/noetl-worker`
- This guarantees fresh pulls when using mutable tags like `latest`.

## Quota safeguard

Both playbooks run a precheck for `CPUS_ALL_REGIONS` before cluster creation.

- `min_global_cpu_quota` (default `64`) - minimum required global CPU quota
- `enforce_cpu_quota_check` (default `true`) - fail fast if quota is below the minimum

## Cluster-only recreate playbook

Use this when you only want to snapshot/destroy/provision the cluster itself:

```bash
noetl run automation/gcp_gke/gke_cluster_recreate.yaml \
  --set action=recreate \
  --set project_id=<gcp-project-id> \
  --set region=us-central1 \
  --set cluster_name=noetl-cluster
```

Supported actions in `gke_cluster_recreate.yaml`:

- `snapshot` - capture current cluster settings and update blueprint file
- `status` - print current cluster summary
- `destroy` - delete cluster (optional pre-snapshot)
- `provision` - create cluster using blueprint/defaults
- `recreate` - snapshot, destroy, then provision
