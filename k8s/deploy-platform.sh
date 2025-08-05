#!/bin/bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}NoETL Kubernetes Deployment Script${NC}"
echo "Set up a Kind cluster and deploy NoETL and Postgres."

if ! command -v kind &> /dev/null; then
    echo -e "${RED}Error: kind is not installed.${NC}"
    echo "See k8s/KIND-README.md for instructions."
    exit 1
fi

if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}Error: kubectl is not installed.${NC}"
    echo "Install kubectl."
    exit 1
fi

echo -e "${GREEN}Creating Kind configuration file...${NC}"
cat > kind-config.yaml << EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraPortMappings:
  - containerPort: 30080
    hostPort: 30080
    protocol: TCP
EOF

echo -e "${GREEN}Creating Kind cluster...${NC}"
kind create cluster --name noetl-cluster --config kind-config.yaml

echo -e "${GREEN}Creating directory for persistent volume...${NC}"
docker exec noetl-cluster-control-plane mkdir -p /mnt/data

echo -e "${GREEN}Deploying Postgres...${NC}"
kubectl apply -f postgres/postgres-pv.yaml
kubectl apply -f postgres/postgres-configmap.yaml
kubectl apply -f postgres/postgres-config-files.yaml
kubectl apply -f postgres/postgres-secret.yaml
kubectl apply -f postgres/postgres-deployment.yaml
kubectl apply -f postgres/postgres-service.yaml

echo -e "${GREEN}Waiting for Postgres to be ready...${NC}"
sleep 10
echo "Checking for Postgres pods..."
kubectl get pods -l app=postgres
kubectl wait --for=condition=ready pod -l app=postgres --timeout=180s || {
    echo -e "${RED}Error: Postgres pods not ready. Checking pod status...${NC}"
    kubectl get pods
    echo -e "${YELLOW}Continuing with deployment anyway...${NC}"
}

echo -e "${GREEN}Deploying NoETL...${NC}"
kubectl apply -f noetl/noetl-configmap.yaml
kubectl apply -f noetl/noetl-secret.yaml
kubectl apply -f noetl/noetl-deployment.yaml
kubectl apply -f noetl/noetl-service.yaml

echo -e "${GREEN}Waiting for NoETL to be ready...${NC}"
# Give Kubernetes some time to create the pods
sleep 10
# Check if pods exist
echo "Checking for NoETL pods..."
kubectl get pods -l app=noetl
# Wait for pods to be ready
kubectl wait --for=condition=ready pod -l app=noetl --timeout=180s || {
    echo -e "${RED}Error: NoETL pods not ready. Checking pod status...${NC}"
    kubectl get pods
    echo -e "${YELLOW}Continuing anyway...${NC}"
}

# Show status
echo -e "${GREEN}Deployment completed successfully!${NC}"
echo -e "${YELLOW}Cluster Status:${NC}"
kubectl get pods
kubectl get services

echo -e "${GREEN}NoETL is now available at:${NC}"
echo -e "  - Web UI: ${YELLOW}http://localhost:30080${NC}"
echo -e "  - API: ${YELLOW}http://localhost:30080/api${NC}"

echo -e "${GREEN}To delete the cluster when you're done:${NC}"
echo -e "  ${YELLOW}kind delete cluster --name noetl-cluster${NC}"