#!/bin/bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

CLUSTER_NAME="noetl-cluster"
LOAD_NOETL_PIP=true
LOAD_NOETL_LOCAL_DEV=true
LOAD_POSTGRES=true

function show_usage {
    echo "Usage: $0 [options]"
    echo "Options:"
    echo "  --cluster-name NAME  Name of the Kind cluster. Default: noetl-cluster"
    echo "  --no-pip            Skip loading noetl-pip image"
    echo "  --no-local-dev      Skip loading noetl-local-dev image"
    echo "  --no-postgres        Skip loading postgres-noetl image"
    echo "  --help               Show this help message"
    
    if [ -n "$1" ]; then
        exit 1
    else
        exit 0
    fi
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --cluster-name)
            CLUSTER_NAME="$2"
            shift 2
            ;;
        --no-pip)
            LOAD_NOETL_PIP=false
            shift
            ;;
        --no-local-dev)
            LOAD_NOETL_LOCAL_DEV=false
            shift
            ;;
        --no-postgres)
            LOAD_POSTGRES=false
            shift
            ;;
        --help)
            show_usage
            ;;
        *)
            echo -e "${RED}Error: Unknown option: $1${NC}"
            show_usage "error"
            ;;
    esac
done

echo -e "${YELLOW}NoETL Docker Image Loader for Kind${NC}"
echo "This script will load Docker images into the Kind cluster."
echo

if ! command -v kind &> /dev/null; then
    echo -e "${RED}Error: kind is not installed.${NC}"
    echo "Install kind to use this script."
    exit 1
fi

if ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: docker is not installed.${NC}"
    echo "Install docker to use this script."
    exit 1
fi

if ! kind get clusters | grep -q "^${CLUSTER_NAME}$"; then
    echo -e "${RED}Error: Kind cluster '${CLUSTER_NAME}' does not exist.${NC}"
    echo "Create the cluster first using kind create cluster --name ${CLUSTER_NAME}"
    exit 1
fi

if $LOAD_NOETL_PIP; then
    echo -e "${GREEN}Loading noetl-pip:latest image into Kind cluster...${NC}"
    kind load docker-image noetl-pip:latest --name "${CLUSTER_NAME}"
else
    echo -e "${YELLOW}Skipping noetl-pip image load as requested.${NC}"
fi

if $LOAD_NOETL_LOCAL_DEV; then
    echo -e "${GREEN}Loading noetl-local-dev:latest image into Kind cluster...${NC}"
    kind load docker-image noetl-local-dev:latest --name "${CLUSTER_NAME}"
else
    echo -e "${YELLOW}Skipping noetl-local-dev image load as requested.${NC}"
fi

if $LOAD_POSTGRES; then
    echo -e "${GREEN}Loading postgres-noetl:latest image into Kind cluster...${NC}"
    kind load docker-image postgres-noetl:latest --name "${CLUSTER_NAME}"
else
    echo -e "${YELLOW}Skipping postgres-noetl image load as requested.${NC}"
fi

echo -e "${GREEN}All requested images have been loaded into the Kind cluster.${NC}"
echo "You can now deploy NoETL using the deployment scripts."