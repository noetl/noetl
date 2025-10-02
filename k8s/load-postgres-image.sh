#!/bin/bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

CLUSTER_NAME="noetl-cluster"

function show_usage {
    echo "Usage: $0 [options]"
    echo "Options:"
    echo "  --cluster-name NAME  Name of the Kind cluster. Default: noetl-cluster"
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
        --help)
            show_usage
            ;;
        *)
            echo -e "${RED}Error: Unknown option: $1${NC}"
            show_usage "error"
            ;;
    esac
done

echo -e "${YELLOW}PostgreSQL Docker Image Loader for Kind${NC}"
echo "This script will load the PostgreSQL Docker image into the Kind cluster."
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

echo -e "${GREEN}Loading postgres-noetl:latest image into Kind cluster...${NC}"
kind load docker-image postgres-noetl:latest --name "${CLUSTER_NAME}"

echo -e "${GREEN}PostgreSQL image has been loaded into the Kind cluster.${NC}"
echo "You can now restart PostgreSQL deployment to use the updated image:"
echo -e "${YELLOW}Examples:${NC}"
echo -e "  kubectl rollout restart deployment/postgres -n postgres"
echo -e "  # Or apply schema changes:"
echo -e "  make postgres-reset-schema"