#!/bin/bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' 

echo -e "${YELLOW}Postgres Redeployment Script${NC}"
echo "Redeploy Postgres in the existing Kind cluster."
echo -e "If you encounter issues, check ${GREEN}POSTGRES-FIX.md${NC} for troubleshooting."

if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}Error: kubectl is not installed.${NC}"
    echo "Install kubectl."
    exit 1
fi

if ! kubectl cluster-info &> /dev/null; then
    echo -e "${RED}Error: Cannot connect to Kubernetes cluster.${NC}"
    echo "Make sure your cluster is running and kubectl is properly configured."
    exit 1
fi

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo -e "${GREEN}Removing existing Postgres deployment...${NC}"
kubectl delete deployment postgres --ignore-not-found=true
echo "Waiting for Postgres pods to terminate..."
kubectl wait --for=delete pod -l app=postgres --timeout=60s || true

echo -e "${GREEN}Redeploying Postgres...${NC}"
kubectl apply -f "${SCRIPT_DIR}/postgres/postgres-configmap.yaml"
kubectl apply -f "${SCRIPT_DIR}/postgres/postgres-config-files.yaml"
kubectl apply -f "${SCRIPT_DIR}/postgres/postgres-secret.yaml"
kubectl apply -f "${SCRIPT_DIR}/postgres/postgres-deployment.yaml"

echo -e "${GREEN}Waiting for Postgres to be ready...${NC}"
sleep 10
echo "Checking for Postgres pods..."
kubectl get pods -l app=postgres
kubectl wait --for=condition=ready pod -l app=postgres --timeout=180s || {
    echo -e "${RED}Error: Postgres pods not ready. Checking pod status...${NC}"
    kubectl get pods -l app=postgres
    echo -e "${YELLOW}Check the logs for more information:${NC}"
    echo -e "${YELLOW}kubectl logs -l app=postgres${NC}"
}

echo -e "${GREEN}Redeployment completed!${NC}"
echo -e "${YELLOW}Postgres Status:${NC}"
kubectl get pods -l app=postgres

echo -e "${GREEN}To check Postgres logs:${NC}"
echo -e "  ${YELLOW}kubectl logs -l app=postgres${NC}"