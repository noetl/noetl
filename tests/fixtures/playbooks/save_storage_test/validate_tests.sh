#!/bin/bash

# Save Storage Test Suite Validation Script
# This script helps validate the save storage test playbooks

set -e

echo "=== NoETL Save Storage Test Suite Validation ==="
echo "Date: $(date)"
echo "Environment: NoETL Kubernetes Cluster"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    local status=$1
    local message=$2
    case $status in
        "SUCCESS") echo -e "${GREEN}✓ $message${NC}" ;;
        "ERROR") echo -e "${RED}✗ $message${NC}" ;;
        "INFO") echo -e "${YELLOW}ℹ $message${NC}" ;;
    esac
}

# Check if kubectl is available and cluster is accessible
check_cluster() {
    print_status "INFO" "Checking Kubernetes cluster access..."
    if kubectl get pods -n noetl > /dev/null 2>&1; then
        print_status "SUCCESS" "Kubernetes cluster accessible"
    else
        print_status "ERROR" "Cannot access Kubernetes cluster"
        exit 1
    fi
}

# Check if NoETL services are running
check_noetl_services() {
    print_status "INFO" "Checking NoETL services..."
    
    # Check server
    if kubectl get deployment noetl-server -n noetl > /dev/null 2>&1; then
        print_status "SUCCESS" "NoETL server deployment found"
    else
        print_status "ERROR" "NoETL server deployment not found"
        exit 1
    fi
    
    # Check worker
    if kubectl get deployment noetl-worker -n noetl > /dev/null 2>&1; then
        print_status "SUCCESS" "NoETL worker deployment found"
    else
        print_status "ERROR" "NoETL worker deployment not found"
        exit 1
    fi
}

# Register test playbooks
register_playbooks() {
    print_status "INFO" "Registering save storage test playbooks..."
    
    local base_path="./tests/fixtures/playbooks/save_storage_test"
    
    # Register simple test
    if .venv/bin/noetl playbook register "$base_path/save_simple_test.yaml" > /dev/null 2>&1; then
        print_status "SUCCESS" "Registered save_simple_test.yaml"
    else
        print_status "ERROR" "Failed to register save_simple_test.yaml"
    fi
    
    # Register comprehensive test
    if .venv/bin/noetl playbook register "$base_path/save_all_storage_types.yaml" > /dev/null 2>&1; then
        print_status "SUCCESS" "Registered save_all_storage_types.yaml"
    else
        print_status "ERROR" "Failed to register save_all_storage_types.yaml"
    fi
    
    # Register edge cases test
    if .venv/bin/noetl playbook register "$base_path/save_edge_cases.yaml" > /dev/null 2>&1; then
        print_status "SUCCESS" "Registered save_edge_cases.yaml"
    else
        print_status "ERROR" "Failed to register save_edge_cases.yaml"
    fi
}

# Check for required credentials
check_credentials() {
    print_status "INFO" "Checking for required credentials..."
    
    if .venv/bin/noetl credential list | grep -q "pg_k8s"; then
        print_status "SUCCESS" "pg_k8s credential found"
    else
        print_status "ERROR" "pg_k8s credential not found"
        echo "Please register the pg_k8s credential using:"
        echo "task register-test-credentials"
    fi
}

# Run simple test
run_simple_test() {
    print_status "INFO" "Running simple save storage test..."
    
    local execution_id
    execution_id=$(.venv/bin/noetl execution create tests/save_storage/simple --data '{}' | grep -o '"execution_id":"[^"]*"' | cut -d'"' -f4)
    
    if [ -n "$execution_id" ]; then
        print_status "SUCCESS" "Simple test started with execution ID: $execution_id"
        
        # Wait a bit and check status
        sleep 10
        local status
        status=$(.venv/bin/noetl execution get "$execution_id" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
        
        if [ "$status" = "completed" ]; then
            print_status "SUCCESS" "Simple test completed successfully"
        else
            print_status "INFO" "Simple test status: $status (may still be running)"
        fi
    else
        print_status "ERROR" "Failed to start simple test"
    fi
}

# Display help
show_help() {
    echo "Usage: $0 [COMMAND]"
    echo ""
    echo "Commands:"
    echo "  validate    - Run full validation suite"
    echo "  register    - Register test playbooks only"
    echo "  test        - Run simple test only"
    echo "  help        - Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 validate     # Full validation"
    echo "  $0 register     # Register playbooks"
    echo "  $0 test         # Run simple test"
}

# Main execution
main() {
    local command=${1:-validate}
    
    case $command in
        "validate")
            check_cluster
            check_noetl_services
            register_playbooks
            check_credentials
            run_simple_test
            print_status "SUCCESS" "Save storage test suite validation completed"
            ;;
        "register")
            register_playbooks
            ;;
        "test")
            run_simple_test
            ;;
        "help"|"-h"|"--help")
            show_help
            ;;
        *)
            print_status "ERROR" "Unknown command: $command"
            show_help
            exit 1
            ;;
    esac
}

# Run main function with all arguments
main "$@"