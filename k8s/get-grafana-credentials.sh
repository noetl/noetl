#!/bin/bash
# Quick script to get Grafana credentials for NoETL deployments
# Supports both unified and legacy deployments

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}NoETL Grafana Credentials${NC}"
echo

# Check for unified deployment first
if kubectl get ns noetl-platform >/dev/null 2>&1; then
    echo -e "${YELLOW}Found unified deployment (noetl-platform namespace)${NC}"
    ./k8s/observability/grafana-credentials.sh noetl-platform
elif kubectl get ns observability >/dev/null 2>&1; then
    echo -e "${YELLOW}Found legacy deployment (observability namespace)${NC}"
    ./k8s/observability/grafana-credentials.sh observability
else
    echo -e "${RED}No NoETL deployment found.${NC}"
    echo
    echo "To deploy NoETL with observability:"
    echo -e "  ${YELLOW}Unified deployment (recommended):${NC} ./k8s/deploy-unified-platform.sh"
    echo -e "  ${YELLOW}Legacy deployment:${NC} make observability-deploy"
    echo
    exit 1
fi

echo -e "\n${GREEN}Available observability UIs:${NC}"
echo -e "  - Grafana Dashboard: ${YELLOW}http://localhost:3000${NC}"
echo -e "  - VictoriaMetrics:   ${YELLOW}http://localhost:8428/vmui/${NC}"
echo -e "  - VictoriaLogs:      ${YELLOW}http://localhost:9428${NC}"
echo
echo -e "${YELLOW}Note: Port-forwards may need to be started:${NC}"
echo -e "  make unified-port-forward-start     ${GREEN}# For unified deployment${NC}"
echo -e "  make observability-port-forward-start ${GREEN}# For legacy deployment${NC}"