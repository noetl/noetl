# JupyterLab Regression Testing Environment

Complete guide for deploying and using JupyterLab for NoETL regression testing.

## Overview

JupyterLab deployment provides an interactive analytics environment for:
- Running master regression tests
- Real-time execution monitoring
- Event analysis with DuckDB
- Performance visualization with Plotly
- Error detection and debugging
- Historical trend analysis

## Technology Stack

- **JupyterLab**: Interactive notebook environment
- **psycopg3**: Modern PostgreSQL adapter
- **DuckDB**: Embedded SQL analytics engine
- **Polars**: High-performance DataFrames (Rust-based)
- **PyArrow**: Columnar data format
- **Plotly**: Interactive visualizations

## Quick Start

### Deploy JupyterLab

```bash
# Complete deployment with testing
task jupyterlab:full

# Or deploy manually
task jupyterlab:deploy
```

### Access JupyterLab

1. **Browser**: http://localhost:30888
2. **Token**: `noetl`
3. **Notebook**: `/work/notebooks/regression_dashboard.ipynb`

### Run Regression Test

1. Open notebook in browser
2. Execute cells in order (or Run All)
3. Monitor test execution in real-time
4. Review results, visualizations, and analysis

## Task Commands

### Deployment

```bash
# Deploy JupyterLab to kind cluster
task jupyterlab:deploy

# Remove JupyterLab
task jupyterlab:undeploy

# Complete workflow (deploy + test)
task jupyterlab:full
```

### Management

```bash
# Check deployment status
task jupyterlab:status

# View logs
task jupyterlab:logs

# Restart deployment
task jupyterlab:restart

# Update notebook and restart
task jupyterlab:update-notebook
```

### Access

```bash
# Port-forward to localhost:8888
task jupyterlab:port-forward

# Open shell in pod
task jupyterlab:shell
```

### Testing

```bash
# Test deployment (readiness, packages, notebook)
task jupyterlab:test
```

## Architecture

### Kubernetes Resources

- **Namespace**: `noetl`
- **Deployment**: `jupyterlab` (1 replica)
- **Service**: `jupyterlab` (NodePort 30888)
- **PVC**: `jupyterlab-pvc` (5Gi storage)
- **ConfigMap**: `jupyterlab-notebooks` (notebook content)

### Environment Variables

Automatically configured for Kubernetes environment:

```yaml
NOETL_SERVER_URL: http://noetl-server.noetl.svc.cluster.local:8080
POSTGRES_HOST: postgres.postgres.svc.cluster.local
POSTGRES_PORT: 5432
POSTGRES_USER: demo
POSTGRES_PASSWORD: demo
POSTGRES_DB: demo_noetl
JUPYTER_TOKEN: noetl
```

### Resource Limits

```yaml
requests:
  memory: 2Gi
  cpu: 500m
limits:
  memory: 4Gi
  cpu: 2000m
```

## Notebook Structure

### 1. Setup and Configuration
- Import modern data stack
- Configure database connection
- Set test parameters

### 2. Database Connection Utilities
- `get_postgres_connection()` - psycopg3 connection
- `query_to_polars()` - Query to Polars DataFrame
- `query_to_arrow()` - Query to PyArrow Table
- `init_duckdb_with_postgres()` - DuckDB with PostgreSQL

### 3. Execute Master Regression Test
- Start test via API
- Capture execution ID

### 4. Real-Time Monitoring
- Poll execution status
- Display progress with step counts
- Detect completion or failure

### 5. Execution Analysis with DuckDB
- Event summary and timing
- Step-by-step duration analysis
- Performance metrics calculation

### 6. Validation and Test Results
- Verify expected step count (53)
- Check completion status
- Validate no unrecovered failures
- Calculate performance metrics

### 7. Error Detection and Debugging
- Identify all error events
- Analyze retry/recovery patterns
- Show detailed error messages

### 8. Performance Visualizations
- Event timeline scatter plot
- Step duration bar chart
- Event type distribution pie chart

### 9. Historical Trend Analysis
- Recent test run history (7 days)
- Success rate calculation
- Duration trends
- Statistical summary

### 10. Export Results & Cleanup
- Export events to Parquet
- Save validation results as JSON
- Close database connections

## Usage Examples

### Running Complete Test

```python
# Cell 3: Start test
test_result = start_regression_test()
EXECUTION_ID = test_result['execution_id']

# Cell 4: Monitor until completion
test_success = monitor_execution(EXECUTION_ID)

# Cell 6: Validate results
validation_result = validate_regression_test(EXECUTION_ID)
```

### Ad-Hoc Analysis

```python
# Query specific execution
execution_id = 511084125059547272

# Analyze with DuckDB
ddb = init_duckdb_with_postgres()
events = ddb.execute(f"""
    SELECT * FROM noetl_db.noetl.event
    WHERE execution_id = {execution_id}
""").pl()

# Create custom visualization
import plotly.express as px
fig = px.scatter(events.to_pandas(), x='created_at', y='event_type')
fig.show()
```

### Historical Analysis

