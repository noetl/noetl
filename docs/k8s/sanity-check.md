# NoETL Kubernetes Sanity Check (Manual Steps)

This guide walks you through a complete manual sanity check for NoETL on Kubernetes. It includes resetting the Postgres schema, rebuilding/redeploying NoETL with the new separated build scripts, and validating the updated API with partition-based TTL system.

Use this when you need to manually verify changes end-to-end.

## Recent Updates
- **Separated Build Scripts**: Independent build/load scripts for NoETL and PostgreSQL components
- **Partition-based TTL**: Daily partitioned metric table with 1-day TTL enforcement via partition dropping
- **Improved Development Workflow**: Faster iteration cycles by building only changed components

## Prerequisites
- A working Kubernetes cluster/context (Kind or other) with NoETL deployed.
- Postgres accessible via kubectl port-forward (default: localhost:30543).
- .env configured for database access variables if using the Makefile target:
  - POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
  - NOETL_SCHEMA (optional, defaults to noetl)
- Python virtualenv for the local CLI if needed: .venv/bin/noetl
- jq and curl installed (for endpoint checks)

## 1) Ensure Postgres port-forward is running

Check an existing background port-forward for Postgres (Kind default shown):

```bash
ps aux | grep "kubectl.*port-forward.*30543" | grep -v grep
```

If it is not running, you can start it via your own command or using repo helpers, e.g.

```bash
make k8s-postgres-port-forward-bg NAMESPACE=postgres
# or interactively
make k8s-postgres-port-forward NAMESPACE=postgres
```

## 2) Reset the Postgres schema

Preferred: use the Makefile target (drops and recreates the schema):

```bash
make postgres-reset-schema
```

Equivalent verbose manual sequence:

```bash
set -a; [ -f .env ] && . .env; set +a; \
  export PGHOST=$POSTGRES_HOST PGPORT=$POSTGRES_PORT PGUSER=$POSTGRES_USER PGPASSWORD=$POSTGRES_PASSWORD PGDATABASE=$POSTGRES_DB; \
  echo "Dropping schema ${NOETL_SCHEMA:-noetl}..."; \
  psql -v ON_ERROR_STOP=1 -c "DROP SCHEMA IF EXISTS ${NOETL_SCHEMA:-noetl} CASCADE;"

# Apply schema using the NoETL CLI (ensures role exists and runs packaged DDL)
.venv/bin/noetl db apply-schema --ensure-role
```

## 3) Rebuild and redeploy NoETL components

### Option A: Full rebuild (both NoETL and PostgreSQL)

Use the automated redeployment script:

```bash
./k8s/redeploy-noetl.sh
```

### Option B: NoETL-only rebuild (recommended for code changes)

Build only NoETL images (faster for development):

```bash
./docker/build-noetl-images.sh
```

Load only NoETL images into Kind:

```bash
./k8s/load-noetl-images.sh
```

### Option C: PostgreSQL-only rebuild (for schema changes)

Build only PostgreSQL image:

```bash
./docker/build-postgres-image.sh
```

Load only PostgreSQL image into Kind:

```bash
./k8s/load-postgres-image.sh
```

### Restart deployments (after any build option)

Restart NoETL server and worker deployments to pick up new images:

```bash
kubectl rollout restart deployment/noetl -n noetl

kubectl rollout restart deployment/noetl-worker-cpu-01 -n noetl-worker-cpu-01 && \
kubectl rollout restart deployment/noetl-worker-cpu-02 -n noetl-worker-cpu-02 && \
kubectl rollout restart deployment/noetl-worker-gpu-01 -n noetl-worker-gpu-01
```

Wait for server to become available:

```bash
kubectl wait --for=condition=available --timeout=60s deployment/noetl -n noetl
```

## 4) Validate API health and partition-based TTL features

Health check:

```bash
curl -s http://localhost:30082/api/health | jq
```

Trigger partition-based TTL cleanup (drops partitions older than 1 day):

```bash
curl -s -X POST http://localhost:30082/api/metrics/cleanup | jq
```

Set a custom TTL for a specific metric name:

```bash
curl -s -X POST "http://localhost:30082/api/metrics/ttl/set?metric_name=test_metric&ttl_days=14" | jq
```

Create upcoming daily partitions:

```bash
curl -s -X POST "http://localhost:30082/api/metrics/partitions/create?days_ahead=3" | jq
```

List current partitions:

