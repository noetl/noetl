#!/bin/bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

WORKER_NAMESPACES=(
    "noetl-worker-cpu-01"
    "noetl-worker-cpu-02"
    "noetl-worker-gpu-01"
)

echo -e "${YELLOW}NoETL Redeployment Script${NC}"
echo "This script will redeploy NoETL in the existing Kind cluster."
echo -e "If you encounter issues, please check the logs for troubleshooting."

if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}Error: kubectl is not installed.${NC}"
    echo "Install kubectl first."
    exit 1
fi

if ! kubectl cluster-info &> /dev/null; then
    echo -e "${RED}Error: Cannot connect to Kubernetes cluster.${NC}"
    echo "Make sure your cluster is running and kubectl is properly configured."
    exit 1
fi

echo -e "${GREEN}Removing existing NoETL deployment...${NC}"
if kubectl get namespace noetl >/dev/null 2>&1; then
    kubectl delete deployment -n noetl noetl --ignore-not-found=true || true
    kubectl wait -n noetl --for=delete pod -l app=noetl --timeout=60s || true
fi
for ns in "${WORKER_NAMESPACES[@]}"; do
    if kubectl get namespace "$ns" >/dev/null 2>&1; then
        kubectl delete deployment -n "$ns" --all --ignore-not-found=true || true
        kubectl wait -n "$ns" --for=delete pod -l component=worker --timeout=60s || true
    fi
done

echo -e "${GREEN}Redeploying NoETL...${NC}"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
kubectl apply -f ${SCRIPT_DIR}/noetl/namespaces.yaml
kubectl apply -n noetl -f ${SCRIPT_DIR}/noetl/noetl-configmap.yaml
kubectl apply -n noetl -f ${SCRIPT_DIR}/noetl/noetl-secret.yaml
kubectl apply -n noetl -f ${SCRIPT_DIR}/noetl/noetl-deployment.yaml
kubectl apply -n noetl -f ${SCRIPT_DIR}/noetl/noetl-service.yaml

for ns in "${WORKER_NAMESPACES[@]}"; do
    kubectl apply -n "$ns" -f ${SCRIPT_DIR}/noetl/noetl-configmap.yaml
    kubectl apply -n "$ns" -f ${SCRIPT_DIR}/noetl/noetl-secret.yaml
done

kubectl apply -f ${SCRIPT_DIR}/noetl/noetl-worker-deployments.yaml

echo -e "${GREEN}Waiting for NoETL to be ready...${NC}"
sleep 10
echo "Checking for NoETL pods..."
kubectl get pods -n noetl -l app=noetl
kubectl wait -n noetl --for=condition=ready pod -l app=noetl --timeout=180s || {
    echo -e "${RED}Error: NoETL pods not ready. Checking pod status...${NC}"
    kubectl get pods -n noetl -l app=noetl
    echo -e "${YELLOW}Please check the logs for more information:${NC}"
    echo -e "${YELLOW}kubectl -n noetl logs -l app=noetl${NC}"
}

echo -e "${GREEN}Checking NoETL worker pools...${NC}"
for ns in "${WORKER_NAMESPACES[@]}"; do
    echo "Namespace: $ns"
    kubectl get pods -n "$ns" -l component=worker || true
    kubectl wait -n "$ns" --for=condition=ready pod -l component=worker --timeout=180s || {
        echo -e "${YELLOW}Warning: Worker pods are not ready yet in namespace $ns.${NC}"
        kubectl get pods -n "$ns" -l component=worker || true
    }
done

echo -e "${GREEN}Redeployment completed!${NC}"
echo -e "${YELLOW}NoETL Status:${NC}"
kubectl get pods -n noetl -l app=noetl
for ns in "${WORKER_NAMESPACES[@]}"; do
    kubectl get pods -n "$ns" -l component=worker || true
done

echo -e "${GREEN}To check NoETL logs:${NC}"
echo -e "  ${YELLOW}kubectl -n noetl logs -l app=noetl${NC}"