```python
# Compare multiple test runs
history = ddb.execute("""
    SELECT execution_id,
           MIN(created_at) as start_time,
           COUNT(DISTINCT CASE WHEN event_type = 'step_completed' THEN node_name END) as steps
    FROM noetl_db.noetl.event e
    JOIN noetl_db.noetl.catalog c ON e.catalog_id = c.catalog_id
    WHERE c.path = 'tests/fixtures/playbooks/regression_test/master_regression_test'
    GROUP BY execution_id
    ORDER BY start_time DESC
    LIMIT 10
""").pl()

print(history)
```

## Troubleshooting

### Pod Not Starting

```bash
# Check pod status
kubectl get pods -n noetl -l app=jupyterlab

# View pod events
kubectl describe pod -n noetl -l app=jupyterlab

# Check logs
task jupyterlab:logs
```

### Connection Issues

```bash
# Test inside pod
task jupyterlab:shell

# Check PostgreSQL connection
python -c "import psycopg; psycopg.connect('host=postgres.postgres.svc.cluster.local port=5432 dbname=demo_noetl user=demo password=demo')"

# Check NoETL server
curl http://noetl-server.noetl.svc.cluster.local:8080/health
```

### Package Installation Failed

```bash
# Restart deployment to retry installation
task jupyterlab:restart

# Or manually install in pod
task jupyterlab:shell
pip install psycopg[binary] duckdb polars pyarrow plotly
```

### Notebook Not Found

```bash
# Verify ConfigMap exists
kubectl get configmap jupyterlab-notebooks -n noetl -o yaml

# Update notebook
task jupyterlab:update-notebook
```

### Access Issues

```bash
# Check service
kubectl get service jupyterlab -n noetl

# Verify NodePort is accessible
curl http://localhost:30888

# Alternative: port-forward
task jupyterlab:port-forward
```

## CI/CD Integration

### Scheduled Regression Tests

```yaml
# Example CronJob
apiVersion: batch/v1
kind: CronJob
metadata:
  name: regression-test
  namespace: noetl
spec:
  schedule: "0 */6 * * *"  # Every 6 hours
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: test-runner
            image: jupyter/scipy-notebook:latest
            command:
            - jupyter
            - nbconvert
            - --to
            - notebook
            - --execute
            - /work/notebooks/regression_dashboard.ipynb
            volumeMounts:
            - name: notebooks
              mountPath: /work/notebooks
          restartPolicy: OnFailure
          volumes:
          - name: notebooks
            configMap:
              name: jupyterlab-notebooks
```

### Alerting Setup

```python
# Add to notebook for Slack notifications
import requests

def send_slack_alert(validation_result):
    if not validation_result['passed']:
        webhook_url = os.getenv('SLACK_WEBHOOK_URL')
        message = {
            "text": f"❌ Regression test failed - Execution {validation_result['execution_id']}",
            "blocks": [
                {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(validation_result['issues'])}}
            ]
        }
        requests.post(webhook_url, json=message)
```

## Performance Optimization

### DuckDB Query Optimization

```python
# Use DuckDB for large aggregations instead of Polars
# DuckDB pushes down predicates to PostgreSQL

# Good: DuckDB aggregation
result = ddb.execute("""
    SELECT event_type, COUNT(*) as cnt
    FROM noetl_db.noetl.event
    WHERE execution_id = 123
    GROUP BY event_type
""").pl()

# Avoid: Loading all data then aggregating
# events = query_to_polars("SELECT * FROM noetl.event WHERE execution_id = 123")
# result = events.group_by('event_type').count()
```

### Polars for Data Manipulation

```python
# Use Polars for in-memory transformations
df = query_to_polars("SELECT * FROM noetl.event WHERE execution_id = 123")

# Efficient filtering and transformation
result = (df
    .filter(pl.col('event_type').str.contains('completed'))
    .with_columns([
        pl.col('created_at').cast(pl.Datetime).alias('timestamp'),
        pl.col('result').str.json_extract().alias('parsed_result')
    ])
    .sort('timestamp')
)
```

### Arrow for Data Transfer

```python
# Use Arrow for efficient data serialization
events_arrow = query_to_arrow("SELECT * FROM noetl.event")

# Write to Parquet (columnar, compressed)
pq.write_table(events_arrow, 'events.parquet')

# Read efficiently
events_df = pl.read_parquet('events.parquet')
```

## Best Practices

1. **Run tests during low-traffic periods** to avoid impacting production workloads
2. **Archive test results** to Parquet for historical analysis
3. **Set up alerting** for test failures
4. **Monitor resource usage** and adjust limits if needed
5. **Update notebook regularly** with new analysis patterns
6. **Use DuckDB for aggregations**, Polars for transformations
7. **Clean up old test executions** to prevent database bloat

## Next Steps

1. **Integrate with CI/CD**: Add scheduled test runs
2. **Set up monitoring**: Grafana dashboards for test trends
3. **Add alerting**: Slack/email notifications for failures
4. **Expand analysis**: Custom metrics and KPIs
5. **Automate cleanup**: Remove old test data automatically

## References

- [JupyterLab Documentation](https://jupyterlab.readthedocs.io/)
- [DuckDB Documentation](https://duckdb.org/docs/)
- [Polars Documentation](https://pola-rs.github.io/polars/)
- [Plotly Documentation](https://plotly.com/python/)
- [psycopg3 Documentation](https://www.psycopg.org/psycopg3/docs/)
