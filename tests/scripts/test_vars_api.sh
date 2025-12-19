#!/usr/bin/env bash
#
# Test Variable Management API endpoints
#
# Tests all four endpoints:
# - GET /api/vars/{execution_id} - List all variables
# - GET /api/vars/{execution_id}/{var_name} - Get specific variable
# - POST /api/vars/{execution_id} - Set variables
# - DELETE /api/vars/{execution_id}/{var_name} - Delete variable
#

set -e

API_URL="${NOETL_API_URL:-http://localhost:8082}"
PLAYBOOK_PATH="tests/fixtures/playbooks/vars_test/test_vars_api.yaml"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_test() {
    echo -e "${YELLOW}[TEST]${NC} $1"
}

# Step 1: Register playbook
log_info "Registering test playbook..."
PLAYBOOK_CONTENT=$(cat "$PLAYBOOK_PATH")
REGISTER_RESPONSE=$(curl -s -X POST "$API_URL/api/catalog/register" \
    -H "Content-Type: application/json" \
    -d "{\"content\": $(echo "$PLAYBOOK_CONTENT" | jq -Rs .), \"resource_type\": \"Playbook\"}")

CATALOG_ID=$(echo "$REGISTER_RESPONSE" | jq -r '.catalog_id')
VERSION=$(echo "$REGISTER_RESPONSE" | jq -r '.version')
log_info "Playbook registered: catalog_id=$CATALOG_ID, version=$VERSION"

# Step 2: Execute playbook
log_info "Executing playbook..."
EXEC_RESPONSE=$(curl -s -X POST "$API_URL/api/run/playbook" \
    -H "Content-Type: application/json" \
    -d "{\"catalog_id\": $CATALOG_ID, \"args\": {}}")

EXECUTION_ID=$(echo "$EXEC_RESPONSE" | jq -r '.execution_id')
log_info "Execution started: execution_id=$EXECUTION_ID"

# Wait for vars to be created
log_info "Waiting 8 seconds for vars block to process..."
sleep 8

# Step 3: Test GET /api/vars/{execution_id} - List all variables
log_test "TEST 1: GET /api/vars/$EXECUTION_ID (list all variables)"
LIST_RESPONSE=$(curl -s "$API_URL/api/vars/$EXECUTION_ID")
VAR_COUNT=$(echo "$LIST_RESPONSE" | jq -r '.count')
log_info "Response: Found $VAR_COUNT variables"
echo "$LIST_RESPONSE" | jq '.'

if [ "$VAR_COUNT" -ge 4 ]; then
    log_info "✓ TEST 1 PASSED: Found $VAR_COUNT variables (expected >= 4)"
else
    log_error "✗ TEST 1 FAILED: Expected >= 4 variables, got $VAR_COUNT"
    exit 1
fi

# Step 4: Test GET /api/vars/{execution_id}/{var_name} - Get specific variable
log_test "TEST 2: GET /api/vars/$EXECUTION_ID/test_user_id (get specific variable)"
GET_VAR_RESPONSE=$(curl -s "$API_URL/api/vars/$EXECUTION_ID/test_user_id")
VAR_VALUE=$(echo "$GET_VAR_RESPONSE" | jq -r '.value')
VAR_TYPE=$(echo "$GET_VAR_RESPONSE" | jq -r '.type')
ACCESS_COUNT=$(echo "$GET_VAR_RESPONSE" | jq -r '.access_count')
log_info "Response: value=$VAR_VALUE, type=$VAR_TYPE, access_count=$ACCESS_COUNT"
echo "$GET_VAR_RESPONSE" | jq '.'

if [ "$VAR_VALUE" == "999" ] && [ "$VAR_TYPE" == "step_result" ]; then
    log_info "✓ TEST 2 PASSED: Variable value and type correct"
else
    log_error "✗ TEST 2 FAILED: Expected value=999 type=step_result, got value=$VAR_VALUE type=$VAR_TYPE"
    exit 1
fi

# Step 5: Test POST /api/vars/{execution_id} - Set variables
log_test "TEST 3: POST /api/vars/$EXECUTION_ID (set new variables)"
POST_RESPONSE=$(curl -s -X POST "$API_URL/api/vars/$EXECUTION_ID" \
    -H "Content-Type: application/json" \
    -d '{
        "variables": {
            "api_injected_var": "test_value_from_api",
            "api_counter": 42,
            "api_config": {"enabled": true, "timeout": 30}
        },
        "var_type": "user_defined",
        "source_step": "api_test_script"
    }')

VARS_SET=$(echo "$POST_RESPONSE" | jq -r '.variables_set')
log_info "Response: variables_set=$VARS_SET"
echo "$POST_RESPONSE" | jq '.'

if [ "$VARS_SET" == "3" ]; then
    log_info "✓ TEST 3 PASSED: Set 3 variables via API"
else
    log_error "✗ TEST 3 FAILED: Expected 3 variables set, got $VARS_SET"
    exit 1
fi

