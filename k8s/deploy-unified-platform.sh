#!/bin/bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_PATH="$(cd "${SCRIPT_DIR}/.." && pwd)"

SETUP_CLUSTER=true
DEPLOY_POSTGRES=true
DEPLOY_NOETL_PIP=true
DEPLOY_NOETL_DEV=false
DEPLOY_OBSERVABILITY=true
REPO_PATH_ARG=""
UNIFIED_NAMESPACE="noetl-platform"

function show_usage {
    echo "Usage: $0 [options]"
    echo "Options:"
    echo "  --no-cluster          Skip cluster setup"
    echo "  --no-postgres         Skip Postgres deployment"
    echo "  --no-noetl-pip        Skip NoETL pip deployment"
    echo "  --no-observability    Skip observability deployment"
    echo "  --deploy-noetl-dev    Deploy NoETL from GitHub"
    echo "  --namespace NAME      Unified namespace for noetl, workers, and observability (default: noetl-platform)"
    echo "  --repo-path PATH      Path to local NoETL repository default: parent directory"
    echo "  --help                Show this help message"
    
    if [ -n "$1" ]; then
        exit 1
    else
        exit 0
    fi
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --no-cluster)
            SETUP_CLUSTER=false
            shift
            ;;
        --no-postgres)
            DEPLOY_POSTGRES=false
            shift
            ;;
        --no-noetl-pip)
            DEPLOY_NOETL_PIP=false
            shift
            ;;
        --no-observability)
            DEPLOY_OBSERVABILITY=false
            shift
            ;;
        --deploy-noetl-dev)
            DEPLOY_NOETL_DEV=true
            shift
            ;;
        --namespace)
            UNIFIED_NAMESPACE="$2"
            shift 2
            ;;
        --repo-path)
            REPO_PATH_ARG="$2"
            shift 2
            ;;
        --help)
            show_usage
            ;;
        *)
            echo -e "${RED}Error: Unknown option $1${NC}"
            show_usage 1
            ;;
    esac
done

echo -e "${GREEN}NoETL Unified Platform Deployment${NC}"
echo -e "This script will deploy NoETL server, workers, and observability in a unified namespace: ${YELLOW}${UNIFIED_NAMESPACE}${NC}"
echo

# Validate tools
if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}Error: kubectl is not installed or not in PATH${NC}"
    exit 1
fi

if ! command -v kind &> /dev/null; then
    echo -e "${RED}Error: kind is not installed or not in PATH${NC}"
    exit 1
fi

if $DEPLOY_OBSERVABILITY && ! command -v helm &> /dev/null; then
    echo -e "${RED}Error: helm is not installed or not in PATH (required for observability)${NC}"
    exit 1
fi

# Cluster setup
if $SETUP_CLUSTER; then
    cd "${SCRIPT_DIR}"
    
    # Check for existing cluster
    EXISTING_CLUSTER=$(kind get clusters 2>/dev/null | grep noetl-cluster || true)
    if [ -n "$EXISTING_CLUSTER" ]; then
        echo -e "${YELLOW}A Kind cluster named 'noetl-cluster' already exists.${NC}"
        read -p "Do you want to delete it and recreate from scratch? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo -e "${YELLOW}Deleting existing cluster...${NC}"
            kind delete cluster --name noetl-cluster
        else
            echo -e "${YELLOW}Skipping cluster creation and reusing the existing cluster.${NC}"
            echo -e "Hint: You can also run with --no-cluster to skip cluster setup."
        fi
    fi

    if ! kind get clusters 2>/dev/null | grep -qx noetl-cluster; then
        echo -e "${GREEN}Creating Kind cluster...${NC}"
        kind create cluster --name noetl-cluster --config kind-config.yaml
    else
        echo -e "${GREEN}Kind cluster 'noetl-cluster' is available.${NC}"
    fi

    echo -e "${GREEN}Creating directory for persistent volume...${NC}"
    docker exec noetl-cluster-control-plane mkdir -p /mnt/data
fi

# Deploy PostgreSQL
if $DEPLOY_POSTGRES; then
    echo -e "${GREEN}Deploying PostgreSQL...${NC}"
    # First apply namespace
    kubectl apply -f "${SCRIPT_DIR}/postgres/postgres-namespace.yaml"
    # Then apply the rest
    kubectl apply -f "${SCRIPT_DIR}/postgres/"
    
    echo -e "${GREEN}Waiting for PostgreSQL to be ready...${NC}"
    sleep 10
    kubectl wait -n postgres --for=condition=ready pod -l app=postgres --timeout=180s || {
        echo -e "${RED}Error: PostgreSQL pod not ready. Checking pod status...${NC}"
        kubectl get pods -n postgres -l app=postgres
        echo -e "${YELLOW}Continuing anyway...${NC}"
    }
