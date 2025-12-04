#!/bin/bash
# check_logs.sh - Quick log checker for debugging

echo "=== NoETL Worker Logs (last 50 lines) ==="
kubectl logs -n noetl deployment/noetl-worker --tail=50

echo ""
echo "=== NoETL Server Logs (last 50 lines) ==="
kubectl logs -n noetl deployment/noetl-server --tail=50

echo ""
echo "=== Checking for recent container jobs ==="
kubectl get jobs -n noetl -l noetl.io/component=container

echo ""
echo "=== Checking for recent container pods ==="
kubectl get pods -n noetl -l noetl.io/component=container

echo ""
echo "=== Checking NoETL queue ==="
kubectl exec -n postgres deployment/postgres -- psql -U demo -d demo_noetl -c "SELECT id, step_name, status, created_at FROM noetl.queue ORDER BY created_at DESC LIMIT 10;"

echo ""
echo "=== Checking NoETL events ==="
kubectl exec -n postgres deployment/postgres -- psql -U demo -d demo_noetl -c "SELECT event_id, event_type, step_name, status, created_at FROM noetl.event ORDER BY created_at DESC LIMIT 10;"

echo ""
echo "=== Testing worker can reach PostgreSQL ==="
WORKER_POD=$(kubectl get pods -n noetl -l app=noetl-worker -o jsonpath='{.items[0].metadata.name}')
echo "Worker pod: $WORKER_POD"
kubectl exec -n noetl "$WORKER_POD" -- nslookup postgres.postgres.svc.cluster.local

echo ""
echo "=== Checking if worker has kubernetes Python library ==="
kubectl exec -n noetl "$WORKER_POD" -- python3 -c "import kubernetes; print('kubernetes module available')" 2>&1 || echo "ERROR: kubernetes module not found"
