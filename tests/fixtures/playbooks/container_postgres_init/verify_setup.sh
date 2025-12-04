#!/bin/bash
set -euo pipefail

# verify_setup.sh - Verify NoETL Kubernetes setup for container tests
# This script checks that all components are properly deployed and accessible

echo "=========================================="
echo "NoETL Container Test - Setup Verification"
echo "=========================================="
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

check_pass() {
    echo -e "${GREEN}✓${NC} $1"
}

check_fail() {
    echo -e "${RED}✗${NC} $1"
}

check_warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# Step 1: Check Kind cluster
echo "1. Checking Kind cluster..."
if kind get clusters 2>/dev/null | grep -q "noetl"; then
    check_pass "Kind cluster 'noetl' exists"
else
    check_fail "Kind cluster 'noetl' not found"
    echo "   Run: make bootstrap"
    exit 1
fi
echo ""

# Step 2: Check kubectl context
echo "2. Checking kubectl context..."
CURRENT_CONTEXT=$(kubectl config current-context 2>/dev/null || echo "none")
if [ "$CURRENT_CONTEXT" == "kind-noetl" ]; then
    check_pass "kubectl context is 'kind-noetl'"
else
    check_warn "kubectl context is '$CURRENT_CONTEXT', switching to 'kind-noetl'"
    kubectl config use-context kind-noetl
fi
echo ""

# Step 3: Check PostgreSQL deployment
echo "3. Checking PostgreSQL deployment..."
if kubectl get deployment postgres -n postgres >/dev/null 2>&1; then
    check_pass "PostgreSQL deployment exists"
    READY=$(kubectl get deployment postgres -n postgres -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    if [ "$READY" == "1" ]; then
        check_pass "PostgreSQL is ready (1/1 replicas)"
    else
        check_fail "PostgreSQL is not ready ($READY/1 replicas)"
    fi
else
    check_fail "PostgreSQL deployment not found"
    exit 1
fi
echo ""

# Step 4: Check NoETL server
echo "4. Checking NoETL server..."
if kubectl get deployment noetl-server -n noetl >/dev/null 2>&1; then
    check_pass "NoETL server deployment exists"
    READY=$(kubectl get deployment noetl-server -n noetl -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    if [ "$READY" -ge "1" ]; then
        check_pass "NoETL server is ready ($READY replicas)"
    else
        check_fail "NoETL server is not ready ($READY replicas)"
    fi
else
    check_fail "NoETL server deployment not found"
    exit 1
fi
echo ""

# Step 5: Check NoETL worker
echo "5. Checking NoETL worker..."
if kubectl get deployment noetl-worker -n noetl >/dev/null 2>&1; then
    check_pass "NoETL worker deployment exists"
    READY=$(kubectl get deployment noetl-worker -n noetl -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    if [ "$READY" -ge "1" ]; then
        check_pass "NoETL worker is ready ($READY replicas)"
    else
        check_fail "NoETL worker is not ready ($READY replicas)"
    fi
else
    check_fail "NoETL worker deployment not found"
    exit 1
fi
echo ""

# Step 6: Check server accessibility
echo "6. Checking NoETL server API..."
if curl -sf http://localhost:8082/api/health >/dev/null 2>&1; then
    check_pass "NoETL API is accessible at http://localhost:8082"
    HEALTH=$(curl -s http://localhost:8082/api/health)
    echo "   Response: $HEALTH"
else
    check_fail "NoETL API is not accessible at http://localhost:8082"
    echo "   Check port forwarding: kubectl port-forward -n noetl svc/noetl-server 8082:8082"
fi
echo ""

# Step 7: Check PostgreSQL connectivity from cluster
echo "7. Testing PostgreSQL connectivity from cluster..."
if kubectl exec -n postgres deployment/postgres -- psql -U demo -d demo_noetl -c "SELECT version();" >/dev/null 2>&1; then
    check_pass "PostgreSQL is accessible from cluster"
else
    check_fail "PostgreSQL is not accessible from cluster"
fi
echo ""

# Step 8: Check container test image
echo "8. Checking container test image in cluster..."
IMAGE_CHECK=$(docker exec noetl-control-plane crictl images 2>/dev/null | grep postgres-container-test || echo "")
if [ -n "$IMAGE_CHECK" ]; then
    check_pass "Container test image is loaded in cluster"
    echo "   $IMAGE_CHECK"
else
    check_warn "Container test image not found in cluster"
    echo "   Run: task test:container:build-image"
fi
echo ""

# Step 9: Check worker logs for errors
echo "9. Checking worker logs for recent errors..."
WORKER_POD=$(kubectl get pods -n noetl -l app=noetl-worker -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [ -n "$WORKER_POD" ]; then
    check_pass "Worker pod: $WORKER_POD"
    ERROR_COUNT=$(kubectl logs -n noetl "$WORKER_POD" --tail=100 2>/dev/null | grep -c "ERROR" || echo "0")
    if [ "$ERROR_COUNT" -gt "0" ]; then
        check_warn "Found $ERROR_COUNT ERROR lines in recent logs"
        echo "   Run: kubectl logs -n noetl $WORKER_POD"
    else
        check_pass "No recent errors in worker logs"
    fi
else
    check_warn "Could not find worker pod"
fi
echo ""

# Step 10: Check if credentials are registered
echo "10. Checking registered credentials..."
CREDS=$(curl -s http://localhost:8082/api/credentials 2>/dev/null || echo "[]")
if echo "$CREDS" | grep -q "pg_k8s"; then
    check_pass "Credential 'pg_k8s' is registered"
else
    check_warn "Credential 'pg_k8s' not found"
    echo "   Run: task test:k8s:register-credentials"
fi
echo ""

echo "=========================================="
echo "Setup Verification Complete"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Build and load image: task test:container:build-image"
echo "  2. Register playbook: task test:container:register"
echo "  3. Execute playbook: task test:container:execute"
echo "  4. Check status: task test:container:status"
echo "  5. Verify results: task test:container:verify"
echo ""
echo "Or run all at once: task test:container:full"
echo ""
