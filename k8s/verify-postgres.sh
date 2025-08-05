#!/bin/bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' 

echo -e "${YELLOW}Postgres Verification Script${NC}"
echo "Verify that Postgres is running correctly."

if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}Error: kubectl is not installed.${NC}"
    echo "Install kubectl."
    exit 1
fi

if ! kubectl cluster-info &> /dev/null; then
    echo -e "${RED}Error: Cannot connect to Kubernetes cluster.${NC}"
    echo "Verify that cluster is running and kubectl is properly configured."
    exit 1
fi

echo -e "${GREEN}Checking Postgres pod status...${NC}"
POSTGRES_POD=$(kubectl get pod -l app=postgres -o jsonpath="{.items[0].metadata.name}" 2>/dev/null)

if [ -z "$POSTGRES_POD" ]; then
    echo -e "${RED}Error: No Postgres pod found.${NC}"
    echo "Deploy Postgres."
    exit 1
fi

POD_STATUS=$(kubectl get pod $POSTGRES_POD -o jsonpath="{.status.phase}")
CONTAINER_READY=$(kubectl get pod $POSTGRES_POD -o jsonpath="{.status.containerStatuses[0].ready}")

echo -e "Pod name: ${YELLOW}$POSTGRES_POD${NC}"
echo -e "Pod status: ${YELLOW}$POD_STATUS${NC}"
echo -e "Container ready: ${YELLOW}$CONTAINER_READY${NC}"

if [ "$POD_STATUS" != "Running" ]; then
    echo -e "${RED}Error: Postgres pod is not running.${NC}"
    echo -e "Pod status details:"
    kubectl describe pod $POSTGRES_POD
    exit 1
fi

if [ "$CONTAINER_READY" != "true" ]; then
    echo -e "${RED}Error: Postgres container is not ready.${NC}"
    echo -e "Container logs:"
    kubectl logs $POSTGRES_POD
    exit 1
fi

echo -e "${GREEN}Checking Postgres service...${NC}"
POSTGRES_SERVICE=$(kubectl get service postgres -o name 2>/dev/null)

if [ -z "$POSTGRES_SERVICE" ]; then
    echo -e "${RED}Error: Postgres service not found.${NC}"
    exit 1
fi

echo -e "Postgres service: ${YELLOW}$POSTGRES_SERVICE${NC}"

echo -e "${GREEN}Checking Postgres logs for errors...${NC}"
POSTGRES_LOGS=$(kubectl logs $POSTGRES_POD 2>/dev/null | grep -i "error\|fatal" | tail -10)

if [ -n "$POSTGRES_LOGS" ]; then
    echo -e "${YELLOW}Warning: Found potential errors in Postgres logs:${NC}"
    echo "$POSTGRES_LOGS"
else
    echo -e "${GREEN}No errors found in Postgres logs.${NC}"
fi

echo -e "${GREEN}Testing Postgres connection from within the pod...${NC}"
CONNECTION_TEST=$(kubectl exec $POSTGRES_POD -- psql -U $POSTGRES_USER -d $POSTGRES_DB -c "SELECT 1" 2>/dev/null)

if [ $? -eq 0 ]; then
    echo -e "${GREEN}Successfully connected to Postgres database.${NC}"
else
    echo -e "${RED}Error: Could not connect to Postgres database.${NC}"
    echo "This could be due to authentication issues or database not being ready."
    echo "Check the environment variables and Postgres configuration."
fi

echo -e "\n${GREEN}Postgres Verification Summary:${NC}"
echo -e "- Pod status: ${YELLOW}$POD_STATUS${NC}"
echo -e "- Container ready: ${YELLOW}$CONTAINER_READY${NC}"
echo -e "- Service available: ${YELLOW}$([ -n "$POSTGRES_SERVICE" ] && echo "Yes" || echo "No")${NC}"

if [ "$POD_STATUS" == "Running" ] && [ "$CONTAINER_READY" == "true" ] && [ -n "$POSTGRES_SERVICE" ]; then
    echo -e "\n${GREEN}Postgres appears to be running correctly.${NC}"
else
    echo -e "\n${RED}Postgres verification failed. Please check the issues above.${NC}"
    exit 1
fi