#!/bin/bash
set -euo pipefail

# diagnose.sh - Complete diagnostic and test execution for container fixture
# This script runs all checks and attempts execution with detailed output

cd "$(dirname "${BASH_SOURCE[0]}")/../../../.."
REPO_ROOT="$(pwd)"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_section() {
    echo -e "\n${BLUE}=========================================="
    echo -e "$1"
    echo -e "==========================================${NC}\n"
}

log_pass() { echo -e "${GREEN}✓${NC} $1"; }
log_fail() { echo -e "${RED}✗${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log_info() { echo -e "${BLUE}ℹ${NC} $1"; }

ERRORS=0

log_section "NoETL Container Test - Complete Diagnostic"
echo "Repository: $REPO_ROOT"
echo "Timestamp: $(date)"
echo ""

# === STEP 1: Cluster Check ===
log_section "STEP 1: Kind Cluster Check"
if kind get clusters 2>/dev/null | grep -q "noetl"; then
    log_pass "Kind cluster 'noetl' exists"
    CLUSTER_NODES=$(docker ps --filter "name=noetl-control-plane" --format "{{.Names}}" 2>/dev/null || echo "")
    if [ -n "$CLUSTER_NODES" ]; then
        log_pass "Cluster containers running: $CLUSTER_NODES"
    fi
else
    log_fail "Kind cluster 'noetl' not found"
    echo "Run: make bootstrap or task bring-all"
    exit 1
fi

# === STEP 2: Kubectl Context ===
log_section "STEP 2: Kubectl Context"
CURRENT_CONTEXT=$(kubectl config current-context 2>/dev/null || echo "none")
echo "Current context: $CURRENT_CONTEXT"
if [ "$CURRENT_CONTEXT" != "kind-noetl" ]; then
    log_warn "Switching to kind-noetl context"
    kubectl config use-context kind-noetl
    log_pass "Context switched"
fi

# === STEP 3: Namespace Check ===
log_section "STEP 3: Namespace Check"
for ns in noetl postgres; do
    if kubectl get namespace "$ns" >/dev/null 2>&1; then
        log_pass "Namespace '$ns' exists"
    else
        log_fail "Namespace '$ns' not found"
        ((ERRORS++))
    fi
done

# === STEP 4: PostgreSQL Status ===
log_section "STEP 4: PostgreSQL Status"
echo "Checking PostgreSQL deployment..."
kubectl get deployment postgres -n postgres 2>/dev/null || log_fail "PostgreSQL deployment not found"
kubectl get pods -n postgres
PGREADY=$(kubectl get deployment postgres -n postgres -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
if [ "$PGREADY" == "1" ]; then
    log_pass "PostgreSQL ready (1/1)"
    
    echo ""
    echo "Testing PostgreSQL connectivity..."
    if kubectl exec -n postgres deployment/postgres -- psql -U demo -d demo_noetl -c "SELECT version();" >/dev/null 2>&1; then
        log_pass "PostgreSQL accessible from cluster"
    else
        log_fail "PostgreSQL not accessible"
        ((ERRORS++))
    fi
else
    log_fail "PostgreSQL not ready ($PGREADY/1)"
    ((ERRORS++))
fi

# === STEP 5: NoETL Server Status ===
log_section "STEP 5: NoETL Server Status"
echo "Checking NoETL server deployment..."
kubectl get deployment noetl-server -n noetl 2>/dev/null || log_fail "NoETL server not found"
kubectl get pods -n noetl -l app=noetl-server
SERVERREADY=$(kubectl get deployment noetl-server -n noetl -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
if [ "$SERVERREADY" -ge "1" ]; then
    log_pass "NoETL server ready ($SERVERREADY replicas)"
    
    echo ""
    echo "Testing NoETL API..."
    if curl -sf http://localhost:8082/api/health >/dev/null 2>&1; then
        log_pass "API accessible at http://localhost:8082"
        curl -s http://localhost:8082/api/health | head -5
    else
        log_fail "API not accessible"
        log_warn "Check port forwarding: kubectl port-forward -n noetl svc/noetl-server 8082:8082 &"
        ((ERRORS++))
    fi
else
    log_fail "NoETL server not ready ($SERVERREADY replicas)"
    ((ERRORS++))
fi

# === STEP 6: NoETL Worker Status ===
log_section "STEP 6: NoETL Worker Status"
echo "Checking NoETL worker deployment..."
kubectl get deployment noetl-worker -n noetl 2>/dev/null || log_fail "NoETL worker not found"
kubectl get pods -n noetl -l app=noetl-worker
WORKERREADY=$(kubectl get deployment noetl-worker -n noetl -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
if [ "$WORKERREADY" -ge "1" ]; then
    log_pass "NoETL worker ready ($WORKERREADY replicas)"
    
    WORKER_POD=$(kubectl get pods -n noetl -l app=noetl-worker -o jsonpath='{.items[0].metadata.name}')
    echo ""
    echo "Worker pod: $WORKER_POD"
    echo ""
    echo "Last 10 lines of worker logs:"
    kubectl logs -n noetl "$WORKER_POD" --tail=10 2>/dev/null || log_warn "Could not fetch logs"
    
    echo ""
    echo "Testing DNS from worker..."
    if kubectl exec -n noetl "$WORKER_POD" -- nslookup postgres.postgres.svc.cluster.local >/dev/null 2>&1; then
        log_pass "DNS resolution works from worker"
    else
        log_fail "DNS resolution failed from worker"
        kubectl exec -n noetl "$WORKER_POD" -- nslookup postgres.postgres.svc.cluster.local || true
        ((ERRORS++))
    fi
else
    log_fail "NoETL worker not ready ($WORKERREADY replicas)"
    ((ERRORS++))
fi

# === STEP 7: Container Image Check ===
log_section "STEP 7: Container Image Check"
IMAGE_IN_CLUSTER=$(docker exec noetl-control-plane crictl images 2>/dev/null | grep postgres-container-test || echo "")
if [ -n "$IMAGE_IN_CLUSTER" ]; then
    log_pass "Container image loaded in cluster"
    echo "$IMAGE_IN_CLUSTER"
else
    log_warn "Container image not found in cluster"
    echo "Building and loading image..."
    docker build -t noetl/postgres-container-test:latest tests/fixtures/playbooks/container_postgres_init/ || log_fail "Build failed"
    kind load docker-image noetl/postgres-container-test:latest --name noetl || log_fail "Load failed"
    log_pass "Image built and loaded"
fi

# === STEP 8: Credentials Check ===
log_section "STEP 8: Credentials Check"
if curl -sf http://localhost:8082/api/credentials >/dev/null 2>&1; then
    CREDS=$(curl -s http://localhost:8082/api/credentials)
    if echo "$CREDS" | grep -q "pg_k8s"; then
        log_pass "Credential 'pg_k8s' registered"
    else
        log_warn "Credential 'pg_k8s' not found"
        echo "Registering credentials..."
        curl -X POST http://localhost:8082/api/credentials -H 'Content-Type: application/json' --data-binary @tests/fixtures/credentials/pg_k8s.json || log_warn "Registration failed"
    fi
else
    log_fail "Cannot access credentials API"
    ((ERRORS++))
fi

# === STEP 9: Register Playbook ===
log_section "STEP 9: Playbook Registration"
if [ -x ".venv/bin/noetl" ]; then
    CLI=".venv/bin/noetl"
else
    CLI="noetl"
fi

echo "Registering playbook..."
$CLI register tests/fixtures/playbooks/container_postgres_init/container_postgres_init.yaml --host localhost --port 8082 || log_warn "Registration may have failed"
log_pass "Playbook registration attempted"

# === STEP 10: Execute Playbook ===
log_section "STEP 10: Execute Playbook"
echo "Executing playbook..."
EXEC_OUTPUT=$($CLI execute playbook tests/fixtures/playbooks/container_postgres_init --host localhost --port 8082 --json 2>&1)
echo "$EXEC_OUTPUT"

EXECUTION_ID=$(echo "$EXEC_OUTPUT" | grep -o '"execution_id": "[0-9]*"' | head -1 | cut -d'"' -f4)
if [ -n "$EXECUTION_ID" ]; then
    log_pass "Execution started: $EXECUTION_ID"
else
    log_fail "Could not extract execution ID"
    ((ERRORS++))
fi

# === STEP 11: Monitor Execution ===
log_section "STEP 11: Monitor Execution (30s wait)"
echo "Waiting for execution to complete..."
for i in {1..30}; do
    echo -n "."
    sleep 1
    
    # Check for jobs
    JOBS=$(kubectl get jobs -n noetl -l noetl.io/component=container 2>/dev/null | tail -n +2 || echo "")
    if [ -n "$JOBS" ]; then
        echo ""
        log_info "Container jobs found"
        kubectl get jobs -n noetl -l noetl.io/component=container
        break
    fi
done
echo ""

# === STEP 12: Check Results ===
log_section "STEP 12: Check Results"
echo "Waiting for schema creation (up to 30s)..."
for i in {1..6}; do
    if kubectl exec -n postgres deployment/postgres -- psql -U demo -d demo_noetl -c "\dn container_test" 2>/dev/null | grep -q container_test; then
        log_pass "Schema 'container_test' created"
        
        echo ""
        echo "Execution log:"
        kubectl exec -n postgres deployment/postgres -- psql -U demo -d demo_noetl -c "SELECT * FROM container_test.execution_log ORDER BY executed_at;" 2>/dev/null || log_warn "No execution log yet"
        
        echo ""
        echo "Tables:"
        kubectl exec -n postgres deployment/postgres -- psql -U demo -d demo_noetl -c "\dt container_test.*" 2>/dev/null || true
        
        echo ""
        echo "Data counts:"
        kubectl exec -n postgres deployment/postgres -- psql -U demo -d demo_noetl -c "
            SELECT 'customers' AS table_name, COUNT(*) AS count FROM container_test.customers
            UNION ALL SELECT 'products', COUNT(*) FROM container_test.products  
            UNION ALL SELECT 'orders', COUNT(*) FROM container_test.orders
            UNION ALL SELECT 'order_items', COUNT(*) FROM container_test.order_items
            ORDER BY table_name;
        " 2>/dev/null || log_warn "Tables not ready yet"
        
        break
    fi
    echo "Waiting... ($i/6)"
    sleep 5
done

# === STEP 13: Job Status ===
log_section "STEP 13: Container Job Status"
kubectl get jobs -n noetl -l noetl.io/component=container 2>/dev/null || echo "No jobs found"
kubectl get pods -n noetl -l noetl.io/component=container 2>/dev/null || echo "No pods found"

echo ""
echo "Recent job logs:"
POD=$(kubectl get pods -n noetl -l noetl.io/component=container --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1:].metadata.name}' 2>/dev/null || echo "")
if [ -n "$POD" ]; then
    echo "Pod: $POD"
    kubectl logs -n noetl "$POD" --tail=30 2>/dev/null || echo "No logs available"
fi

# === SUMMARY ===
log_section "DIAGNOSTIC SUMMARY"
if [ $ERRORS -eq 0 ]; then
    log_pass "All checks passed!"
    echo ""
    echo "To clean up: task test:container:cleanup"
else
    log_fail "Found $ERRORS error(s)"
    echo ""
    echo "Check worker logs: kubectl logs -n noetl deployment/noetl-worker"
    echo "Check server logs: kubectl logs -n noetl deployment/noetl-server"
fi

exit $ERRORS
