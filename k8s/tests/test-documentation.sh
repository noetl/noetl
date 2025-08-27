#!/bin/bash

# Test script to verify the documentation changes
# This script checks that the documentation accurately reflects the behavior of the scripts

# Text colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}Testing NoETL Documentation Accuracy${NC}"
echo

# Check if deploy-platform.sh exists and is executable
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PARENT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEPLOY_SCRIPT="${PARENT_DIR}/deploy-platform.sh"

if [ ! -f "${DEPLOY_SCRIPT}" ]; then
    echo -e "${RED}Error: deploy-platform.sh not found at ${DEPLOY_SCRIPT}${NC}"
    exit 1
fi

echo -e "${GREEN}Found deploy-platform.sh at: ${DEPLOY_SCRIPT}${NC}"

# Check if the script is executable
if [ ! -x "${DEPLOY_SCRIPT}" ]; then
    echo -e "${RED}Error: deploy-platform.sh is not executable${NC}"
    echo -e "Run: chmod +x ${DEPLOY_SCRIPT}"
    exit 1
fi

echo -e "${GREEN}deploy-platform.sh is executable${NC}"

# Check that the script gracefully handles the deprecated --deploy-noetl-reload flag (warns and ignores)
if ! grep -q "--deploy-noetl-reload" "${DEPLOY_SCRIPT}"; then
    echo -e "${RED}Error: deploy-platform.sh should recognize --deploy-noetl-reload (deprecated)${NC}"
    exit 1
fi
if ! grep -q "deprecated and ignored" "${DEPLOY_SCRIPT}"; then
    echo -e "${RED}Error: deploy-platform.sh should warn that --deploy-noetl-reload is deprecated and ignored${NC}"
    exit 1
fi

echo -e "${GREEN}deploy-platform.sh recognizes --deploy-noetl-reload and warns appropriately${NC}"

# README should NOT recommend --deploy-noetl-reload anymore
README_FILE="${PARENT_DIR}/README.md"
if grep -q -- "--deploy-noetl-reload" "${README_FILE}"; then
    echo -e "${RED}Error: README.md should not mention --deploy-noetl-reload (deprecated)${NC}"
    exit 1
fi

echo -e "${GREEN}README.md no longer mentions --deploy-noetl-reload${NC}"

# README should contain the Deprecated/Remove list section with at least one of the files
if ! grep -q "Deprecated and Safe-to-Remove Files" "${README_FILE}"; then
    echo -e "${RED}Error: README.md should include a deprecated/remove section${NC}"
    exit 1
fi
if ! grep -q "deploy-noetl-reload.sh" "${README_FILE}"; then
    echo -e "${RED}Error: README.md deprecated section should list deploy-noetl-reload.sh${NC}"
    exit 1
fi

echo -e "${GREEN}README.md contains the deprecated/remove section and lists reload files${NC}"

echo
echo -e "${GREEN}All documentation tests passed (reload flow deprecated).${NC}"
echo -e "${YELLOW}Docs reflect only supported deployments (pip and local-dev).${NC}"