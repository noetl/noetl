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
DEPLOY_NOETL_RELOAD=false
REPO_PATH_ARG=""
WORKER_NAMESPACES=(
    "noetl-worker-cpu-01"
    "noetl-worker-cpu-02"
    "noetl-worker-gpu-01"
)

function show_usage {
    echo "Usage: $0 [options]"
    echo "Options:"
    echo "  --no-cluster          Skip cluster setup"
    echo "  --no-postgres         Skip Postgres deployment"
    echo "  --no-noetl-pip        Skip NoETL pip deployment"
    echo "  --deploy-noetl-dev    Deploy NoETL from GitHub"
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
        --deploy-noetl-dev)
            DEPLOY_NOETL_DEV=true
            shift
            ;;
        --deploy-noetl-reload)
            echo -e "${YELLOW}Warning: --deploy-noetl-reload is deprecated and ignored.${NC}"
            shift
            ;;
        --repo-path)
            REPO_PATH_ARG="$2"
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

echo -e "${YELLOW}NoETL Platform Deployment Script${NC}"
echo "This script will set up a complete NoETL platform in Kubernetes."
echo

if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}Error: kubectl is not installed.${NC}"
    echo "Install kubectl."
    exit 1
fi

if $SETUP_CLUSTER; then
    if ! command -v kind &> /dev/null; then
        echo -e "${RED}Error: kind is not installed.${NC}"
        echo "See k8s/KIND-README.md for instructions."
        exit 1
    fi

    if false; then
        echo -e "${GREEN}Setting up Kind cluster with repository mounting for reload ...${NC}"
        if [ -n "$REPO_PATH_ARG" ]; then
            "${SCRIPT_DIR}/setup-kind-cluster.sh" "$REPO_PATH_ARG"
        else
            "${SCRIPT_DIR}/setup-kind-cluster.sh"
        fi
    else
        echo -e "${GREEN}Creating Kind configuration file...${NC}"
        cat > kind-config.yaml << EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraPortMappings:
  - containerPort: 30080
    hostPort: 30080
    protocol: TCP
  - containerPort: 30081
    hostPort: 30081
    protocol: TCP
  - containerPort: 30082
    hostPort: 30082
    protocol: TCP
  - containerPort: 30083
    hostPort: 30083
    protocol: TCP
  - containerPort: 30084
    hostPort: 30084
    protocol: TCP
EOF

        EXISTING_CLUSTER=$(kind get clusters 2>/dev/null | grep -x noetl-cluster || true)
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
else
    echo -e "${YELLOW}Skipping cluster setup as requested.${NC}"
fi

if $DEPLOY_POSTGRES; then
    echo -e "${GREEN}Building Postgres image...${NC}"
    "${REPO_PATH}/docker/build-images.sh" --no-pip --no-local-dev
    
    echo -e "${GREEN}Deploying Postgres...${NC}"
    kubectl apply -f "${SCRIPT_DIR}/postgres/postgres-namespace.yaml"
    kubectl apply -f "${SCRIPT_DIR}/postgres/postgres-pv.yaml"
    kubectl apply -f "${SCRIPT_DIR}/postgres/postgres-configmap.yaml"
    kubectl apply -f "${SCRIPT_DIR}/postgres/postgres-config-files.yaml"
    kubectl apply -f "${SCRIPT_DIR}/postgres/postgres-secret.yaml"
    kubectl apply -f "${SCRIPT_DIR}/postgres/postgres-deployment.yaml"
    kubectl apply -f "${SCRIPT_DIR}/postgres/postgres-service.yaml"

    echo -e "${GREEN}Waiting for Postgres to be ready...${NC}"
    sleep 10
    echo "Checking for Postgres pods..."
    kubectl get pods -l app=postgres -n postgres
    kubectl wait --for=condition=ready pod -l app=postgres -n postgres --timeout=180s || {
        echo -e "${RED}Error: Postgres pods not ready. Checking pod status...${NC}"
        kubectl get pods -n postgres
        echo -e "${YELLOW}Continuing with deployment anyway...${NC}"
    }
else
    echo -e "${YELLOW}Skipping Postgres deployment as requested.${NC}"
fi

