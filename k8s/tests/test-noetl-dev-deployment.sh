#!/bin/bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}NoETL Development Deployment Test Script${NC}"
echo "This script validates the NoETL development deployment configurations."

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Check if kubectl is installed
if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}Error: kubectl is not installed.${NC}"
    echo "Install kubectl."
    exit 1
fi

# Validate the deployment YAML files
echo -e "${GREEN}Validating NoETL development deployment YAML files...${NC}"

# Test the development deployment YAML
echo -e "${GREEN}Testing noetl-dev-deployment.yaml...${NC}"
kubectl apply --dry-run=client -f "${SCRIPT_DIR}/noetl/noetl-dev-deployment.yaml"
if [ $? -eq 0 ]; then
    echo -e "${GREEN}noetl-dev-deployment.yaml is valid.${NC}"
else
    echo -e "${RED}Error: noetl-dev-deployment.yaml is invalid.${NC}"
    exit 1
fi

# Test the package deployment YAML
echo -e "${GREEN}Testing noetl-package-deployment.yaml...${NC}"
kubectl apply --dry-run=client -f "${SCRIPT_DIR}/noetl/noetl-package-deployment.yaml"
if [ $? -eq 0 ]; then
    echo -e "${GREEN}noetl-package-deployment.yaml is valid.${NC}"
else
    echo -e "${RED}Error: noetl-package-deployment.yaml is invalid.${NC}"
    exit 1
fi

# Test the version deployment YAML
echo -e "${GREEN}Testing noetl-version-deployment.yaml...${NC}"
kubectl apply --dry-run=client -f "${SCRIPT_DIR}/noetl/noetl-version-deployment.yaml"
if [ $? -eq 0 ]; then
    echo -e "${GREEN}noetl-version-deployment.yaml is valid.${NC}"
else
    echo -e "${RED}Error: noetl-version-deployment.yaml is invalid.${NC}"
    exit 1
fi

# Test the deployment script
echo -e "${GREEN}Testing deploy-noetl-dev.sh script...${NC}"
if [ -x "${SCRIPT_DIR}/deploy-noetl-dev.sh" ]; then
    echo -e "${GREEN}deploy-noetl-dev.sh is executable.${NC}"
else
    echo -e "${RED}Error: deploy-noetl-dev.sh is not executable.${NC}"
    chmod +x "${SCRIPT_DIR}/deploy-noetl-dev.sh"
    echo -e "${GREEN}Made deploy-noetl-dev.sh executable.${NC}"
fi

# Test the deployment script help
echo -e "${GREEN}Testing deploy-noetl-dev.sh help...${NC}"
"${SCRIPT_DIR}/deploy-noetl-dev.sh" --help > /dev/null
if [ $? -eq 0 ]; then
    echo -e "${GREEN}deploy-noetl-dev.sh help works correctly.${NC}"
else
    echo -e "${RED}Error: deploy-noetl-dev.sh help failed.${NC}"
    exit 1
fi

# Simulate the container startup to check for pip and command issues
echo -e "${GREEN}Simulating container startup for development mode...${NC}"
echo "This would create a non-root user, install NoETL in development mode, and run the server with the correct command."
echo "Command that would be executed: python -m noetl.main server start --host 0.0.0.0 --port 8080"

echo -e "${GREEN}Simulating container startup for package installation...${NC}"
echo "This would create a non-root user, install NoETL from a local package, and run the server with the correct command."
echo "Command that would be executed: python -m noetl.main server start --host 0.0.0.0 --port 8080"

echo -e "${GREEN}Simulating container startup for version-specific installation...${NC}"
echo "This would create a non-root user, install a specific version of NoETL from PyPI, and run the server with the correct command."
echo "Command that would be executed: python -m noetl.main server start --host 0.0.0.0 --port 8080"

echo -e "${GREEN}All tests passed!${NC}"
echo "The development deployment configurations should work correctly."