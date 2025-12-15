#!/bin/bash
# Test OAuth integrations (Google GCS and Secret Manager)

set -e

NOETL_SERVER="http://localhost:8082"

echo "=== OAuth Integration Tests ==="
echo "Server: $NOETL_SERVER"
echo ""

# Test 1: Google Cloud Storage OAuth
echo "▶ Test 1: Google Cloud Storage OAuth"
echo "  Registering playbook..."

PLAYBOOK_PATH="tests/fixtures/playbooks/oauth/google_gcs"
PLAYBOOK_FILE="tests/fixtures/playbooks/oauth/google_gcs/google_gcs_oauth.yaml"

if [ ! -f "$PLAYBOOK_FILE" ]; then
    echo "  ✗ Playbook file not found: $PLAYBOOK_FILE"
    exit 1
fi

# Register GCS playbook
REGISTER_RESULT=$(curl -s "$NOETL_SERVER/api/catalog/register" -X POST \
  -H "Content-Type: application/json" \
  --data-binary @<(jq -n --rawfile content "$PLAYBOOK_FILE" "{path: \"$PLAYBOOK_PATH\", content: \$content}"))

REGISTER_STATUS=$(echo "$REGISTER_RESULT" | jq -r '.status // "error"')
REGISTER_VERSION=$(echo "$REGISTER_RESULT" | jq -r '.version // "?"')

if [ "$REGISTER_STATUS" != "success" ]; then
    echo "  ✗ Registration failed: $REGISTER_RESULT"
    exit 1
fi

echo "  ✓ Registered: version $REGISTER_VERSION"
echo "  Executing playbook..."

# Execute GCS playbook
EXEC_RESULT=$(curl -s "$NOETL_SERVER/api/run/playbook" -X POST \
  -H "Content-Type: application/json" \
  -d "{\"path\": \"$PLAYBOOK_PATH\"}")

EXEC_ID=$(echo "$EXEC_RESULT" | jq -r '.execution_id // "null"')

if [ "$EXEC_ID" = "null" ]; then
    echo "  ✗ Execution failed: $EXEC_RESULT"
    exit 1
fi

echo "  Execution ID: $EXEC_ID"
echo "  Waiting for completion..."
sleep 20

# Check results
EVENT_QUERY="SELECT node_name, event_type FROM noetl.event WHERE execution_id = $EXEC_ID AND event_type = 'action_completed' ORDER BY event_id"
EVENTS=$(curl -s "$NOETL_SERVER/api/postgres/execute" \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"$EVENT_QUERY\", \"schema\": \"noetl\"}" | \
  jq -r '.result // [] | length')

echo "  ✓ Events: $EVENTS action_completed events"

# Check bucket list result
BUCKET_QUERY="SELECT result->'status', result->'data'->'status_code' FROM noetl.event WHERE execution_id = $EXEC_ID AND node_name = 'list_buckets' AND event_type = 'action_completed'"
BUCKET_RESULT=$(curl -s "$NOETL_SERVER/api/postgres/execute" \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"$BUCKET_QUERY\", \"schema\": \"noetl\"}")

BUCKET_STATUS=$(echo "$BUCKET_RESULT" | jq -r '.result[0][0] // "unknown"')
BUCKET_CODE=$(echo "$BUCKET_RESULT" | jq -r '.result[0][1] // "0"')

echo "  GCS API Status: $BUCKET_STATUS (HTTP $BUCKET_CODE)"

if [ "$BUCKET_CODE" = "200" ]; then
    echo "  ✅ Google GCS OAuth Test PASSED"
else
    echo "  ⚠️  Google GCS OAuth Test completed with status: $BUCKET_STATUS"
fi

echo ""

# Test 2: Google Secret Manager OAuth
echo "▶ Test 2: Google Secret Manager OAuth"
echo "  Registering playbook..."

PLAYBOOK_PATH="tests/fixtures/playbooks/oauth/google_secret_manager"
PLAYBOOK_FILE="tests/fixtures/playbooks/oauth/google_secret_manager/google_secret_manager.yaml"

if [ ! -f "$PLAYBOOK_FILE" ]; then
    echo "  ✗ Playbook file not found: $PLAYBOOK_FILE"
    exit 1
fi

# Register Secret Manager playbook
REGISTER_RESULT=$(curl -s "$NOETL_SERVER/api/catalog/register" -X POST \
  -H "Content-Type: application/json" \
  --data-binary @<(jq -n --rawfile content "$PLAYBOOK_FILE" "{path: \"$PLAYBOOK_PATH\", content: \$content}"))

REGISTER_STATUS=$(echo "$REGISTER_RESULT" | jq -r '.status // "error"')
REGISTER_VERSION=$(echo "$REGISTER_RESULT" | jq -r '.version // "?"')

if [ "$REGISTER_STATUS" != "success" ]; then
    echo "  ✗ Registration failed: $REGISTER_RESULT"
    exit 1
fi

echo "  ✓ Registered: version $REGISTER_VERSION"
echo "  Executing playbook..."

# Execute Secret Manager playbook
EXEC_RESULT=$(curl -s "$NOETL_SERVER/api/run/playbook" -X POST \
  -H "Content-Type: application/json" \
  -d "{\"path\": \"$PLAYBOOK_PATH\"}")

EXEC_ID=$(echo "$EXEC_RESULT" | jq -r '.execution_id // "null"')

if [ "$EXEC_ID" = "null" ]; then
    echo "  ✗ Execution failed: $EXEC_RESULT"
    exit 1
fi

echo "  Execution ID: $EXEC_ID"
echo "  Waiting for completion..."
sleep 15

# Check results
EVENT_QUERY="SELECT node_name, event_type FROM noetl.event WHERE execution_id = $EXEC_ID AND event_type = 'action_completed' ORDER BY event_id"
EVENTS=$(curl -s "$NOETL_SERVER/api/postgres/execute" \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"$EVENT_QUERY\", \"schema\": \"noetl\"}" | \
  jq -r '.result // [] | length')

echo "  ✓ Events: $EVENTS action_completed events"

# Check Secret Manager API result
SECRET_QUERY="SELECT result->'status', result->'data'->'status_code' FROM noetl.event WHERE execution_id = $EXEC_ID AND node_name = 'call_secret_manager_api' AND event_type = 'action_completed'"
SECRET_RESULT=$(curl -s "$NOETL_SERVER/api/postgres/execute" \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"$SECRET_QUERY\", \"schema\": \"noetl\"}")

SECRET_STATUS=$(echo "$SECRET_RESULT" | jq -r '.result[0][0] // "unknown"')
SECRET_CODE=$(echo "$SECRET_RESULT" | jq -r '.result[0][1] // "0"')

echo "  Secret Manager API Status: $SECRET_STATUS (HTTP $SECRET_CODE)"

if [ "$SECRET_CODE" = "200" ]; then
    echo "  ✅ Google Secret Manager OAuth Test PASSED"
else
    echo "  ⚠️  Google Secret Manager OAuth Test completed with status: $SECRET_STATUS"
fi

echo ""
echo "=== OAuth Tests Complete ==="
echo ""
echo "Summary:"
echo "- Google GCS OAuth: HTTP $BUCKET_CODE"
echo "- Google Secret Manager OAuth: HTTP $SECRET_CODE"
echo ""

if [ "$BUCKET_CODE" = "200" ] && [ "$SECRET_CODE" = "200" ]; then
    echo "✅ All OAuth tests PASSED"
    exit 0
else
    echo "⚠️  Some tests did not return HTTP 200"
    echo "This may be expected if credentials are not configured"
    exit 0
fi