```bash
curl -s http://localhost:30082/api/metrics/partitions | jq
```

## 5) Verify database schema (Python async check)

This script prints the "noetl.metric" table structure and lists TTL-related functions:

```bash
cd /Users/kadyapam/projects/noetl/noetl && .venv/bin/python -c "
import asyncio
import psycopg
from noetl.core.common import get_async_db_connection

async def check_schema():
    async with get_async_db_connection() as conn:
        async with conn.cursor() as cur:
            # Check metric table structure (partitioned)
            await cur.execute('''
                SELECT column_name, data_type, is_nullable, column_default 
                FROM information_schema.columns 
                WHERE table_schema = 'noetl' AND table_name = 'metric'
                ORDER BY ordinal_position
            ''')
            columns = await cur.fetchall()
            print('Metric table structure (partitioned by date):')
            for col_name, col_type, nullable, default in columns:
                print(f'  {col_name}: {col_type} (nullable: {nullable}, default: {default})')
            
            # Check existing partitions
            await cur.execute('''
                SELECT schemaname, tablename 
                FROM pg_tables 
                WHERE schemaname = 'noetl' AND tablename LIKE 'metric_%' 
                ORDER BY tablename
            ''')
            partitions = await cur.fetchall()
            print(f'\nExisting metric partitions ({len(partitions)} found):')
            for schema, table in partitions:
                print(f'  {schema}.{table}')

            # Check TTL and partition management functions
            await cur.execute('''
                SELECT routine_name 
                FROM information_schema.routines 
                WHERE routine_schema = 'noetl' 
                AND (routine_name LIKE '%metric%' OR routine_name LIKE '%partition%')
                ORDER BY routine_name
            ''')
            functions = await cur.fetchall()
            print('\nTTL and partition management functions:')
            for (func_name,) in functions:
                print(f'  {func_name}')

asyncio.run(check_schema())
"
```

## Expected outcomes
- **Partitioned metric table**: `noetl.metric` with daily partitions (e.g., `metric_20250929`)
- **Partition-based TTL**: 1-day retention enforced by dropping old partitions
- **TTL functions available**: `cleanup_expired_metrics`, `set_metric_ttl`, `extend_component_metrics_ttl`, `create_metric_partition`, `drop_old_metric_partitions`
- **Separated build workflow**: Independent NoETL and PostgreSQL image building
- **API endpoints responding**: Health, metrics, TTL, and partition management endpoints working
- **Grafana dashboards updated**: Server and worker dashboards showing PostgreSQL metrics
- **PostgreSQL datasource working**: Grafana can query NoETL metrics from database
- **Real-time metrics visibility**: CPU, memory, queue depth, worker status in dashboards

## Notes

- **Separated Build Scripts**: Use `./docker/build-noetl-images.sh` and `./k8s/load-noetl-images.sh` for faster NoETL-only builds during development
- **Partition-based TTL**: The system now uses daily partitions with 1-day retention, significantly improving cleanup performance
- **Schema Reset**: The Makefile target `postgres-reset-schema` encapsulates the safe reset flow and falls back to local DDL if needed
- **Namespace Configuration**: Namespaces shown above reflect typical defaults in this repo; adjust if your deployment uses different namespaces
- **Development Efficiency**: The new separated workflow reduces build times from minutes to seconds for NoETL code changes


## 6) Partition management and TTL verification

### Create upcoming daily partitions

Create partitions for the next 3 days:

```bash
curl -s -X POST "http://localhost:30082/api/metrics/partitions/create?days_ahead=3" | jq
```

### Verify partition-based TTL cleanup

The cleanup endpoint drops entire partitions older than 1 day for fast TTL enforcement:

```bash
curl -s -X POST http://localhost:30082/api/metrics/cleanup | jq
```

Expected response includes:
- `dropped_partitions`: List of partition names that were dropped (may be empty if no old partitions exist)
- `cleanup_time`: Timestamp when cleanup was performed
- `retention_policy`: Current retention settings

### Test development workflow efficiency

For typical NoETL code changes, use the faster separated build:

```bash
time ./docker/build-noetl-images.sh --no-local-dev
time ./k8s/load-noetl-images.sh --no-local-dev
```

This should be significantly faster than rebuilding all images including PostgreSQL.

## 7) Deploy updated Grafana dashboards and datasources

### Apply updated datasources configuration

The new PostgreSQL datasource enables Grafana to query NoETL metrics directly from the database:

