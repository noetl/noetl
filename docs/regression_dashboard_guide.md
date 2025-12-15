# Regression Dashboard Deployment Guide

## Overview

The regression dashboard notebook has been updated with modern Python data stack:
- **psycopg3** - Modern PostgreSQL adapter (NOT psycopg2)
- **DuckDB** - SQL analytics engine for fast queries
- **Polars** - High-performance DataFrame library
- **PyArrow** - Columnar data format
- **Plotly** - Interactive visualizations

## Quick Start

### 1. Deploy JupyterLab to Kind Cluster

```bash
# Deploy using existing taskfile
task jupyterlab:deploy

# Wait for pod to be ready
kubectl wait --for=condition=ready pod -l app=jupyterlab -n noetl --timeout=300s
```

### 2. Access JupyterLab

```bash
# Access via NodePort
open http://localhost:30888

# Or use port-forward
kubectl port-forward -n noetl svc/jupyterlab 8888:8888
open http://localhost:8888
```

**Login:** Token is `noetl`

### 3. Open Regression Dashboard

Navigate to: `work/notebooks/regression_dashboard.ipynb`

### 4. Run Tests

Execute cells sequentially:
1. **Setup** - Imports and configuration
2. **Database Connection** - Test connectivity  
3. **Execute Test** - Start master regression test
4. **Monitor** - Real-time progress tracking
5. **Analyze** - DuckDB-powered event analysis
6. **Validate** - Comprehensive test validation
7. **Visualize** - Performance charts and timelines
8. **Debug** - Error detection and recovery analysis
9. **Historical** - Trend analysis over time
10. **Export** - Save results to Parquet

## Notebook Features

### Real-Time Monitoring
- Polls execution status every 5 seconds
- Shows step progress (X/53)
- Detects completion or failures
- Calculates events per second

### DuckDB Analytics
```python
# Example: Event analysis with DuckDB
ddb = init_duckdb_with_postgres()
result = ddb.execute("""
    SELECT event_type, COUNT(*) 
    FROM noetl_db.noetl.event 
    WHERE execution_id = 123
    GROUP BY event_type
""").pl()  # Returns Polars DataFrame
```

### Polars Data Processing
```python
# High-performance DataFrame operations
df = query_to_polars("SELECT * FROM noetl.event LIMIT 10000")
summary = df.group_by('event_type').agg([
    pl.col('node_name').count().alias('count'),
    pl.col('created_at').min().alias('first_event')
])
```

### PyArrow Export
```python
# Efficient columnar export
events_arrow = ddb.execute("SELECT * FROM noetl.event").arrow()
pq.write_table(events_arrow, "events.parquet")
```

## Validation Checks

The notebook performs comprehensive validation:

1. **Playbook Completion** - Checks for `playbook_completed` event
2. **Step Count** - Validates all 53 steps executed
3. **Failure Recovery** - Detects unrecovered failures
4. **Child Playbooks** - Validates sub-playbook completions
5. **Performance** - Calculates duration and throughput

## Error Detection

Automatic error analysis includes:
- All failure events with timestamps
- Retry/recovery tracking
- Detailed error messages
- Step-by-step failure timeline
- Recovery status for each failed step

## Visualizations

Interactive Plotly charts:
- **Event Timeline** - Scatter plot of all events
- **Step Duration** - Horizontal bar chart (top 20 slowest)
- **Event Distribution** - Pie chart of event types
- **Historical Trends** - Success rate over time
- **Duration Trends** - Performance over time

## Kubernetes Configuration

The deployment uses:
- **Namespace**: `noetl` (same as NoETL server)
- **Service**: NodePort 30888
- **Database**: `postgres.postgres.svc.cluster.local:5432`
- **Credentials**: demo/demo/demo_noetl
- **Server**: `noetl-server.noetl.svc.cluster.local:8080`

## Troubleshooting

### Check JupyterLab Status
```bash
task jupyterlab:status
```

### View Logs
```bash
task jupyterlab:logs
```

### Test Database Connection
```bash
task jupyterlab:test-connection
```

### Restart JupyterLab
```bash
task jupyterlab:restart
```

### Shell Access
```bash
task jupyterlab:shell
```

## Advanced Usage

### Export Results for Analysis
```python
# Results are automatically exported to:
/opt/noetl/data/test_results/
  - test_{execution_id}_events.parquet
  - test_{execution_id}_validation.json
```

### Historical Analysis
The notebook queries last 7 days of test runs:
- Success rate percentage
- Average duration
- Average steps completed
- Trend visualizations

### Custom Queries
Use DuckDB for ad-hoc analysis:
```python
ddb = init_duckdb_with_postgres()
custom_df = ddb.execute("""
    SELECT 
        node_name,
        AVG(duration) as avg_duration
    FROM (
        SELECT 
            node_name,
            EXTRACT(EPOCH FROM (end_time - start_time)) as duration
        FROM ...
    )
    GROUP BY node_name
    ORDER BY avg_duration DESC
""").pl()
```

## Next Steps

1. **Scheduling** - Set up cron job to run tests daily
2. **Alerting** - Integrate with monitoring system
3. **CI/CD** - Add to deployment pipeline
4. **Reports** - Generate HTML reports from exports
5. **Metrics** - Push to Prometheus/Grafana

## Summary

✅ **Notebook Updated** - Modern stack (psycopg3, DuckDB, Polars, Arrow)  
✅ **K8s Ready** - Configured for Kubernetes deployment  
✅ **Comprehensive** - Full test execution, monitoring, and analysis  
✅ **Production-Ready** - Error handling, validation, and export