BUILD_IMAGES=true
if $BUILD_IMAGES; then
    echo -e "${GREEN}Building Docker images for NoETL deployments...${NC}"
    "${REPO_PATH}/docker/build-images.sh"
    echo -e "${GREEN}Docker images built successfully.${NC}"
    
    if kubectl config current-context | grep -q "kind-"; then
        echo -e "${GREEN}Loading Docker images into Kind cluster...${NC}"
        "${SCRIPT_DIR}/load-images.sh" --cluster-name "$(kubectl config current-context | sed 's/^kind-//')"
        echo -e "${GREEN}Docker images loaded successfully.${NC}"
    fi
fi

if $DEPLOY_NOETL_PIP; then
    echo -e "${GREEN}Deploying NoETL from pip...${NC}"
    kubectl apply -f "${SCRIPT_DIR}/noetl/namespaces.yaml"

    kubectl apply -n noetl -f "${SCRIPT_DIR}/noetl/noetl-configmap.yaml"
    kubectl apply -n noetl -f "${SCRIPT_DIR}/noetl/noetl-secret.yaml"
    kubectl apply -n noetl -f "${SCRIPT_DIR}/noetl/noetl-deployment.yaml"
    kubectl apply -n noetl -f "${SCRIPT_DIR}/noetl/noetl-service.yaml"

    for ns in "${WORKER_NAMESPACES[@]}"; do
        kubectl apply -n "$ns" -f "${SCRIPT_DIR}/noetl/noetl-configmap.yaml"
        kubectl apply -n "$ns" -f "${SCRIPT_DIR}/noetl/noetl-secret.yaml"
    done

    kubectl apply -f "${SCRIPT_DIR}/noetl/noetl-worker-deployments.yaml"

    echo -e "${GREEN}Waiting for NoETL to be ready...${NC}"
    sleep 10
    echo "Checking for NoETL pods..."
    kubectl get pods -n noetl -l app=noetl
    kubectl wait -n noetl --for=condition=ready pod -l app=noetl --timeout=180s || {
        echo -e "${RED}Error: NoETL pods not ready. Checking pod status...${NC}"
        kubectl get pods -n noetl -l app=noetl
        echo -e "${YELLOW}Continuing anyway...${NC}"
    }

    echo -e "${GREEN}Checking NoETL worker pools...${NC}"
    for ns in "${WORKER_NAMESPACES[@]}"; do
        echo "Namespace: $ns"
        kubectl get pods -n "$ns" -l component=worker || true
        kubectl wait -n "$ns" --for=condition=ready pod -l component=worker --timeout=180s || {
            echo -e "${YELLOW}Warning: Worker pods are not ready yet in namespace $ns.${NC}"
            kubectl get pods -n "$ns" -l component=worker || true
        }
    done
else
    echo -e "${YELLOW}Skipping NoETL pip deployment as requested.${NC}"
fi

if $DEPLOY_NOETL_DEV; then
    echo -e "${GREEN}Deploying NoETL from GitHub...${NC}"
    if [ -n "$REPO_PATH_ARG" ]; then
        "${SCRIPT_DIR}/deploy-noetl-dev.sh" --type dev --repo-path "$REPO_PATH_ARG"
    else
        "${SCRIPT_DIR}/deploy-noetl-dev.sh" --type dev
    fi
else
    echo -e "${YELLOW}Skipping NoETL GitHub deployment as requested.${NC}"
fi


echo -e "${GREEN}Deployment completed.${NC}"
echo -e "${YELLOW}Cluster Status:${NC}"
if $DEPLOY_NOETL_PIP; then
    kubectl get pods -n noetl || true
    for ns in "${WORKER_NAMESPACES[@]}"; do
        kubectl get pods -n "$ns" || true
    done
else
    kubectl get pods || true
fi
kubectl get services -A | grep -E '(noetl|postgres)' || true

echo -e "${GREEN}Available NoETL instances:${NC}"
if $DEPLOY_NOETL_PIP; then
    echo -e "  - NoETL (pip): ${YELLOW}http://localhost:30082/api/health${NC}"
fi
if $DEPLOY_NOETL_DEV; then
    echo -e "  - NoETL (local-dev): ${YELLOW}http://localhost:30080/api/health${NC}"
fi

echo -e "${GREEN}To delete the cluster when you're done:${NC}"
echo -e "  ${YELLOW}kind delete cluster --name noetl-cluster${NC}"