```bash
kubectl apply -f k8s/observability/grafana-datasources-configmap.yaml
```

### Provision updated dashboards

Deploy the enhanced server and worker dashboards with PostgreSQL metrics panels:

```bash
k8s/observability/provision-grafana.sh
```

### Restart Grafana to pick up datasource changes

```bash
kubectl rollout restart deployment/vmstack-grafana -n noetl-platform
```

Wait for Grafana to restart:

```bash
kubectl wait --for=condition=available --timeout=60s deployment/vmstack-grafana -n noetl-platform
```

### Verify dashboard deployment

Check that the dashboards are properly provisioned:

```bash
kubectl get configmaps -n noetl-platform | grep dashboard
```

Expected output should show dashboard ConfigMaps:
```
noetl-server-dashboard-cm    1      <timestamp>
noetl-workers-dashboard-cm   1      <timestamp>
```

### Access updated dashboards

1. **Set up Grafana port-forward** (if not already running):
   ```bash
   kubectl port-forward -n noetl-platform svc/vmstack-grafana 3000:80 &
   ```

2. **Access Grafana** at http://localhost:3000
   - Username: `admin`
   - Password: `admin`

3. **Navigate to dashboards**:
   - Go to **Dashboards** → **Browse** → **NoETL** folder
   - Open **"NoETL Server Overview"** - should show new PostgreSQL-based metrics
   - Open **"NoETL Worker Pools"** - should show worker stats, CPU/memory usage, and status tables

### Verify new metrics panels

In the **NoETL Server Overview** dashboard, you should see:
- **Active Components**: Count from runtime table
- **CPU Usage by Component**: Time-series from PostgreSQL metrics
- **Memory Usage by Component**: Time-series from PostgreSQL metrics  
- **Active Workers**: Table with color-coded status
- **Queue Depth Over Time**: Job queue metrics
- **Latest Metrics Summary**: Recent metrics from all components

In the **NoETL Worker Pools** dashboard, you should see:
- **Stats panels**: Active Workers, Total Capacity, Pending/Running Jobs
- **Resource monitoring**: CPU and Memory usage over time per worker
- **Worker Status Details**: Comprehensive worker information table
- **Performance metrics**: Active tasks and job processing rates

## Troubleshooting

### Check partition creation

If partitions aren't being created automatically, verify the partition management functions:

```bash
psql -h localhost -p 30543 -U noetl -d noetl -c "SELECT noetl.create_metric_partition('2025-09-30');"
```

### Verify TTL enforcement

Insert test data and verify cleanup:

```bash
# Insert test metric with specific date
curl -X POST "http://localhost:30082/api/metrics" \
  -H "Content-Type: application/json" \
  -d '{"component": "test", "metric_name": "test_metric", "metric_value": 42, "timestamp": "2025-09-27T10:00:00Z"}'

# Run cleanup to remove old partitions
curl -s -X POST http://localhost:30082/api/metrics/cleanup | jq
```

### Grafana dashboard issues

If dashboards show "No data" or connection errors:

1. **Check PostgreSQL datasource connection**:
   ```bash
   # Test PostgreSQL port-forward is working
   psql -h localhost -p 30543 -U noetl -d noetl -c "SELECT 1;"
   ```

2. **Verify datasource configuration in Grafana**:
   - Go to **Configuration** → **Data Sources** → **NoETL PostgreSQL**
   - Click **Test** button - should show "Database Connection OK"
   - Check the connection URL is correct: `postgres.postgres.svc.cluster.local:5432`

3. **Check if metrics exist in database**:
   ```bash
   psql -h localhost -p 30543 -U noetl -d noetl -c "SELECT COUNT(*) FROM noetl.metric;"
   ```

4. **Restart Grafana sidecar to reload dashboards**:
   ```bash
   kubectl delete pod -l app.kubernetes.io/name=grafana -n noetl-platform
   ```

5. **Check Grafana logs for errors**:
   ```bash
   kubectl logs deployment/vmstack-grafana -n noetl-platform -c grafana
   ```

6. **Verify dashboard ConfigMaps are labeled correctly**:
   ```bash
   kubectl get cm -n noetl-platform -l grafana_dashboard=1
   ```

If metrics panels show "No data points":
- Ensure NoETL components are running and reporting metrics
- Check that metrics exist: `curl -s http://localhost:30082/api/metrics/query | jq`
- Verify time range in dashboard covers period when metrics were collected