# Step 6: Verify injected variable is accessible
log_test "TEST 4: GET /api/vars/$EXECUTION_ID/api_injected_var (verify injected variable)"
GET_INJECTED_RESPONSE=$(curl -s "$API_URL/api/vars/$EXECUTION_ID/api_injected_var")
INJECTED_VALUE=$(echo "$GET_INJECTED_RESPONSE" | jq -r '.value')
INJECTED_TYPE=$(echo "$GET_INJECTED_RESPONSE" | jq -r '.type')
INJECTED_SOURCE=$(echo "$GET_INJECTED_RESPONSE" | jq -r '.source_step')
log_info "Response: value=$INJECTED_VALUE, type=$INJECTED_TYPE, source=$INJECTED_SOURCE"
echo "$GET_INJECTED_RESPONSE" | jq '.'

if [ "$INJECTED_VALUE" == "test_value_from_api" ] && [ "$INJECTED_TYPE" == "user_defined" ]; then
    log_info "✓ TEST 4 PASSED: Injected variable accessible with correct type"
else
    log_error "✗ TEST 4 FAILED: Injected variable not accessible or incorrect type"
    exit 1
fi

# Step 7: List all variables again (should have original + injected)
log_test "TEST 5: GET /api/vars/$EXECUTION_ID (verify total count after injection)"
LIST_AFTER_RESPONSE=$(curl -s "$API_URL/api/vars/$EXECUTION_ID")
VAR_COUNT_AFTER=$(echo "$LIST_AFTER_RESPONSE" | jq -r '.count')
log_info "Response: Found $VAR_COUNT_AFTER variables after injection"

if [ "$VAR_COUNT_AFTER" -ge 7 ]; then
    log_info "✓ TEST 5 PASSED: Variable count increased (now $VAR_COUNT_AFTER)"
else
    log_error "✗ TEST 5 FAILED: Expected >= 7 variables, got $VAR_COUNT_AFTER"
    exit 1
fi

# Step 8: Test DELETE /api/vars/{execution_id}/{var_name}
log_test "TEST 6: DELETE /api/vars/$EXECUTION_ID/api_counter (delete variable)"
DELETE_RESPONSE=$(curl -s -X DELETE "$API_URL/api/vars/$EXECUTION_ID/api_counter")
DELETED=$(echo "$DELETE_RESPONSE" | jq -r '.deleted')
log_info "Response: deleted=$DELETED"
echo "$DELETE_RESPONSE" | jq '.'

if [ "$DELETED" == "true" ]; then
    log_info "✓ TEST 6 PASSED: Variable deleted successfully"
else
    log_error "✗ TEST 6 FAILED: Variable deletion failed"
    exit 1
fi

# Step 9: Verify deleted variable is gone
log_test "TEST 7: GET /api/vars/$EXECUTION_ID/api_counter (verify deletion)"
GET_DELETED_RESPONSE=$(curl -s -w "\n%{http_code}" "$API_URL/api/vars/$EXECUTION_ID/api_counter")
HTTP_CODE=$(echo "$GET_DELETED_RESPONSE" | tail -n1)
log_info "Response: HTTP status=$HTTP_CODE"

if [ "$HTTP_CODE" == "404" ]; then
    log_info "✓ TEST 7 PASSED: Deleted variable returns 404"
else
    log_error "✗ TEST 7 FAILED: Expected 404, got $HTTP_CODE"
    exit 1
fi

# Step 10: Test DELETE on non-existent variable
log_test "TEST 8: DELETE /api/vars/$EXECUTION_ID/nonexistent (delete non-existent variable)"
DELETE_NOTFOUND_RESPONSE=$(curl -s -X DELETE "$API_URL/api/vars/$EXECUTION_ID/nonexistent")
DELETED_NOTFOUND=$(echo "$DELETE_NOTFOUND_RESPONSE" | jq -r '.deleted')
log_info "Response: deleted=$DELETED_NOTFOUND"

if [ "$DELETED_NOTFOUND" == "false" ]; then
    log_info "✓ TEST 8 PASSED: Delete returns false for non-existent variable"
else
    log_error "✗ TEST 8 FAILED: Expected deleted=false for non-existent variable"
    exit 1
fi

# Final summary
echo ""
log_info "========================================="
log_info "ALL TESTS PASSED ✓"
log_info "========================================="
log_info "Execution ID: $EXECUTION_ID"
log_info "Tested endpoints:"
log_info "  - GET /api/vars/{execution_id}"
log_info "  - GET /api/vars/{execution_id}/{var_name}"
log_info "  - POST /api/vars/{execution_id}"
log_info "  - DELETE /api/vars/{execution_id}/{var_name}"
log_info "========================================="

# Cleanup: Print instructions
echo ""
log_info "To view all variables in database:"
echo "PGPASSWORD=demo psql -h localhost -p 54321 -U demo -d demo_noetl -c \"SELECT var_name, var_type, source_step, access_count FROM noetl.transient WHERE execution_id = $EXECUTION_ID ORDER BY created_at;\""

echo ""
log_info "To check execution events:"
echo "PGPASSWORD=demo psql -h localhost -p 54321 -U demo -d demo_noetl -c \"SELECT event_type, node_name, status FROM noetl.event WHERE execution_id = $EXECUTION_ID ORDER BY event_id;\""
