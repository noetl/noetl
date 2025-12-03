#!/bin/bash
set -euo pipefail

# test.sh - Quick test of container_postgres_init fixture
# Usage: ./test.sh [skip-build]

SKIP_BUILD="${1:-}"
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "==================================================="
echo "Container PostgreSQL Init - Test Runner"
echo "==================================================="
echo ""

# Change to repository root
cd "$(dirname "${BASH_SOURCE[0]}")/../../../.."
REPO_ROOT="$(pwd)"
echo "Repository root: $REPO_ROOT"
echo ""

# Function to print status
print_status() {
    local status=$1
    local message=$2
    if [ "$status" == "ok" ]; then
        echo -e "${GREEN}✓${NC} $message"
    elif [ "$status" == "skip" ]; then
        echo -e "${YELLOW}⊘${NC} $message"
    else
        echo -e "${RED}✗${NC} $message"
    fi
}

# Step 1: Check cluster
echo "Step 1: Checking Kind cluster..."
if kind get clusters | grep -q "noetl"; then
    print_status "ok" "Kind cluster exists"
else
    print_status "error" "Kind cluster not found"
    echo ""
    echo "Create cluster with: task bring-all"
    exit 1
fi
echo ""

# Step 2: Build image
if [ "$SKIP_BUILD" == "skip-build" ]; then
    print_status "skip" "Skipping image build (use skip-build argument)"
else
    echo "Step 2: Building and loading container image..."
    if task test:container:build-image; then
        print_status "ok" "Image built and loaded"
    else
        print_status "error" "Image build failed"
        exit 1
    fi
fi
echo ""

# Step 3: Register playbook
echo "Step 3: Registering playbook..."
if task test:container:register 2>&1 | grep -q "success\|already"; then
    print_status "ok" "Playbook registered"
else
    print_status "error" "Playbook registration failed"
    exit 1
fi
echo ""

# Step 4: Execute playbook
echo "Step 4: Executing playbook..."
if task test:container:execute; then
    print_status "ok" "Playbook executed"
else
    print_status "error" "Playbook execution failed"
    exit 1
fi
echo ""

# Wait for execution to complete
echo "Waiting for execution to complete..."
sleep 10
echo ""

# Step 5: Verify results
echo "Step 5: Verifying results..."
if task test:container:verify; then
    print_status "ok" "Results verified"
else
    print_status "error" "Verification failed"
    exit 1
fi
echo ""

echo "==================================================="
echo -e "${GREEN}All tests passed!${NC}"
echo "==================================================="
echo ""
echo "Created schema: container_test"
echo "Created tables: customers, products, orders, order_items, execution_log"
echo ""
echo "Clean up with: task test:container:cleanup"
echo ""
