# NoETL Redeployment Guide - Preserving Observability Services

## Quick Start (Automated)

### Option 1: Use the Makefile Target (Recommended)
```bash
cd /Users/kadyapam/projects/noetl/noetl
make redeploy-noetl
```

### Option 2: Use the Script Directly
```bash
cd /Users/kadyapam/projects/noetl/noetl
./k8s/redeploy-noetl.sh
```

This script will:
1. ✅ Create a backup of current PostgreSQL data
2. ✅ Rebuild Docker images with latest metrics code
3. ✅ Load new images into Kind cluster
4. ✅ Redeploy PostgreSQL with updated schema (includes metrics table)
5. ✅ Redeploy NoETL server with metrics functionality
6. ✅ Redeploy workers with metrics reporting
7. ✅ Verify metrics endpoints are working
8. ✅ Preserve all observability services (VictoriaMetrics, Grafana, etc.)

---

## Manual Step-by-Step (If you prefer manual control)

### Step 1: Rebuild Images
```bash
cd /Users/kadyapam/projects/noetl/noetl

# Build new images with metrics functionality
./docker/build-images.sh --no-pip --tag latest

# Load images into Kind cluster
kind load docker-image noetl-local-dev:latest --name noetl-cluster
kind load docker-image postgres-noetl:latest --name noetl-cluster
```

### Step 2: Backup Current Data (Optional but recommended)
```bash
# Create backup directory
mkdir -p backup/$(date +%Y%m%d_%H%M%S)

# Get postgres pod name
POSTGRES_POD=$(kubectl get pods -l app=postgres -o jsonpath='{.items[0].metadata.name}')

# Create database dump
kubectl exec "$POSTGRES_POD" -- pg_dump -U noetl noetl > backup/$(date +%Y%m%d_%H%M%S)/noetl_backup.sql
```

### Step 3: Redeploy PostgreSQL with Updated Schema
```bash
# Remove existing PostgreSQL
kubectl delete deployment postgres --ignore-not-found=true
kubectl wait --for=delete pod -l app=postgres --timeout=60s

# Redeploy with updated schema (includes metrics table)
kubectl apply -f k8s/postgres/postgres-configmap.yaml
kubectl apply -f k8s/postgres/postgres-config-files.yaml
kubectl apply -f k8s/postgres/postgres-secret.yaml
kubectl apply -f k8s/postgres/postgres-deployment.yaml

# Wait for PostgreSQL to be ready
kubectl wait --for=condition=available deployment/postgres --timeout=300s
sleep 30  # Allow time for database initialization
```

### Step 4: Redeploy NoETL Server
```bash
# Remove existing NoETL server
kubectl delete deployment -n noetl noetl --ignore-not-found=true
kubectl wait -n noetl --for=delete pod -l app=noetl --timeout=60s

# Apply server configuration and deployment
kubectl apply -f k8s/noetl/namespaces.yaml
kubectl apply -n noetl -f k8s/noetl/noetl-configmap.yaml
kubectl apply -n noetl -f k8s/noetl/noetl-secret.yaml
kubectl apply -n noetl -f k8s/noetl/noetl-deployment.yaml
kubectl apply -n noetl -f k8s/noetl/noetl-service.yaml

# Wait for server to be ready
kubectl wait -n noetl --for=condition=available deployment/noetl --timeout=300s
```

### Step 5: Redeploy NoETL Workers
```bash
# Remove existing workers
for ns in noetl-worker-cpu-01 noetl-worker-cpu-02 noetl-worker-gpu-01; do
    kubectl delete deployment -n "$ns" --all --ignore-not-found=true
    kubectl wait -n "$ns" --for=delete pod -l component=worker --timeout=60s || true
done

# Apply worker configurations
for ns in noetl-worker-cpu-01 noetl-worker-cpu-02 noetl-worker-gpu-01; do
    kubectl apply -n "$ns" -f k8s/noetl/noetl-configmap.yaml
    kubectl apply -n "$ns" -f k8s/noetl/noetl-secret.yaml
done

# Apply worker deployments
kubectl apply -f k8s/noetl/noetl-worker-deployments.yaml

# Wait for workers to be ready
for ns in noetl-worker-cpu-01 noetl-worker-cpu-02 noetl-worker-gpu-01; do
    kubectl wait -n "$ns" --for=condition=available deployment --all --timeout=300s || true
done
```

---

## Verification Steps

### Check Deployment Status
```bash
# Check PostgreSQL
kubectl get pods -l app=postgres

# Check NoETL server
kubectl get pods -n noetl -l app=noetl

# Check workers
kubectl get pods -n noetl-worker-cpu-01 -l component=worker
kubectl get pods -n noetl-worker-cpu-02 -l component=worker
kubectl get pods -n noetl-worker-gpu-01 -l component=worker

# Verify observability services are untouched
kubectl get pods -n noetl-platform
```

