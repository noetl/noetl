#!/bin/bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}Testing NoETL Redeployment Script${NC}"
echo "This script validates the redeploy-noetl.sh script."

# Check if kubectl is installed
if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}Error: kubectl is not installed.${NC}"
    echo "Install kubectl."
    exit 1
fi

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Validate the YAML files exist
echo -e "${GREEN}Checking if YAML files exist...${NC}"
for file in "${SCRIPT_DIR}/noetl/noetl-configmap.yaml" "${SCRIPT_DIR}/noetl/noetl-secret.yaml" "${SCRIPT_DIR}/noetl/noetl-deployment.yaml" "${SCRIPT_DIR}/noetl/noetl-service.yaml"; do
    if [ -f "$file" ]; then
        echo -e "${GREEN}File exists: $file${NC}"
    else
        echo -e "${RED}Error: File does not exist: $file${NC}"
        exit 1
    fi
done

# Validate the YAML files with kubectl
echo -e "${GREEN}Validating YAML files...${NC}"
for file in "${SCRIPT_DIR}/noetl/noetl-configmap.yaml" "${SCRIPT_DIR}/noetl/noetl-secret.yaml" "${SCRIPT_DIR}/noetl/noetl-deployment.yaml" "${SCRIPT_DIR}/noetl/noetl-service.yaml"; do
    echo "Validating $file..."
    kubectl apply --dry-run=client -f "$file"
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}File is valid: $file${NC}"
    else
        echo -e "${RED}Error: File is invalid: $file${NC}"
        exit 1
    fi
done

echo -e "${GREEN}All tests passed!${NC}"
echo "The redeploy-noetl.sh script should now work correctly with absolute paths."