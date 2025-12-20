#!/bin/bash

# Script to register all test playbooks in the fixtures directory
# Usage: ./register_test_playbooks.sh [host] [port]

HOST=${1:-localhost}
PORT=${2:-8082}
BASE_DIR="./tests/fixtures/playbooks"

echo "Registering all test playbooks with NoETL server at $HOST:$PORT"
echo "Base directory: $BASE_DIR"
echo ""

# Verify server health before proceeding
health_status=$(curl -s -o /dev/null -w "%{http_code}" "http://$HOST:$PORT/api/health" || true)
if [ "$health_status" != "200" ]; then
  echo "ERROR: NoETL server at http://$HOST:$PORT/api/health is not healthy (status: $health_status)"
  exit 1
fi

# Initialize counters
success_count=0
error_count=0
total_count=0

# Function to register a single playbook
register_playbook() {
    local playbook_path="$1"
    local relative_path="${playbook_path#$BASE_DIR/}"

    echo "Registering: $relative_path"

    # Capture output and errors
    output=$(.venv/bin/noetl register "$playbook_path" --host "$HOST" --port "$PORT" 2>&1)
    exit_code=$?

    if [ $exit_code -eq 0 ]; then
        echo "  SUCCESS"
        ((success_count++))
    else
        echo "  ERROR"
        echo "  $output" | head -3  # Show first 3 lines of error
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
