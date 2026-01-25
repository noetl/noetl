# Analytics Stack (Superset + JupyterLab) on Kind

This document explains how to provision and access Apache Superset and JupyterLab in a local Kind Kubernetes cluster for analytics and ML exploration of NoETL executions.

Both tools are deployed into a dedicated Kubernetes namespace `analytics` and can access the existing Postgres database (and other in-cluster services) via cluster DNS. Postgres manifests are kept separate in the `postgres` namespace.

## Prerequisites

- Local Kind cluster created for this project
- Postgres deployed to the cluster (provided in this repo)

Quick checks and setup:

```bash
# Create Kind cluster (if not present)
noetl run automation/infrastructure/kind.yaml --set action=create

# Deploy Postgres (required for Superset metadata and your analytics sources)
noetl run automation/infrastructure/postgres.yaml --set action=deploy
```

## Provisioning

Deploy the analytics stack (Superset + JupyterLab):

```bash
noetl run automation/infrastructure/jupyterlab.yaml --set action=deploy
```

This applies the following manifests:
- `ci/manifests/analytics/namespace.yaml`
- Superset: `ci/manifests/analytics/superset/{secret.yaml,deployment.yaml,service.yaml}`
- JupyterLab: `ci/manifests/analytics/jupyterlab/{secret.yaml,deployment.yaml,service.yaml}`

Remove the analytics stack:

```bash
noetl run automation/infrastructure/jupyterlab.yaml --set action=remove
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

### Kind port mappings (host - cluster)

The Kind cluster is configured to forward these NodePorts to the same ports on your localhost:

- Superset: 30888 - 30888
- JupyterLab: 30999 - 30999

Configuration lives in `ci/kind/config.yaml` under `extraPortMappings` and is applied when the cluster is created. If your Kind cluster existed before these mappings were added, recreate it to apply:

```bash
noetl run automation/infrastructure/kind.yaml --set action=delete
noetl run automation/infrastructure/kind.yaml --set action=create
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
noetl run automation/infrastructure/jupyterlab.yaml --set action=deploy
```

Note: Current values are for local development only. Rotate in real environments.

## Troubleshooting

Basic checks:

```bash
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

## Files Reference

- Manifests under `ci/manifests/analytics/`
- JupyterLab playbook: `automation/infrastructure/jupyterlab.yaml`

## Execution analysis notebook (Jupyter)

An exploratory dashboard-style notebook is provided to analyze NoETL playbook executions stored in Postgres:

- Location in repo: `tests/fixtures/notebooks/regression_dashboard.py`
- It is a Jupyter-friendly Python script with `#%%` cells (works in JupyterLab, VS Code, PyCharm).
- What it shows:
  - Recent runs overview and final statuses
  - KPIs (success/error counts, median duration)
  - Failures by step (top offenders)
  - Slowest steps by duration percentiles
  - Drill-down timeline (Gantt-like) for a selected execution

Dependencies (install inside JupyterLab or your local venv):

```bash
pip install pandas sqlalchemy psycopg2-binary plotly
```

Connectivity:
- By default, it reads DB params from `tests/fixtures/credentials/pg_local.json` (in-cluster DNS).
- It has an automatic fallback to `localhost:54321` (Kind NodePort) with `demo:demo` user for `demo_noetl` DB.

How to run:
1. Open JupyterLab at http://localhost:30999.
2. Upload `tests/fixtures/notebooks/regression_dashboard.py` (or mount your repo into the pod).
3. Open it and execute the cells. Adjust parameters at the top (playbook path, lookback window) as needed.

Or run locally in your IDE with a Jupyter kernel; verify Postgres is reachable on `localhost:54321`.
