#!/bin/bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}Testing NoETL Development Port Configuration${NC}"
echo "This script validates the port configuration for NoETL deployments."

# Check if kubectl is installed
if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}Error: kubectl is not installed.${NC}"
    echo "Install kubectl."
    exit 1
fi

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Validate the deployment YAML files
echo -e "${GREEN}Validating NoETL deployment YAML files...${NC}"

# Test the regular deployment YAML
echo -e "${GREEN}Testing noetl-deployment.yaml...${NC}"
kubectl apply --dry-run=client -f "${SCRIPT_DIR}/noetl/noetl-deployment.yaml"
if [ $? -eq 0 ]; then
    echo -e "${GREEN}noetl-deployment.yaml is valid.${NC}"
    # Check the port configuration
    PORT=$(grep -A1 "containerPort:" "${SCRIPT_DIR}/noetl/noetl-deployment.yaml" | tail -1 | awk '{print $2}')
    echo -e "${GREEN}Regular NoETL deployment uses port: ${PORT}${NC}"
else
    echo -e "${RED}Error: noetl-deployment.yaml is invalid.${NC}"
    exit 1
fi

# Test the development deployment YAML
echo -e "${GREEN}Testing noetl-dev-deployment.yaml...${NC}"
kubectl apply --dry-run=client -f "${SCRIPT_DIR}/noetl/noetl-dev-deployment.yaml"
if [ $? -eq 0 ]; then
    echo -e "${GREEN}noetl-dev-deployment.yaml is valid.${NC}"
    # Check the port configuration
    DEV_PORT=$(grep -A1 "containerPort:" "${SCRIPT_DIR}/noetl/noetl-dev-deployment.yaml" | tail -1 | awk '{print $2}')
    echo -e "${GREEN}Development NoETL deployment uses port: ${DEV_PORT}${NC}"
else
    echo -e "${RED}Error: noetl-dev-deployment.yaml is invalid.${NC}"
    exit 1
fi

# Validate the service YAML files
echo -e "${GREEN}Validating NoETL service YAML files...${NC}"

# Test the regular service YAML
echo -e "${GREEN}Testing noetl-service.yaml...${NC}"
kubectl apply --dry-run=client -f "${SCRIPT_DIR}/noetl/noetl-service.yaml"
if [ $? -eq 0 ]; then
    echo -e "${GREEN}noetl-service.yaml is valid.${NC}"
    # Check the port configuration
    SERVICE_PORT=$(grep -A1 "port:" "${SCRIPT_DIR}/noetl/noetl-service.yaml" | tail -1 | awk '{print $2}')
    NODE_PORT=$(grep -A1 "nodePort:" "${SCRIPT_DIR}/noetl/noetl-service.yaml" | tail -1 | awk '{print $2}')
    echo -e "${GREEN}Regular NoETL service uses port: ${SERVICE_PORT}, nodePort: ${NODE_PORT}${NC}"
else
    echo -e "${RED}Error: noetl-service.yaml is invalid.${NC}"
    exit 1
fi

# Test the development service YAML
echo -e "${GREEN}Testing noetl-dev-service.yaml...${NC}"
kubectl apply --dry-run=client -f "${SCRIPT_DIR}/noetl/noetl-dev-service.yaml"
if [ $? -eq 0 ]; then
    echo -e "${GREEN}noetl-dev-service.yaml is valid.${NC}"
    # Check the port configuration
    DEV_SERVICE_PORT=$(grep -A1 "port:" "${SCRIPT_DIR}/noetl/noetl-dev-service.yaml" | tail -1 | awk '{print $2}')
    DEV_NODE_PORT=$(grep -A1 "nodePort:" "${SCRIPT_DIR}/noetl/noetl-dev-service.yaml" | tail -1 | awk '{print $2}')
    echo -e "${GREEN}Development NoETL service uses port: ${DEV_SERVICE_PORT}, nodePort: ${DEV_NODE_PORT}${NC}"
else
    echo -e "${RED}Error: noetl-dev-service.yaml is invalid.${NC}"
    exit 1
fi

# Check for port conflicts
echo -e "${GREEN}Checking for port conflicts...${NC}"
if [ "${PORT}" = "${DEV_PORT}" ]; then
    echo -e "${RED}Error: Container port conflict detected! Both deployments use port ${PORT}.${NC}"
    exit 1
else
    echo -e "${GREEN}No container port conflicts detected.${NC}"
fi

if [ "${SERVICE_PORT}" = "${DEV_SERVICE_PORT}" ]; then
    echo -e "${RED}Error: Service port conflict detected! Both services use port ${SERVICE_PORT}.${NC}"
    exit 1
else
    echo -e "${GREEN}No service port conflicts detected.${NC}"
fi

if [ "${NODE_PORT}" = "${DEV_NODE_PORT}" ]; then
    echo -e "${RED}Error: NodePort conflict detected! Both services use nodePort ${NODE_PORT}.${NC}"
    exit 1
else
    echo -e "${GREEN}No NodePort conflicts detected.${NC}"
fi

echo -e "${GREEN}All tests passed!${NC}"
echo "The port configuration for NoETL deployments is valid and should not have conflicts."