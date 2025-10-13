#!/bin/bash

# Script to register all test playbooks in the fixtures directory
# Usage: ./register_test_playbooks.sh [host] [port]

HOST=${1:-localhost}
PORT=${2:-8082}
BASE_DIR="./tests/fixtures/playbooks"

echo "Registering all test playbooks with NoETL server at $HOST:$PORT"
echo "Base directory: $BASE_DIR"
echo ""

# Initialize counters
success_count=0
error_count=0
total_count=0

# Function to register a single playbook
register_playbook() {
    local playbook_path="$1"
    local relative_path="${playbook_path#$BASE_DIR/}"
    
    echo "Registering: $relative_path"
    
    if .venv/bin/noetl register "$playbook_path" --host "$HOST" --port "$PORT" 2>/dev/null; then
        echo "  SUCCESS"
        ((success_count++))
    else
        echo "  ERROR"
        ((error_count++))
    fi
    
    ((total_count++))
    echo ""
}

# Find and register all YAML files in the fixtures directory
while IFS= read -r -d '' playbook_file; do
    register_playbook "$playbook_file"
done < <(find "$BASE_DIR" -name "*.yaml" -type f -print0)

# Print summary
echo "========================================="
echo "Registration Summary:"
echo "  Total playbooks: $total_count"
echo "  Successful: $success_count"
echo "  Errors: $error_count"
echo "========================================="

if [ $error_count -eq 0 ]; then
    echo "All playbooks registered successfully!"
    exit 0
else
    echo "WARNING: Some playbooks failed to register."
    exit 1
fi