else
    echo -e "${YELLOW}Skipping PostgreSQL deployment as requested.${NC}"
fi

# Create unified namespace
echo -e "${GREEN}Creating unified namespace: ${UNIFIED_NAMESPACE}${NC}"
kubectl create namespace "${UNIFIED_NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

# Deploy NoETL in unified mode
if $DEPLOY_NOETL_PIP; then
    echo -e "${GREEN}Deploying NoETL server and workers in unified namespace...${NC}"
    
    # Apply configmaps and secrets to unified namespace
    kubectl apply -n "${UNIFIED_NAMESPACE}" -f "${SCRIPT_DIR}/noetl/noetl-configmap.yaml"
    kubectl apply -n "${UNIFIED_NAMESPACE}" -f "${SCRIPT_DIR}/noetl/noetl-secret.yaml"

    # Generate and apply unified deployment
    "${SCRIPT_DIR}/generate-unified-noetl-deployment.sh" "${UNIFIED_NAMESPACE}" | kubectl apply -f -

    echo -e "${GREEN}Waiting for NoETL to be ready...${NC}"
    sleep 10
    echo "Checking for NoETL pods..."
    kubectl get pods -n "${UNIFIED_NAMESPACE}" -l app=noetl
    kubectl wait -n "${UNIFIED_NAMESPACE}" --for=condition=ready pod -l app=noetl --timeout=180s || {
        echo -e "${RED}Error: NoETL pods not ready. Checking pod status...${NC}"
        kubectl get pods -n "${UNIFIED_NAMESPACE}" -l app=noetl
        echo -e "${YELLOW}Continuing anyway...${NC}"
    }

    echo -e "${GREEN}Checking NoETL worker pools...${NC}"
    kubectl get pods -n "${UNIFIED_NAMESPACE}" -l component=worker || true
    kubectl wait -n "${UNIFIED_NAMESPACE}" --for=condition=ready pod -l component=worker --timeout=180s || {
        echo -e "${YELLOW}Warning: Worker pods are not ready yet in namespace ${UNIFIED_NAMESPACE}.${NC}"
        kubectl get pods -n "${UNIFIED_NAMESPACE}" -l component=worker || true
    }
else
    echo -e "${YELLOW}Skipping NoETL deployment as requested.${NC}"
fi

# Deploy observability in the same namespace
if $DEPLOY_OBSERVABILITY; then
    echo -e "${GREEN}Deploying observability stack in unified namespace...${NC}"
    
    # Deploy observability to the unified namespace instead of separate observability namespace
    "${SCRIPT_DIR}/deploy-unified-observability.sh" "${UNIFIED_NAMESPACE}"
    
    # Deploy PostgreSQL monitoring (VMServiceScrape) after observability stack
    if $DEPLOY_POSTGRES; then
        echo -e "${GREEN}Deploying PostgreSQL monitoring configuration...${NC}"
        kubectl apply -f "${SCRIPT_DIR}/postgres/monitoring/"
        kubectl apply -f "${SCRIPT_DIR}/observability/postgres-dashboard-configmap.yaml" || echo -e "${YELLOW}Warning: PostgreSQL dashboard not found${NC}"
        kubectl apply -f "${SCRIPT_DIR}/observability/noetl-server-dashboard-configmap.yaml" || echo -e "${YELLOW}Warning: NoETL server dashboard not found${NC}"
    fi
else
    echo -e "${YELLOW}Skipping observability deployment as requested.${NC}"
fi

echo -e "${GREEN}Unified deployment completed.${NC}"
echo -e "${YELLOW}Unified Cluster Status:${NC}"
kubectl get pods -n "${UNIFIED_NAMESPACE}" || true
if $DEPLOY_POSTGRES; then
    kubectl get pods -n postgres || true
fi
kubectl get services -A | grep -E "(${UNIFIED_NAMESPACE}|postgres)" || true

echo -e "${GREEN}Available services in unified deployment:${NC}"
if $DEPLOY_NOETL_PIP; then
    echo -e "  - NoETL Server: ${YELLOW}http://localhost:30082/api/health${NC}"
fi
if $DEPLOY_OBSERVABILITY; then
    echo -e "  - Grafana: ${YELLOW}http://localhost:3000${NC}"
    echo -e "  - VictoriaMetrics: ${YELLOW}http://localhost:8428/vmui/${NC}"
    echo -e "  - VictoriaLogs: ${YELLOW}http://localhost:9428${NC}"
fi

echo -e "${GREEN}To delete the cluster when you're done:${NC}"
echo -e "  ${YELLOW}kind delete cluster --name noetl-cluster${NC}"