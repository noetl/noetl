#!/bin/bash

# Script to verify NoETL metrics endpoints are accessible
set -e

echo "Checking NoETL metrics endpoints..."

# Check if pods are running
echo "NoETL Server pods:"
kubectl get pods -n noetl -l app=noetl

echo "NoETL Worker pods:"
kubectl get pods -n noetl -l app=noetl-worker

# Get first server pod
SERVER_POD=$(kubectl get pods -n noetl -l app=noetl -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [ -n "$SERVER_POD" ]; then
    echo "Testing metrics endpoint on server pod $SERVER_POD..."
    kubectl exec -n noetl "$SERVER_POD" -- curl -s http://localhost:8082/metrics | head -20
else
    echo "No server pods found!"
fi

# Get first worker pod
WORKER_POD=$(kubectl get pods -n noetl -l app=noetl-worker -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [ -n "$WORKER_POD" ]; then
    echo "Testing metrics endpoint on worker pod $WORKER_POD..."
    kubectl exec -n noetl "$WORKER_POD" -- curl -s http://localhost:8082/metrics | head -20
else
    echo "No worker pods found!"
fi

# Check VMPodScrape resources
echo "Checking VMPodScrape resources:"
kubectl get vmpodscrape -n observability

# Check VMAgent targets
echo "Checking VMAgent targets (if available):"
kubectl logs -n observability -l app.kubernetes.io/name=vmagent --tail=50 | grep -i "target\|scrape\|error" || echo "No VMAgent logs found"
