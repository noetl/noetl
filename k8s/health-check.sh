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

NAMESPACE="noetl-platform"

# Function to check cluster status
check_cluster() {
    info "🔍 Checking cluster status..."
    
    # Check if Kind cluster exists
    if ! kind get clusters | grep -q "noetl-cluster"; then
        error "Kind cluster 'noetl-cluster' not found"
        return 1
    fi
    success "Kind cluster is running"
    
    # Check if kubectl context is correct
    if ! kubectl config current-context | grep -q "kind-noetl-cluster"; then
        warn "kubectl context is not set to kind-noetl-cluster"
        kubectl config use-context kind-noetl-cluster
    fi
    success "kubectl context is correct"
}

# Function to check namespace
check_namespace() {
    info "🔍 Checking namespace..."
    
    if kubectl get namespace "${NAMESPACE}" &>/dev/null; then
        success "Namespace ${NAMESPACE} exists"
    else
        error "Namespace ${NAMESPACE} not found"
        return 1
    fi
}

# Function to check pods
check_pods() {
    info "🔍 Checking pod status..."
    
    echo "Pod Status:"
    kubectl get pods -n "${NAMESPACE}" -o wide
    
    # Check critical pods
    local failed=0
    
    # PostgreSQL (in postgres namespace)
    if kubectl get pods -n "postgres" -l app=postgres | grep -q "1/1.*Running"; then
        success "PostgreSQL is running"
    else
        error "PostgreSQL is not running properly"
        failed=1
    fi
    
    # NoETL Server
    if kubectl get pods -n "${NAMESPACE}" -l app=noetl,component=server | grep -q "1/1.*Running"; then
        success "NoETL server is running"
    else
        error "NoETL server is not running properly"
        failed=1
    fi
    
    # Workers
    local worker_count=$(kubectl get pods -n "${NAMESPACE}" -l app=noetl-worker,component=worker --no-headers | wc -l)
    local running_workers=$(kubectl get pods -n "${NAMESPACE}" -l app=noetl-worker,component=worker | grep -c "1/1.*Running" || echo "0")
    
    if [ "${running_workers}" -gt 0 ]; then
        success "Workers are running (${running_workers}/${worker_count})"
    else
        error "No workers are running"
        failed=1
    fi
    
    # Grafana
    if kubectl get pods -n "${NAMESPACE}" -l app.kubernetes.io/name=grafana | grep -q "2/2.*Running"; then
        success "Grafana is running"
    else
        error "Grafana is not running properly"
        failed=1
    fi
    
    return $failed
}

# Function to check services
check_services() {
    info "🔍 Checking services..."
    
    echo "Service Status:"
    kubectl get services -n "${NAMESPACE}"
    
    # Check NodePort services
    local noetl_nodeport=$(kubectl get service noetl-server -n "${NAMESPACE}" -o jsonpath='{.spec.ports[0].nodePort}' 2>/dev/null || echo "")
    if [ -n "${noetl_nodeport}" ]; then
        success "NoETL server NodePort: ${noetl_nodeport}"
    else
        warn "NoETL server NodePort not found"
    fi
}

# Function to check connectivity
check_connectivity() {
    info "🔍 Checking connectivity..."
    
    # Test NoETL server
    if curl -s --connect-timeout 5 http://localhost:30082/health &>/dev/null; then
        success "NoETL server is accessible at http://localhost:30082"
    else
        warn "NoETL server not accessible at localhost:30082"
        info "You may need to set up port-forwarding"
    fi
    
    # Test Grafana
    if curl -s --connect-timeout 5 http://localhost:3000 &>/dev/null; then
        success "Grafana is accessible at http://localhost:3000"
    else
        warn "Grafana not accessible at localhost:3000"
        info "Check if port-forwarding is running"
    fi
}

# Function to check dashboards
check_dashboards() {
    info "🔍 Checking dashboards and datasources..."
    
    # Check dashboard ConfigMaps
    local dashboard_cms=$(kubectl get configmaps -n "${NAMESPACE}" | grep -c "noetl-dashboard" || echo "0")
    if [ "${dashboard_cms}" -gt 0 ]; then
        success "NoETL dashboards ConfigMaps found (${dashboard_cms})"
        kubectl get configmaps -n "${NAMESPACE}" | grep "noetl-dashboard"
    else
        error "NoETL dashboards ConfigMaps not found"
    fi
    
    # Check datasource ConfigMaps
    local datasource_check=$(kubectl get configmaps -n "${NAMESPACE}" | grep "noetl-grafana-datasources" || echo "")
    if [ -n "${datasource_check}" ]; then
        success "Grafana datasources ConfigMap found"
    else
        error "Grafana datasources ConfigMap not found"
    fi
}

# Function to show logs for troubleshooting
show_troubleshooting_logs() {
    info "🔍 Recent logs for troubleshooting..."
    
    echo -e "\n${YELLOW}NoETL Server logs (last 10 lines):${NC}"
    kubectl logs -n "${NAMESPACE}" -l app=noetl,component=server --tail=10 || warn "Could not get NoETL server logs"
    
    echo -e "\n${YELLOW}Worker logs (last 5 lines):${NC}"
    kubectl logs -n "${NAMESPACE}" -l app=noetl-worker,component=worker --tail=5 || warn "Could not get worker logs"
    
    echo -e "\n${YELLOW}Grafana logs (last 5 lines):${NC}"
    kubectl logs -n "${NAMESPACE}" -l app.kubernetes.io/name=grafana --tail=5 || warn "Could not get Grafana logs"
}

# Function to show helpful commands
show_helpful_commands() {
    info "📋 Helpful commands for management:"
    
    cat << EOF

${GREEN}Monitoring & Logs:${NC}
  kubectl get all -n ${NAMESPACE}                    # See all resources
  kubectl logs -f -n ${NAMESPACE} -l app=noetl-server # Follow server logs
  kubectl logs -f -n ${NAMESPACE} -l component=worker # Follow worker logs

${GREEN}Debugging:${NC}
  kubectl describe pod -n ${NAMESPACE} <pod-name>    # Detailed pod info
  kubectl exec -it -n ${NAMESPACE} <pod-name> -- bash # Shell into pod

${GREEN}Port Forwarding:${NC}
  kubectl port-forward -n ${NAMESPACE} service/noetl-server 30082:8080
  kubectl port-forward -n ${NAMESPACE} service/vmstack-grafana 3000:3000

${GREEN}Credentials:${NC}
  make unified-grafana-credentials                   # Get Grafana admin password

${GREEN}Cleanup:${NC}
  make unified-recreate-all                          # Full recreation via Makefile
  ./k8s/recreate-all.sh                              # Full recreation (direct script)
  kind delete cluster --name=noetl-cluster          # Delete cluster

EOF
}

# Main function
main() {
    info "🚀 Starting NoETL platform health check..."
    
    local overall_status=0
    
    check_cluster || overall_status=1
    check_namespace || overall_status=1
    check_pods || overall_status=1
    check_services
    check_connectivity
    check_dashboards
    
    if [ $overall_status -eq 0 ]; then
        success "🎉 All checks passed! Platform is healthy."
    else
        warn "⚠️  Some issues detected. See details above."
        show_troubleshooting_logs
    fi
    
    show_helpful_commands
    
    return $overall_status
}

# Run main function
main "$@"