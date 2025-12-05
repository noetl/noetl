# Analytics Stack (Superset + JupyterLab) on Kind

This document explains how to provision and access Apache Superset and JupyterLab in a local Kind Kubernetes cluster for analytics and ML exploration of NoETL executions.

Both tools are deployed into a dedicated Kubernetes namespace `analytics` and can access the existing Postgres database (and other in-cluster services) via cluster DNS. Postgres manifests are kept separate in the `postgres` namespace.

## Prerequisites

- Local Kind cluster created for this project
- Postgres deployed to the cluster (provided in this repo)
- Taskfile CLI installed (`go-task`)

Quick checks and setup:

```bash
# Create Kind cluster (if not present)
task kind:local:cluster-create

# Deploy Postgres (required for Superset metadata and your analytics sources)
task postgres:k8s:deploy
```

## Provisioning

Deploy the analytics stack (Superset + JupyterLab):

```bash
task analytics:k8s:deploy
```

This applies the following manifests:
- `ci/manifests/analytics/namespace.yaml`
- Superset: `ci/manifests/analytics/superset/{secret.yaml,deployment.yaml,service.yaml}`
- JupyterLab: `ci/manifests/analytics/jupyterlab/{secret.yaml,deployment.yaml,service.yaml}`

Remove the analytics stack:

```bash
task analytics:k8s:remove
```

## Access

For local Kind usage we expose NodePorts.

- Superset UI: http://localhost:30888
  - Default admin: `admin` / `admin`
  - Change these in `ci/manifests/analytics/superset/secret.yaml`

- JupyterLab UI: http://localhost:30999
  - Default token: `noetl`
  - Change token in `ci/manifests/analytics/jupyterlab/secret.yaml`

If the ports conflict on your host, update `nodePort` values in the corresponding `Service` manifests and re-apply.

### Kind port mappings (host ↔ cluster)

The Kind cluster is configured to forward these NodePorts to the same ports on your localhost:

- Superset: 30888 → 30888
- JupyterLab: 30999 → 30999

Configuration lives in `ci/kind/config.yaml` under `extraPortMappings` and is applied when the cluster is created. If your Kind cluster existed before these mappings were added, recreate it to apply:

```bash
task kind:local:cluster-delete
task kind:local:cluster-create
```

If you change NodePort values in the Service manifests, also update `ci/kind/config.yaml` accordingly and recreate the cluster so the new host mappings take effect.

## Connectivity to Postgres and Other Databases

Superset uses the existing Postgres as its metadata database. The connection string is configured via the secret and uses cross-namespace DNS:

```
postgresql+psycopg2://demo:demo@postgres.postgres.svc.cluster.local:5432/demo_noetl
```

From JupyterLab notebooks, you can connect to the same Postgres using the same DNS name. Example (Python):

```python
import sqlalchemy as sa

engine = sa.create_engine(
    "postgresql+psycopg2://demo:demo@postgres.postgres.svc.cluster.local:5432/demo_noetl"
)

with engine.connect() as conn:
    rows = conn.execute(sa.text("select now()"))
    print(list(rows))
```

Install libraries inside the Jupyter environment as needed, for example:

```bash
pip install psycopg2-binary sqlalchemy pandas
```

To connect to other in-cluster databases/services, use their Kubernetes service DNS names in the form:

```
<service>.<namespace>.svc.cluster.local
```

## Changing Credentials and Secrets

- Superset admin credentials and `SQLALCHEMY_DATABASE_URI` are in `ci/manifests/analytics/superset/secret.yaml`.
- JupyterLab access token is in `ci/manifests/analytics/jupyterlab/secret.yaml`.

Edit the files as needed and redeploy:

```bash
task analytics:k8s:deploy
```

Note: Current values are for local development only. Rotate in real environments.

## Troubleshooting

Basic checks:

```bash
# Ensure correct kubectl context
task kubectl:local:context-set-kind

# Check pods
kubectl get pods -n analytics

# Wait for readiness (example for Superset)
kubectl wait --for=condition=ready pod -l app=superset -n analytics --timeout=180s

# Inspect logs
kubectl logs -n analytics deploy/superset
kubectl logs -n analytics deploy/jupyterlab
```

If Superset fails to start, verify that the Postgres service is reachable from the `analytics` namespace:

```bash
kubectl run -it --rm pgcheck --image=postgres:17 -n analytics -- bash
apt-get update && apt-get install -y dnsutils
nslookup postgres.postgres.svc.cluster.local
psql "postgresql://demo:demo@postgres.postgres.svc.cluster.local:5432/demo_noetl" -c 'select 1'
```

## Files and Tasks Reference

- Manifests under `ci/manifests/analytics/`
- Taskfile: `ci/taskfile/analytics.yml`
- Top-level shortcuts in `taskfile.yml`:
  - `task analytics:k8s:deploy`
  - `task analytics:k8s:remove`
