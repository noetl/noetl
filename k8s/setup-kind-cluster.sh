#!/bin/bash

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}NoETL Kind Cluster Setup${NC}"
echo -e "Creates a Kind cluster with local repository mounted"
echo

if ! command -v kind &> /dev/null; then
    echo -e "${RED}Error: kind is not installed or not in PATH${NC}"
    echo -e "Install Kind: https://kind.sigs.k8s.io/docs/user/quick-start/"
    exit 1
fi

if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}Error: kubectl is not installed or not in PATH${NC}"
    echo -e "Install kubectl: https://kubernetes.io/docs/tasks/tools/"
    exit 1
fi

if [ -z "$1" ]; then
    REPO_PATH=$(cd "$(dirname "$0")/.." && pwd)
    echo -e "${YELLOW}No repository path provided. Using current directory: ${REPO_PATH}${NC}"
else
    REPO_PATH=$(cd "$1" && pwd)
    if [ $? -ne 0 ]; then
        echo -e "${RED}Error: Invalid repository path: $1${NC}"
        exit 1
    fi
    echo -e "${YELLOW}Using repository path: ${REPO_PATH}${NC}"
fi

if [ ! -f "${REPO_PATH}/pyproject.toml" ] || [ ! -d "${REPO_PATH}/noetl" ]; then
    echo -e "${RED}Error: The specified path does not appear to be a valid NoETL repository.${NC}"
    echo -e "Provide the path to your NoETL repository."
    exit 1
fi

CONFIG_FILE="${REPO_PATH}/k8s/kind-config-with-mounts.yaml"
echo -e "${YELLOW}Creating Kind configuration file at: ${CONFIG_FILE}${NC}"

cat > "${CONFIG_FILE}" << EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraPortMappings:
  - containerPort: 30080
    hostPort: 30080
    protocol: TCP
  - containerPort: 30081
    hostPort: 30081
    protocol: TCP
  - containerPort: 30082
    hostPort: 30082
    protocol: TCP
  - containerPort: 30083
    hostPort: 30083
    protocol: TCP
  - containerPort: 30084
    hostPort: 30084
    protocol: TCP
  extraMounts:
  - hostPath: ${REPO_PATH}
    containerPath: /noetl-repo
EOF

echo -e "${GREEN}Kind configuration created with repository path.${NC}"

EXISTING_CLUSTER=$(kind get clusters 2>/dev/null | grep noetl-cluster || true)
if [ -n "$EXISTING_CLUSTER" ]; then
    echo -e "${YELLOW}A Kind cluster named 'noetl-cluster' already exists.${NC}"
    read -p "Do you want to delete it and create a new one? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Deleting existing cluster...${NC}"
        kind delete cluster --name noetl-cluster
    else
        echo -e "${RED}Aborted. Delete the cluster manually if needed:${NC}"
        echo -e "${YELLOW}kind delete cluster --name noetl-cluster${NC}"
        exit 1
    fi
fi

echo -e "${YELLOW}Creating Kind cluster with repository mounted...${NC}"
kind create cluster --name noetl-cluster --config "${CONFIG_FILE}"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}Kind cluster created.${NC}"
    echo
    echo -e "${GREEN}Next steps:${NC}"
    echo -e "1. Verify the repository is mounted in the Kind container:"
    echo -e "   ${YELLOW}docker exec -it noetl-cluster-control-plane ls /noetl-repo${NC}"
    echo
    echo -e "2. Deploy NoETL using supported options (pip or local-dev). See: ${YELLOW}k8s/docs/README.md${NC}"
else
    echo -e "${RED}Failed to create Kind cluster. Please check the error messages above.${NC}"
    exit 1
fi