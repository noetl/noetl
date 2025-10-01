#!/bin/bash

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
info() { echo -e "${BLUE}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "${SCRIPT_DIR}")"

# Configuration
CLUSTER_NAME="noetl-cluster"
NAMESPACE="noetl-platform"

# Function to cleanup everything
cleanup_everything() {
    info "🧹 Cleaning up everything..."
    
    # Stop any running port-forwards
    info "Stopping port-forwards..."
    pkill -f "kubectl.*port-forward" 2>/dev/null || true
    
    # Delete Kind clusters
    info "Deleting Kind clusters..."
    for cluster in $(kind get clusters 2>/dev/null || true); do
        info "Deleting cluster: ${cluster}"
        kind delete cluster --name="${cluster}" || warn "Failed to delete cluster ${cluster}"
    done
    
    # Clean up Docker images (optional - comment out if you want to keep them)
    info "Cleaning up NoETL Docker images..."
    docker rmi noetl-local-dev:latest 2>/dev/null || warn "NoETL image not found"
    docker rmi postgres-noetl:latest 2>/dev/null || warn "PostgreSQL image not found"
    
    # Clean up any stale port-forward scripts
    rm -f "${SCRIPT_DIR}/observability/port-forward-unified.sh"
    rm -f "/tmp/port-forward-unified.sh"
    
    # Clean up any PersistentVolumes from previous deployments
    info "Cleaning up PersistentVolumes..."
    kubectl delete -f "${SCRIPT_DIR}/observability/victoriametrics-pv.yaml" 2>/dev/null || warn "VictoriaMetrics PV not found or already deleted"
    kubectl delete pv postgres-pv 2>/dev/null || warn "PostgreSQL PV not found or already deleted"
    
    success "Cleanup completed"
}

# Function to build Docker images
build_docker_images() {
    info "🔨 Building Docker images..."
    
    cd "${PROJECT_ROOT}"
    
    # Build NoETL image using the correct Dockerfile path
    info "Building NoETL local-dev image..."
    docker build -t noetl-local-dev:latest -f docker/noetl/dev/Dockerfile . || {
        error "Failed to build NoETL image"
        exit 1
    }
    
    # Build PostgreSQL image using the correct Dockerfile path
    info "Building PostgreSQL image..."
    docker build -t postgres-noetl:latest -f docker/postgres/Dockerfile . || {
        error "Failed to build PostgreSQL image"
        exit 1
    }
    
    success "Docker images built successfully"
}

# Function to create and setup Kind cluster
setup_kind_cluster() {
    info "🚀 Setting up Kind cluster..."
    
    # Create cluster
    kind create cluster --name="${CLUSTER_NAME}" --config="${SCRIPT_DIR}/kind-config.yaml" || {
        error "Failed to create Kind cluster"
        exit 1
    }
    
    # Load Docker images into Kind
    info "Loading Docker images into Kind..."
    kind load docker-image noetl-local-dev:latest --name="${CLUSTER_NAME}" || {
        error "Failed to load NoETL image"
        exit 1
    }
    
    kind load docker-image postgres-noetl:latest --name="${CLUSTER_NAME}" || {
        error "Failed to load PostgreSQL image"
        exit 1
    }
    
    # Verify cluster is ready
    info "Waiting for cluster to be ready..."
    kubectl wait --for=condition=Ready nodes --all --timeout=300s || {
        error "Cluster nodes not ready within timeout"
        exit 1
    }
    
    success "Kind cluster setup completed"
}

# Function to deploy everything
deploy_unified_platform() {
    info "🚢 Deploying unified platform..."
    
    # Run the unified deployment
    "${SCRIPT_DIR}/deploy-unified-platform.sh" || {
        error "Unified platform deployment failed"
        exit 1
    }
    
    success "Unified platform deployed successfully"
}

# Function to verify deployment
verify_deployment() {
    info "🔍 Verifying deployment..."
    
    # Wait for PostgreSQL to be ready
    info "Waiting for PostgreSQL to be ready..."
    kubectl wait --for=condition=Ready pod -l app=postgres -n "${NAMESPACE}" --timeout=300s || {
        warn "PostgreSQL not ready within timeout"
    }
    
    # Wait for NoETL server to be ready
    info "Waiting for NoETL server to be ready..."
    kubectl wait --for=condition=Ready pod -l app=noetl-server -n "${NAMESPACE}" --timeout=300s || {
        warn "NoETL server not ready within timeout"
    }
    
    # Wait for workers to be ready
    info "Waiting for workers to be ready..."
    kubectl wait --for=condition=Ready pod -l component=worker -n "${NAMESPACE}" --timeout=300s || {
        warn "Workers not ready within timeout"
    }
    
    # Wait for Grafana to be ready
    info "Waiting for Grafana to be ready..."
    kubectl wait --for=condition=Ready pod -l app.kubernetes.io/name=grafana -n "${NAMESPACE}" --timeout=300s || {
        warn "Grafana not ready within timeout"
    }
    
    # Check pod status
    info "Checking pod status..."
    kubectl get pods -n "${NAMESPACE}" -o wide
    
    # Check services
    info "Checking services..."
    kubectl get services -n "${NAMESPACE}"
    
    success "Deployment verification completed"
}

# Function to test connectivity
test_connectivity() {
    info "🔗 Testing connectivity..."
    
    # Test NoETL server health
    info "Testing NoETL server health..."
    (for i in {1..15}; do curl -s http://localhost:30082/health > /dev/null && break || (echo "Waiting for NoETL server..."; sleep 2); done) || {
        warn "NoETL server health check failed - checking if port-forward is needed"
        kubectl port-forward -n "${NAMESPACE}" service/noetl-server 30082:8082 &
        PF_PID=$!
        sleep 5
        curl -s http://localhost:30082/health || warn "NoETL server still not responding"
        kill $PF_PID 2>/dev/null || true
    }
    
    # Test Grafana
    info "Testing Grafana connectivity..."
    (for i in {1..5}; do curl -s http://localhost:3000 > /dev/null && break || (echo "Waiting for Grafana..."; sleep 2); done) || {
        warn "Grafana not accessible - port-forward should be running automatically"
    }
    
    success "Connectivity tests completed"
}

# Function to show access information
show_access_info() {
    info "📋 Access Information:"
    cat << EOF

${GREEN}✅ Unified NoETL Platform Deployed Successfully!${NC}

🌐 Access URLs:
  - NoETL Server:       http://localhost:30082 (API & UI)
  - Grafana:            http://localhost:3000 (admin/admin)
  - VictoriaMetrics:    http://localhost:8428/vmui/
  - VictoriaLogs:       http://localhost:9428

🔧 Management Commands:
  - Get Grafana credentials:    make unified-grafana-credentials
  - Check deployment status:    kubectl get all -n ${NAMESPACE}
  - View logs:                 kubectl logs -n ${NAMESPACE} -l app=noetl-server
  - Port-forward management:    k8s/observability/port-forward-unified.sh

📊 Dashboards Available in Grafana:
  - NoETL Server Dashboard (server metrics, health, requests)
  - NoETL Workers Dashboard (worker pools, jobs, performance)

🐳 Cluster Information:
  - Kind cluster:       ${CLUSTER_NAME}
  - Namespace:          ${NAMESPACE}
  - Kubernetes context: kind-${CLUSTER_NAME}

EOF
}

# Main execution
main() {
    info "🚀 Starting complete NoETL platform recreation..."
    
    echo "This will:"
    echo "  1. Clean up all existing Kind clusters and resources"
    echo "  2. Rebuild Docker images"
    echo "  3. Create a new Kind cluster"
    echo "  4. Deploy unified platform with observability"
    echo "  5. Verify everything is working"
    echo
    read -p "Continue? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        info "Aborted by user"
        exit 0
    fi
    
    cleanup_everything
    build_docker_images
    setup_kind_cluster
    deploy_unified_platform
    verify_deployment
    test_connectivity
    show_access_info
    
    success "🎉 Complete platform recreation finished successfully!"
}

# Run main function
main "$@"