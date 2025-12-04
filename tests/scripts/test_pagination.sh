#!/usr/bin/env bash
set -euo pipefail

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
API_URL="http://localhost:8082/api"
TEST_DIR="tests/fixtures/playbooks/pagination"
MOCK_SERVER_PORT=5555

echo -e "${YELLOW}Pagination Feature Test Suite${NC}"
echo "========================================"
echo ""

# Test counter
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Function to run a test
run_test() {
    local test_name="$1"
    local playbook_path="$2"
    local description="$3"
    
    TESTS_RUN=$((TESTS_RUN + 1))
    
    echo -e "\n${YELLOW}Test $TESTS_RUN: $test_name${NC}"
    echo "Description: $description"
    echo "Playbook: $playbook_path"
    echo ""
    
    # Register playbook
    echo "Registering playbook..."
    PLAYBOOK_CONTENT=$(cat "$playbook_path")
    REGISTER_RESPONSE=$(curl -s -X POST "$API_URL/catalog/register" \
        -H "Content-Type: application/json" \
        -d "{\"content\": $(jq -Rs . <<< "$PLAYBOOK_CONTENT")}")
    
    echo "Register response: $REGISTER_RESPONSE"
    
    # Execute playbook
    echo "Executing playbook..."
    EXEC_RESPONSE=$(curl -s -X POST "$API_URL/run/playbook" \
        -H "Content-Type: application/json" \
        -d "{\"path\": \"$test_name\"}")
    
    echo "Execution response: $EXEC_RESPONSE"
    
    # Extract execution_id
    EXECUTION_ID=$(echo "$EXEC_RESPONSE" | jq -r '.execution_id // .id // empty')
    
    if [ -z "$EXECUTION_ID" ]; then
        echo -e "${RED}✗ FAILED: Could not extract execution_id${NC}"
        TESTS_FAILED=$((TESTS_FAILED + 1))
        return 1
    fi
    
    echo "Execution ID: $EXECUTION_ID"
    
    # Wait for completion
    echo "Waiting for execution to complete..."
    MAX_WAIT=60
    ELAPSED=0
    
    while [ $ELAPSED -lt $MAX_WAIT ]; do
        STATUS_RESPONSE=$(curl -s "$API_URL/execution/${EXECUTION_ID}/status")
        STATUS=$(echo "$STATUS_RESPONSE" | jq -r '.status // empty')
        
        echo "Status: $STATUS"
        
        if [ "$STATUS" == "completed" ] || [ "$STATUS" == "success" ]; then
            echo -e "${GREEN}✓ PASSED: $test_name${NC}"
            TESTS_PASSED=$((TESTS_PASSED + 1))
            return 0
        elif [ "$STATUS" == "failed" ] || [ "$STATUS" == "error" ]; then
            echo -e "${RED}✗ FAILED: $test_name${NC}"
            echo "Error details: $STATUS_RESPONSE"
            TESTS_FAILED=$((TESTS_FAILED + 1))
            return 1
        fi
        
        sleep 2
        ELAPSED=$((ELAPSED + 2))
    done
    
    echo -e "${RED}✗ FAILED: Timeout waiting for execution${NC}"
    TESTS_FAILED=$((TESTS_FAILED + 1))
    return 1
}

# Check mock server
echo "Checking mock server at localhost:$MOCK_SERVER_PORT..."
if ! curl -s "http://localhost:$MOCK_SERVER_PORT/health" > /dev/null; then
    echo -e "${RED}ERROR: Mock server not running${NC}"
    echo "Please start it with: python tests/fixtures/servers/paginated_api.py $MOCK_SERVER_PORT"
    exit 1
fi
echo -e "${GREEN}Mock server is running${NC}"
echo ""

# Check NoETL API
echo "Checking NoETL API at $API_URL..."
if ! curl -s "$API_URL/health" > /dev/null; then
    echo -e "${RED}ERROR: NoETL API not accessible${NC}"
    echo "Please ensure NoETL server is running"
    exit 1
fi
echo -e "${GREEN}NoETL API is accessible${NC}"
echo ""

# Run tests
run_test "tests/pagination/basic" \
    "$TEST_DIR/test_pagination_basic.yaml" \
    "Page-number pagination with hasMore flag"

run_test "tests/pagination/offset" \
    "$TEST_DIR/test_pagination_offset.yaml" \
    "Offset-based pagination"

run_test "tests/pagination/cursor" \
    "$TEST_DIR/test_pagination_cursor.yaml" \
    "Cursor-based pagination"

run_test "tests/pagination/max_iterations" \
    "$TEST_DIR/test_pagination_max_iterations.yaml" \
    "Max iterations safety limit"

# Note: Retry test might be flaky, run last
run_test "tests/pagination/retry" \
    "$TEST_DIR/test_pagination_retry.yaml" \
    "Pagination with retry on failures"

# Summary
echo ""
echo "========================================"
echo -e "${YELLOW}Test Summary${NC}"
echo "========================================"
echo "Tests run: $TESTS_RUN"
echo -e "${GREEN}Tests passed: $TESTS_PASSED${NC}"
echo -e "${RED}Tests failed: $TESTS_FAILED${NC}"
echo ""

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}All pagination tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some pagination tests failed${NC}"
    exit 1
fi
