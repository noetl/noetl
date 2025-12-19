# Notebooks for Execution Analytics

This directory contains Jupyter-friendly notebooks and scripts to analyze NoETL executions stored in Postgres.

## Contents
- `regression_dashboard.py` — Notebook-style Python script (with `#%%` cells) that renders an execution analysis dashboard for regression runs.
- `regression_dashboard.ipynb` — Optional notebook stub; prefer the `.py` version for source control friendliness.

## What the dashboard shows
- Recent runs overview and final statuses
- KPIs (success/error counts, median duration)
- Failures by step (top offenders)
- Slowest steps by duration percentiles (P50/P90)
- Drill-down timeline (Gantt-like) for a selected execution

## Prerequisites
- A Postgres instance populated with NoETL execution data (schema `noetl`).
- If using the provided Kind setup, ensure ports are mapped on the host:
  - Postgres: `localhost:54321` (Kind NodePort 30321 → host 54321)
  - JupyterLab: `http://localhost:30999` (token `noetl`)
- Python packages installed in the Jupyter environment:
  ```bash
  pip install pandas sqlalchemy psycopg2-binary plotly
  ```

## How to run

### Option A: In-cluster JupyterLab (Kind)
1. Provision analytics stack (Superset + JupyterLab): `task analytics:k8s:deploy`.
2. Open `http://localhost:30999` and authenticate (default token: `noetl`).
3. Upload/open `tests/fixtures/notebooks/regression_dashboard.py`.
4. Run cells top-to-bottom. Adjust at the top:
   - `PLAYBOOK_PATH` (default: `tests/fixtures/playbooks/regression_test/master_regression_test.yaml`)
   - `HOURS_BACK`, `LIMIT`

### Option B: Local IDE with Jupyter support (VS Code, PyCharm)
1. Ensure Postgres is reachable on `localhost:54321` (from Kind mappings) or your local DB has NoETL schema/data.
2. Open `regression_dashboard.py` in your IDE with a Jupyter kernel and run the cells.

## Database connectivity
The script reads Postgres connection parameters from `tests/fixtures/credentials/pg_local.json` (in-cluster DNS):

```
postgres.postgres.svc.cluster.local:5432 (user=demo, db=demo_noetl)
```

If that fails, it automatically falls back to:

```
postgresql://demo:demo@localhost:54321/demo_noetl
```

You can override via environment variables: `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE`.

## Troubleshooting
- If plots do not render, ensure the kernel has `plotly` installed and the notebook is trusted.
- If the dashboard shows no data:
  - Verify recent executions exist within `HOURS_BACK`.
  - Check that `PLAYBOOK_PATH` filter matches your catalog paths (or broaden it).
- Connectivity tips:
  - Inside Kind JupyterLab, use the in-cluster DNS from `pg_local.json`.
  - From host, prefer `localhost:54321` (see `ci/kind/config.yaml` port mappings).

## Related docs
- `docs/analytics.md` — Provisioning Superset + JupyterLab and access details.
