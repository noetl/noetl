#!/bin/bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}NoETL Cleanup - Removing Old Deployments${NC}"
echo -e "This script will clean up the existing separate deployments to prepare for unified deployment."
echo

# Function to safely delete namespace
cleanup_namespace() {
    local namespace="$1"
    if kubectl get namespace "$namespace" &>/dev/null; then
        echo -e "${YELLOW}Deleting namespace: $namespace${NC}"
        kubectl delete namespace "$namespace" --ignore-not-found=true
        
        # Wait for namespace to be fully deleted
        echo -e "${YELLOW}Waiting for namespace $namespace to be fully deleted...${NC}"
        while kubectl get namespace "$namespace" &>/dev/null; do
            sleep 2
        done
        echo -e "${GREEN}Namespace $namespace deleted successfully.${NC}"
    else
        echo -e "${YELLOW}Namespace $namespace does not exist, skipping.${NC}"
    fi
}

# Function to cleanup helm releases
cleanup_helm_release() {
    local release="$1"
    local namespace="$2"
    if helm list -n "$namespace" | grep -q "$release"; then
        echo -e "${YELLOW}Uninstalling Helm release: $release from namespace $namespace${NC}"
        helm uninstall "$release" -n "$namespace" || true
    else
        echo -e "${YELLOW}Helm release $release not found in namespace $namespace, skipping.${NC}"
    fi
}

echo -e "${YELLOW}Checking current deployments...${NC}"
kubectl get deployments -A | grep -E "(noetl|observability)" || echo "No matching deployments found."
echo

read -p "Do you want to proceed with cleanup? This will delete all existing NoETL and observability deployments. (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Cleanup cancelled.${NC}"
    exit 0
fi

echo -e "${GREEN}Starting cleanup...${NC}"

# Stop any existing port-forwards
echo -e "${YELLOW}Stopping existing port-forwards...${NC}"
pkill -f "kubectl.*port-forward" || true

# Clean up observability helm releases first (before deleting namespace)
if kubectl get namespace observability &>/dev/null; then
    echo -e "${YELLOW}Cleaning up observability Helm releases...${NC}"
    cleanup_helm_release "vmstack" "observability"
    cleanup_helm_release "vlogs" "observability" 
    cleanup_helm_release "vector" "observability"
fi

# Clean up NoETL worker namespaces
cleanup_namespace "noetl-worker-cpu-01"
cleanup_namespace "noetl-worker-cpu-02"
cleanup_namespace "noetl-worker-gpu-01"

# Clean up main noetl namespace
cleanup_namespace "noetl"

# Clean up observability namespace
cleanup_namespace "observability"

# Note: Keep postgres namespace as it can be reused
echo -e "${YELLOW}Keeping postgres namespace (can be reused by unified deployment).${NC}"

echo -e "${GREEN}Cleanup completed successfully!${NC}"
echo -e "${YELLOW}You can now run the unified deployment:${NC}"
echo -e "  ${GREEN}./k8s/deploy-unified-platform.sh${NC}"
echo