### Test Metrics Functionality
```bash
# Get NoETL server pod
NOETL_POD=$(kubectl get pods -n noetl -l app=noetl -o jsonpath='{.items[0].metadata.name}')

# Test Prometheus metrics endpoint
kubectl exec -n noetl "$NOETL_POD" -- curl -s http://localhost:8082/api/metrics/prometheus

# Test self-report endpoint
kubectl exec -n noetl "$NOETL_POD" -- curl -s -X POST http://localhost:8082/api/metrics/self-report

# Check database for metrics table
kubectl exec -n noetl "$NOETL_POD" -- python -c "
from noetl.core.common import get_db_connection
with get_db_connection() as conn:
    with conn.cursor() as cur:
        cur.execute('SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = %s AND table_name = %s', ('noetl', 'metrics'))
        print(f'Metrics table exists: {cur.fetchone()[0] > 0}')
"
```

### Verify Metrics Collection
```bash
# Wait a few minutes for metrics to be collected, then check
sleep 120

# Query metrics from database
kubectl exec -n noetl "$NOETL_POD" -- python -c "
from noetl.core.common import get_db_connection
with get_db_connection() as conn:
    with conn.cursor() as cur:
        cur.execute('SELECT COUNT(*) FROM noetl.metrics')
        count = cur.fetchone()[0]
        print(f'Total metrics collected: {count}')
        
        cur.execute('SELECT DISTINCT component_name FROM noetl.runtime WHERE component_type IN (%s, %s, %s)', 
                   ('server_api', 'worker_pool', 'queue_worker'))
        components = cur.fetchall()
        print(f'Registered components: {[c[0] for c in components]}')
"
```

---

## Important Notes

### What This Preserves
- ✅ **VictoriaMetrics stack** (vmagent, vmcluster, vmalert)
- ✅ **Grafana** with existing dashboards
- ✅ **All observability namespaces** (`noetl-platform`)
- ✅ **Existing monitoring configurations**
- ✅ **Port forwards and service configurations**

### What This Updates
- 🔄 **PostgreSQL schema** (adds metrics table)
- 🔄 **NoETL server** (with metrics API endpoints)
- 🔄 **NoETL workers** (with metrics reporting)
- 🔄 **Docker images** (rebuilt with latest code)

### New Functionality Available
- 📊 **Metrics API**: `/api/metrics/*` endpoints
- 📈 **Prometheus export**: `/api/metrics/prometheus`
- 📋 **Database storage**: `noetl.metrics` table
- 🔄 **Automatic collection**: Workers report every 60 seconds
- 🖥️ **Server metrics**: CPU, memory, worker count, queue size
- 👷 **Worker metrics**: CPU, memory, active tasks, queue size

---

## Troubleshooting

### If PostgreSQL Fails to Start
```bash
# Check logs
kubectl logs -l app=postgres

# Check if schema update is needed
kubectl exec -l app=postgres -- psql -U noetl -c "\dt noetl.*"
```

### If NoETL Server Fails to Start
```bash
# Check server logs
kubectl logs -n noetl -l app=noetl

# Check if metrics endpoints are accessible
kubectl exec -n noetl -l app=noetl -- curl http://localhost:8082/health
```

### If Workers Fail to Start
```bash
# Check worker logs in each namespace
kubectl logs -n noetl-worker-cpu-01 -l component=worker
kubectl logs -n noetl-worker-cpu-02 -l component=worker
kubectl logs -n noetl-worker-gpu-01 -l component=worker
```

### If Metrics Not Appearing
```bash
# Check if runtime table has components registered
kubectl exec -n noetl -l app=noetl -- python -c "
from noetl.core.common import get_db_connection
with get_db_connection() as conn:
    with conn.cursor() as cur:
        cur.execute('SELECT name, component_type, status FROM noetl.runtime')
        for row in cur.fetchall():
            print(f'{row[0]} ({row[1]}): {row[2]}')
"

# Check if metrics table exists and has data
kubectl exec -n noetl -l app=noetl -- python -c "
from noetl.core.common import get_db_connection
with get_db_connection() as conn:
    with conn.cursor() as cur:
        cur.execute('SELECT COUNT(*) FROM noetl.metrics')
        print(f'Metrics count: {cur.fetchone()[0]}')
"
```

---

## Next Steps After Deployment

### 1. Configure VictoriaMetrics Scraping
The observability stack should automatically discover and scrape the new metrics endpoint at `/api/metrics/prometheus`. If not, check:
```bash
kubectl get vmpodscrape -A
kubectl get vmservicescrape -A
```

### 2. Verify Grafana Integration
Access Grafana and verify that NoETL metrics are available:
```bash
kubectl port-forward -n noetl-platform svc/vmstack-grafana 3000:80
# Open http://localhost:3000
```

### 3. Monitor Metrics Collection
Watch for metrics being collected over time:
```bash
# Monitor metrics growth
watch "kubectl exec -n noetl -l app=noetl -- python -c \"
from noetl.core.common import get_db_connection
with get_db_connection() as conn:
    with conn.cursor() as cur:
        cur.execute('SELECT COUNT(*) FROM noetl.metrics WHERE created_at > now() - interval \\'5 minutes\\'')
        print(f'Recent metrics: {cur.fetchone()[0]}')
\""
```