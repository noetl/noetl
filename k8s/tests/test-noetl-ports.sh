#!/bin/bash

# Test script to verify that both noetl and noetl-dev deployments can run simultaneously
# without port conflicts

echo "Testing NoETL port configuration..."

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo "Error: kubectl is not installed or not in PATH"
    exit 1
fi

# Apply the configurations
echo "Applying NoETL configurations..."

# Apply standard NoETL deployment
echo "Deploying standard NoETL..."
kubectl apply -f noetl/namespaces.yaml
kubectl apply -n noetl -f noetl/noetl-configmap.yaml
kubectl apply -n noetl -f noetl/noetl-secret.yaml
kubectl apply -n noetl -f noetl/noetl-deployment.yaml
kubectl apply -n noetl -f noetl/noetl-service.yaml

for ns in noetl-worker-cpu-01 noetl-worker-cpu-02 noetl-worker-gpu-01; do
    kubectl apply -n "$ns" -f noetl/noetl-configmap.yaml
    kubectl apply -n "$ns" -f noetl/noetl-secret.yaml
done

kubectl apply -f noetl/noetl-worker-deployments.yaml

# Apply development NoETL deployment
echo "Deploying development NoETL..."
kubectl apply -f noetl/noetl-dev-deployment.yaml
kubectl apply -f noetl/noetl-dev-service.yaml

# Wait for pods to be ready
echo "Waiting for pods to be ready..."
kubectl wait -n noetl --for=condition=ready pod -l app=noetl --timeout=120s
kubectl wait --for=condition=ready pod -l app=noetl-dev --timeout=120s
for ns in noetl-worker-cpu-01 noetl-worker-cpu-02 noetl-worker-gpu-01; do
    kubectl wait -n "$ns" --for=condition=ready pod -l component=worker --timeout=120s || true
done

# Check if both services are running
echo "Checking services..."
kubectl get services -A | grep noetl

# Check if both pods are running
echo "Checking pods..."
kubectl get pods -A | grep noetl

# Check if the ports are accessible
echo "Testing standard NoETL endpoint (port 30082)..."
curl -s http://localhost:30082/health || echo "Failed to access standard NoETL"

echo "Testing development NoETL endpoint (port 30080)..."
curl -s http://localhost:30080/api/health || echo "Failed to access development NoETL"

echo "Test completed."
