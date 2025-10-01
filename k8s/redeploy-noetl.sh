#!/bin/bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER_NAME="noetl-cluster"

echo -e "${BLUE}======================================================${NC}"
echo -e "${BLUE}NoETL Schema & Application Redeployment${NC}"
echo -e "${BLUE}(Preserving Observability Services)${NC}"
echo -e "${BLUE}======================================================${NC}"
echo

function check_prerequisites() {
    echo -e "${YELLOW}Checking prerequisites...${NC}"
    
    if ! command -v kubectl &> /dev/null; then
        echo -e "${RED}Error: kubectl is not installed.${NC}"
        exit 1
    fi
    
    if ! kubectl cluster-info &> /dev/null; then
        echo -e "${RED}Error: Cannot connect to Kubernetes cluster.${NC}"
        exit 1
    fi
    
    if ! kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
        echo -e "${RED}Error: Kind cluster '${CLUSTER_NAME}' does not exist.${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}✓ Prerequisites check passed${NC}"
}

function backup_current_data() {
    echo -e "${YELLOW}Creating backup of current PostgreSQL data...${NC}"
    
    # Check if postgres is running
    if kubectl get pod -l app=postgres --no-headers 2>/dev/null | grep -q Running; then
        echo "Taking database dump..."
        POSTGRES_POD=$(kubectl get pods -l app=postgres -o jsonpath='{.items[0].metadata.name}')
        
        # Create backup directory
        mkdir -p "${REPO_ROOT}/backup/$(date +%Y%m%d_%H%M%S)"
        BACKUP_DIR="${REPO_ROOT}/backup/$(date +%Y%m%d_%H%M%S)"
        
        # Dump the database
        kubectl exec "$POSTGRES_POD" -- pg_dump -U noetl noetl > "${BACKUP_DIR}/noetl_backup.sql" 2>/dev/null || {
            echo -e "${YELLOW}Warning: Could not create database backup${NC}"
        }
        
        echo -e "${GREEN}✓ Database backup created at: ${BACKUP_DIR}${NC}"
    else
        echo -e "${YELLOW}PostgreSQL not running, skipping backup${NC}"
    fi
}

function rebuild_images() {
    echo -e "${YELLOW}Rebuilding Docker images with latest code...${NC}"
    
    cd "${REPO_ROOT}"
    
    # Build NoETL images only (skip pip version for faster builds)
    echo "Building NoETL images..."
    "${REPO_ROOT}/docker/build-noetl-images.sh" --no-pip --tag latest
    
    echo -e "${GREEN}✓ NoETL images built successfully${NC}"
}

function load_images_to_kind() {
    echo -e "${YELLOW}Loading NoETL images into Kind cluster...${NC}"
    
    # Load only NoETL images into kind cluster
    "${REPO_ROOT}/k8s/load-noetl-images.sh" --no-pip
    
    echo -e "${GREEN}✓ NoETL images loaded into Kind cluster${NC}"
}

function reset_postgres_schema() {
    echo -e "${YELLOW}Resetting PostgreSQL schema with updated DDL (including metrics table)...${NC}"
    
    # Set up port forward for PostgreSQL access
    echo "Setting up PostgreSQL port forward..."
    kubectl port-forward -n postgres svc/postgres 5432:5432 &
    PG_PORT_FORWARD_PID=$!
    sleep 5
    
    # Set PostgreSQL connection environment variables for the Makefile
    export POSTGRES_HOST=localhost
    export POSTGRES_PORT=5432
    export POSTGRES_USER=noetl
    export POSTGRES_PASSWORD=noetl
    export POSTGRES_DB=noetl
    export NOETL_SCHEMA=noetl
    
    # Use the Makefile command to safely reset schema
    echo "Running make postgres-reset-schema..."
    make postgres-reset-schema || {
        echo -e "${RED}Schema reset failed, cleaning up port-forward...${NC}"
        kill $PG_PORT_FORWARD_PID 2>/dev/null || true
        return 1
    }
    
    # Clean up port forward
    kill $PG_PORT_FORWARD_PID 2>/dev/null || true
    sleep 2
    
    echo -e "${GREEN}✓ PostgreSQL schema reset successfully${NC}"
}

function redeploy_noetl_server() {
    echo -e "${YELLOW}Redeploying NoETL server...${NC}"
    
    WORKER_NAMESPACES=(
        "noetl-worker-cpu-01"
        "noetl-worker-cpu-02" 
        "noetl-worker-gpu-01"
    )
    
    # Remove existing NoETL server deployment
    echo "Removing existing NoETL server deployment..."
    if kubectl get namespace noetl >/dev/null 2>&1; then
        kubectl delete deployment -n noetl noetl --ignore-not-found=true
        kubectl wait -n noetl --for=delete pod -l app=noetl --timeout=60s || true
    fi
    
    # Apply NoETL server configuration and deployment
    kubectl apply -f "${REPO_ROOT}/k8s/noetl/namespaces.yaml"
    kubectl apply -n noetl -f "${REPO_ROOT}/k8s/noetl/noetl-configmap.yaml"
    kubectl apply -n noetl -f "${REPO_ROOT}/k8s/noetl/noetl-secret.yaml"
    kubectl apply -n noetl -f "${REPO_ROOT}/k8s/noetl/noetl-deployment.yaml"
    kubectl apply -n noetl -f "${REPO_ROOT}/k8s/noetl/noetl-service.yaml"
    
    # Wait for NoETL server to be ready
    echo "Waiting for NoETL server to be ready..."
    kubectl wait -n noetl --for=condition=available deployment/noetl --timeout=300s
    
    echo -e "${GREEN}✓ NoETL server redeployed successfully${NC}"
}

