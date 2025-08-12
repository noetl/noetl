#!/bin/bash

# Script to easily port-forward the Postgres database from Kubernetes to local machine
# Usage: ./postgres-port-forward.sh [local_port]

LOCAL_PORT=${1:-5432}

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}Postgres Port Forwarding Utility${NC}"
echo -e "This script will forward Postgres port from Kubernetes to local machine"
echo

if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}Error: kubectl is not installed or not in PATH${NC}"
    exit 1
fi

echo -e "${YELLOW}Finding Postgres pod...${NC}"
POSTGRES_POD=$(kubectl get pods -l app=postgres -o jsonpath="{.items[0].metadata.name}" 2>/dev/null)

if [ -z "$POSTGRES_POD" ]; then
    echo -e "${RED}Error: Postgres pod not found. Is the database deployed?${NC}"
    echo "Run 'kubectl get pods' to check available pods."
    exit 1
fi

echo -e "${GREEN}Found Postgres pod: ${YELLOW}$POSTGRES_POD${NC}"

if netstat -tuln | grep -q ":$LOCAL_PORT "; then
    echo -e "${RED}Error: Port $LOCAL_PORT is already in use on local machine.${NC}"
    echo "Try a different port: ./postgres-port-forward.sh <different_port>"
    exit 1
fi

echo -e "${GREEN}Starting port forwarding from local port ${YELLOW}$LOCAL_PORT${GREEN} to Postgres port 5432...${NC}"
echo -e "To stop port forwarding, press ${YELLOW}Ctrl+C${NC}"
echo
echo -e "${GREEN}Connection details:${NC}"
echo -e "  Host: ${YELLOW}localhost${NC}"
echo -e "  Port: ${YELLOW}$LOCAL_PORT${NC}"
echo -e "  User: ${YELLOW}demo${NC}"
echo -e "  Database: ${YELLOW}demo_noetl${NC}"
echo -e "  Password: ${YELLOW}demo${NC}"
echo
echo -e "${GREEN}Example connection command:${NC}"
echo -e "  ${YELLOW}psql -h localhost -p $LOCAL_PORT -U demo -d demo_noetl${NC}"
echo

kubectl port-forward pod/$POSTGRES_POD $LOCAL_PORT:5432