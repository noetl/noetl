# JupyterLab for NoETL Regression Testing

Quick reference for using JupyterLab to run and analyze NoETL regression tests.

## Quick Start

```bash
# Deploy JupyterLab to kind cluster
noetl run automation/infrastructure/jupyterlab.yaml --set action=full
```

## Access

- **URL**: http://localhost:30888
- **Token**: `noetl`
- **Notebook**: `/work/notebooks/regression_dashboard.ipynb`

## Run Test

1. Open notebook in browser
2. Click "Run" -> "Run All Cells"
3. Watch real-time execution monitoring
4. Review results and visualizations

## Common Tasks

```bash
# Check status
noetl run automation/infrastructure/jupyterlab.yaml --set action=status

# View logs
noetl run automation/infrastructure/jupyterlab.yaml --set action=logs

# Restart
noetl run automation/infrastructure/jupyterlab.yaml --set action=restart

# Update notebook
noetl run automation/infrastructure/jupyterlab.yaml --set action=update-notebook

# Remove deployment
noetl run automation/infrastructure/jupyterlab.yaml --set action=undeploy
```

## Tech Stack

- **psycopg3** - PostgreSQL connections
- **DuckDB** - SQL analytics engine
- **Polars** - Fast DataFrames
- **PyArrow** - Columnar data format
- **Plotly** - Interactive visualizations

## What the Notebook Does

1. Starts master regression test (53 steps expected)
2. Monitors execution in real-time
3. Analyzes events with DuckDB
4. Validates results (step count, completion, failures)
5. Detects and analyzes errors
6. Creates performance visualizations
7. Shows historical trends
8. Exports results to Parquet

## Expected Results

- **Steps**: 53/53 completed
- **Duration**: ~60-120 seconds
- **Events**: ~400-500 total
- **Status**: PASSED (playbook_completed event present)

## Troubleshooting

```bash
# Pod not ready
kubectl get pods -n noetl -l app=jupyterlab

# Connection issues
noetl run automation/infrastructure/jupyterlab.yaml --set action=shell
# Then test connections inside pod

# Package errors
noetl run automation/infrastructure/jupyterlab.yaml --set action=restart
```

## Documentation

Full documentation: `docs/jupyterlab_regression_testing.md`
