#!/bin/bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}Testing NoETL Development Deployment Fix${NC}"
echo "This script tests the fix for the ContainerCreating issue in the NoETL development deployment."

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Check if kubectl is installed
if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}Error: kubectl is not installed.${NC}"
    echo "Install kubectl to run this test."
    exit 1
fi

# Apply the deployment
echo -e "${GREEN}Applying the fixed NoETL development deployment...${NC}"
"${SCRIPT_DIR}/deploy-noetl-dev.sh" --type dev

# Wait for the pod to be ready
echo -e "${GREEN}Waiting for the pod to be ready...${NC}"
kubectl wait --for=condition=ready pod -l app=noetl-dev --timeout=300s

if [ $? -eq 0 ]; then
    echo -e "${GREEN}Success! The NoETL development pod is now running.${NC}"
    
    # Get the pod details
    echo -e "${GREEN}Pod details:${NC}"
    kubectl get pods -l app=noetl-dev -o wide
    
    # Check if the service is accessible
    echo -e "${GREEN}Checking if the service is accessible...${NC}"
    if kubectl get service noetl-dev &> /dev/null; then
        echo -e "${GREEN}Service noetl-dev exists.${NC}"
        
        # Try to access the health endpoint
        echo -e "${GREEN}Trying to access the health endpoint...${NC}"
        kubectl port-forward service/noetl-dev 8080:8080 &
        PORT_FORWARD_PID=$!
        sleep 5
        
        if curl -s http://localhost:8080/api/health &> /dev/null; then
            echo -e "${GREEN}Success! The health endpoint is accessible.${NC}"
        else
            echo -e "${YELLOW}Warning: Could not access the health endpoint. This might be due to the service not being fully ready yet.${NC}"
        fi
        
        # Kill the port-forward process
        kill $PORT_FORWARD_PID
    else
        echo -e "${YELLOW}Warning: Service noetl-dev does not exist. You may need to create it.${NC}"
    fi
else
    echo -e "${RED}Error: The NoETL development pod did not become ready within the timeout period.${NC}"
    echo -e "${RED}Checking pod status:${NC}"
    kubectl describe pod -l app=noetl-dev
    exit 1
fi

echo -e "${GREEN}Test completed.${NC}"