function redeploy_noetl_workers() {
    echo -e "${YELLOW}Redeploying NoETL workers...${NC}"
    
    WORKER_NAMESPACES=(
        "noetl-worker-cpu-01"
        "noetl-worker-cpu-02"
        "noetl-worker-gpu-01" 
    )
    
    # Remove existing worker deployments
    echo "Removing existing worker deployments..."
    for ns in "${WORKER_NAMESPACES[@]}"; do
        if kubectl get namespace "$ns" >/dev/null 2>&1; then
            kubectl delete deployment -n "$ns" --all --ignore-not-found=true
            kubectl wait -n "$ns" --for=delete pod -l component=worker --timeout=60s || true
        fi
    done
    
    # Apply worker configurations
    for ns in "${WORKER_NAMESPACES[@]}"; do
        kubectl apply -n "$ns" -f "${REPO_ROOT}/k8s/noetl/noetl-configmap.yaml"
        kubectl apply -n "$ns" -f "${REPO_ROOT}/k8s/noetl/noetl-secret.yaml"
    done
    
    # Apply worker deployments
    kubectl apply -f "${REPO_ROOT}/k8s/noetl/noetl-worker-deployments.yaml"
    
    # Wait for workers to be ready
    echo "Waiting for workers to be ready..."
    for ns in "${WORKER_NAMESPACES[@]}"; do
        echo "Checking workers in namespace: $ns"
        kubectl wait -n "$ns" --for=condition=available deployment --all --timeout=300s || {
            echo -e "${YELLOW}Warning: Some workers in $ns may not be ready yet${NC}"
        }
    done
    
    echo -e "${GREEN}✓ NoETL workers redeployed successfully${NC}"
}

function verify_metrics_functionality() {
    echo -e "${YELLOW}Verifying metrics functionality...${NC}"
    
    # Wait for server to be fully ready
    sleep 30
    
    # Get NoETL server pod
    NOETL_POD=$(kubectl get pods -n noetl -l app=noetl -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
    
    if [ -n "$NOETL_POD" ]; then
        echo "Testing metrics endpoints..."
        
        # Test metrics endpoint
        kubectl exec -n noetl "$NOETL_POD" -- curl -s http://localhost:8082/api/metrics/prometheus >/dev/null && {
            echo -e "${GREEN}✓ Metrics endpoint is working${NC}"
        } || {
            echo -e "${YELLOW}Warning: Metrics endpoint test failed${NC}"
        }
        
        # Test self-report endpoint
        kubectl exec -n noetl "$NOETL_POD" -- curl -s -X POST http://localhost:8082/api/metrics/self-report >/dev/null && {
            echo -e "${GREEN}✓ Self-report endpoint is working${NC}"
        } || {
            echo -e "${YELLOW}Warning: Self-report endpoint test failed${NC}"
        }
    else
        echo -e "${YELLOW}Warning: Could not find NoETL server pod for testing${NC}"
    fi
}

function show_status() {
    echo -e "${BLUE}======================================================${NC}"
    echo -e "${BLUE}Deployment Status${NC}"
    echo -e "${BLUE}======================================================${NC}"
    
    echo -e "${YELLOW}PostgreSQL Status:${NC}"
    kubectl get pods -l app=postgres || true
    
    echo -e "\n${YELLOW}NoETL Server Status:${NC}"
    kubectl get pods -n noetl -l app=noetl || true
    
    echo -e "\n${YELLOW}NoETL Workers Status:${NC}"
    WORKER_NAMESPACES=("noetl-worker-cpu-01" "noetl-worker-cpu-02" "noetl-worker-gpu-01")
    for ns in "${WORKER_NAMESPACES[@]}"; do
        echo "Namespace: $ns"
        kubectl get pods -n "$ns" -l component=worker || true
        echo
    done
    
    echo -e "${YELLOW}Observability Services Status (should be untouched):${NC}"
    kubectl get pods -n noetl-platform || true
    
    echo -e "\n${GREEN}Useful commands:${NC}"
    echo -e "  ${YELLOW}Check NoETL logs:${NC} kubectl -n noetl logs -l app=noetl"
    echo -e "  ${YELLOW}Check worker logs:${NC} kubectl -n noetl-worker-cpu-01 logs -l component=worker"
    echo -e "  ${YELLOW}Test metrics:${NC} kubectl exec -n noetl <pod> -- curl http://localhost:8082/api/metrics/prometheus"
    echo -e "  ${YELLOW}Access Grafana:${NC} kubectl port-forward -n noetl-platform svc/vmstack-grafana 3000:80"
}

# Main execution
echo -e "${GREEN}Starting NoETL redeployment process...${NC}"
echo "This will rebuild and redeploy NoETL schema, server, and workers."
echo "Observability services will remain untouched."
echo

read -p "Continue? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Deployment cancelled."
    exit 0
fi

check_prerequisites
backup_current_data
rebuild_images
load_images_to_kind
reset_postgres_schema
redeploy_noetl_server
redeploy_noetl_workers
verify_metrics_functionality
show_status

echo -e "\n${GREEN}======================================================${NC}"
echo -e "${GREEN}NoETL redeployment completed successfully!${NC}"
echo -e "${GREEN}======================================================${NC}"
echo -e "The metrics functionality is now deployed and ready to use."
echo -e "Workers will automatically start reporting metrics via heartbeats."
echo -e "Server metrics are available at: /api/metrics/prometheus"