#!/bin/bash
# Test all pagination playbooks

set -e

echo "=== Registering Pagination Test Playbooks ==="
echo ""

# Register each playbook
declare -A PLAYBOOKS=(
  ["basic"]="tests/pagination/basic/basic"
  ["cursor"]="tests/pagination/cursor/cursor"
  ["offset"]="tests/pagination/offset/offset"
  ["max_iterations"]="tests/pagination/max_iterations/max_iterations"
  ["retry"]="tests/pagination/retry/retry"
  ["loop"]="tests/pagination/loop_with_pagination/loop_with_pagination"
)

declare -A PLAYBOOK_FILES=(
  ["basic"]="tests/fixtures/playbooks/pagination/basic/test_pagination_basic.yaml"
  ["cursor"]="tests/fixtures/playbooks/pagination/cursor/test_pagination_cursor.yaml"
  ["offset"]="tests/fixtures/playbooks/pagination/offset/test_pagination_offset.yaml"
  ["max_iterations"]="tests/fixtures/playbooks/pagination/max_iterations/test_pagination_max_iterations.yaml"
  ["retry"]="tests/fixtures/playbooks/pagination/retry/test_pagination_retry.yaml"
  ["loop"]="tests/fixtures/playbooks/pagination/loop_with_pagination/test_loop_with_pagination.yaml"
)

# Register playbooks
for name in "${!PLAYBOOKS[@]}"; do
  path="${PLAYBOOKS[$name]}"
  file="${PLAYBOOK_FILES[$name]}"
  echo "▶ Registering $name: $path"
  
  result=$(curl -s http://localhost:8082/api/catalog/register -X POST \
    -H "Content-Type: application/json" \
    --data-binary @<(jq -n --rawfile content "$file" "{path: \"$path\", content: \$content}"))
  
  status=$(echo "$result" | jq -r '.status // "error"')
  version=$(echo "$result" | jq -r '.version // "?"')
  echo "  ✓ Status: $status (version $version)"
done

echo ""
echo "=== Running Pagination Tests ==="
echo ""

# Reset flaky counters
echo "▶ Resetting test server flaky counters..."
curl -s -X POST http://localhost:30555/api/v1/flaky/reset > /dev/null
echo "  ✓ Reset complete"
echo ""

# Run tests (excluding loop for now)
declare -a TEST_ORDER=("basic" "cursor" "offset" "max_iterations" "retry")

for name in "${TEST_ORDER[@]}"; do
  path="${PLAYBOOKS[$name]}"
  echo "▶ Running: $name ($path)"
  
  exec_id=$(curl -s http://localhost:8082/api/run/playbook -X POST \
    -H "Content-Type: application/json" \
    -d "{\"path\": \"$path\"}" | jq -r '.execution_id')
  
  if [ "$exec_id" = "null" ] || [ -z "$exec_id" ]; then
    echo "  ✗ Failed to start execution"
    continue
  fi
  
  echo "  Execution ID: $exec_id"
  sleep 15
  
  # Get results
  count=$(curl -s http://localhost:8082/api/postgres/execute \
    -H "Content-Type: application/json" \
    -d "{\"query\": \"SELECT jsonb_array_length(result->'result') FROM noetl.event WHERE execution_id = $exec_id AND event_type = 'action_completed' LIMIT 1\", \"schema\": \"noetl\"}" | \
    jq -r '.result[0][0] // "?"')
  
  # For retry test, also check retry_worked
  if [ "$name" = "retry" ]; then
    retry_worked=$(curl -s http://localhost:8082/api/postgres/execute \
      -H "Content-Type: application/json" \
      -d "{\"query\": \"SELECT result->'retry_worked' FROM noetl.event WHERE execution_id = $exec_id AND event_type = 'action_completed'\", \"schema\": \"noetl\"}" | \
      jq -r '.result[0][0] // "?"')
    echo "  ✓ Items: $count, Retry worked: $retry_worked"
  else
    echo "  ✓ Items: $count"
  fi
  echo ""
done

# Run loop test
echo "▶ Running: loop (${PLAYBOOKS[loop]})"
exec_id=$(curl -s http://localhost:8082/api/run/playbook -X POST \
  -H "Content-Type: application/json" \
  -d "{\"path\": \"${PLAYBOOKS[loop]}\"}" | jq -r '.execution_id')

if [ "$exec_id" != "null" ] && [ -n "$exec_id" ]; then
  echo "  Execution ID: $exec_id"
  sleep 30
  
  # Get item counts for each iteration
  echo "  Iteration results:"
  for i in 0 1 2; do
    count=$(curl -s http://localhost:8082/api/postgres/execute \
      -H "Content-Type: application/json" \
      -d "{\"query\": \"SELECT jsonb_array_length(result->'result') FROM noetl.event WHERE execution_id = $exec_id AND node_name = 'fetch_all_endpoints_iter_$i' AND event_type = 'action_completed'\", \"schema\": \"noetl\"}" | \
      jq -r '.result[0][0] // "?"')
    echo "    iter_$i: $count items"
  done
else
  echo "  ✗ Failed to start execution"
fi

echo ""
echo "=== Test Summary ==="
echo "All pagination tests completed!"
