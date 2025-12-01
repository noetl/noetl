#!/bin/bash
# Register all test credentials with NoETL after a reset
# This includes the standard test credentials plus optional OAuth credentials

set -e

NOETL_HOST="${NOETL_HOST:-localhost}"
NOETL_PORT="${NOETL_PORT:-8083}"
BASE_URL="http://${NOETL_HOST}:${NOETL_PORT}"

echo "🔐 Registering test credentials with NoETL..."
echo "   Server: $BASE_URL"
echo ""

CREDS_DIR="tests/fixtures/credentials"
SUCCESS_COUNT=0
SKIP_COUNT=0
ERROR_COUNT=0

# Function to register a credential
register_credential() {
    local file=$1
    local name=$(basename "$file" .json)
    
    if [ ! -f "$file" ]; then
        echo "⏭️  Skipped: $name (file not found)"
        ((SKIP_COUNT++))
        return
    fi
    
    # Check if it's an example file
    if [[ "$file" == *.example ]]; then
        echo "⏭️  Skipped: $name (example file)"
        ((SKIP_COUNT++))
        return
    fi
    
    echo -n "📝 Registering: $name ... "
    
    response=$(curl -s -X POST "$BASE_URL/api/credentials" \
        -H 'Content-Type: application/json' \
        --data-binary "@$file" \
        -w "\n%{http_code}")
    
    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | sed '$d')
    
    if [ "$http_code" = "200" ] || [ "$http_code" = "201" ]; then
        echo "✅"
        ((SUCCESS_COUNT++))
    else
        echo "❌ (HTTP $http_code)"
        echo "   Response: $body" | head -c 100
        ((ERROR_COUNT++))
    fi
}

# Register standard test credentials (these should always exist)
echo "📦 Standard Test Credentials:"
register_credential "$CREDS_DIR/pg_local.json"
register_credential "$CREDS_DIR/sf_test.json"
register_credential "$CREDS_DIR/gcs_hmac_local.json"

echo ""
echo "🔑 OAuth Credentials (optional):"
register_credential "$CREDS_DIR/google_oauth.json"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Summary:"
echo "   ✅ Success: $SUCCESS_COUNT"
echo "   ⏭️  Skipped: $SKIP_COUNT"
echo "   ❌ Failed:  $ERROR_COUNT"
echo ""

if [ $ERROR_COUNT -gt 0 ]; then
    echo "⚠️  Some credentials failed to register"
    exit 1
fi

if [ $SUCCESS_COUNT -eq 0 ]; then
    echo "ℹ️  No credentials were registered"
    echo ""
    echo "💡 To set up OAuth credentials, run:"
    echo "   ./tests/fixtures/credentials/copy_gcloud_credentials.sh"
    exit 0
fi

echo "✅ All available credentials registered successfully!"
echo ""
echo "🔍 Verify with:"
echo "   curl $BASE_URL/api/credentials | jq '.items[] | {name, type}'"
