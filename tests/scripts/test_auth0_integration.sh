#!/bin/bash
set -e

echo "=== Auth0 Full Integration Test Setup ==="
echo ""
echo "This script will:"
echo "1. Register Auth0 client secret as NoETL credential (one-time setup)"
echo "2. Register Auth0 playbooks"
echo "3. Test the full Auth0 flow"
echo ""

# Check if user password is provided
if [ -z "$AUTH0_USER_PASSWORD" ]; then
    echo "ERROR: AUTH0_USER_PASSWORD environment variable not set"
    echo ""
    echo "Usage:"
    echo "  export AUTH0_USER_PASSWORD='password_for_kadyapam@gmail.com'"
    echo "  $0 [client_secret]"
    echo ""
    echo "Optional: Pass client_secret as argument to register/update it:"
    echo "  $0 'your_auth0_client_secret'"
    echo ""
    echo "Or use credential file (recommended):"
    echo "  1. cp tests/fixtures/credentials/auth0_client.json.example \\"
    echo "     tests/fixtures/credentials/auth0_client.json"
    echo "  2. Edit auth0_client.json with your client_secret"
    echo "  3. Run: $0 --use-file"
    exit 1
fi

NOETL_API="http://localhost:8082"
CLIENT_SECRET="${1:-}"
CRED_FILE="tests/fixtures/credentials/auth0_client.json"

echo "Note: Auth0 credentials should be registered via NoETL API endpoint"
echo "      Keychain will resolve credential fields automatically"
echo ""

# Step 1: Register or update Auth0 client credential
if [ "$CLIENT_SECRET" = "--use-file" ]; then
    echo "Step 1: Register Auth0 credential from file"
    
    if [ ! -f "$CRED_FILE" ]; then
        echo ""
        echo "ERROR: Credential file not found: $CRED_FILE"
        echo ""
        echo "Please create it from the example:"
        echo "  cp ${CRED_FILE}.example $CRED_FILE"
        echo "  # Edit $CRED_FILE with your client_secret"
        exit 1
    fi
    
    # Register via NoETL API
    response=$(curl -s -X POST "$NOETL_API/api/credentials" \
        -H 'Content-Type: application/json' \
        --data-binary "@$CRED_FILE" \
        -w "\n%{http_code}")
    
    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | sed '$d')
    
    if [ "$http_code" = "200" ] || [ "$http_code" = "201" ]; then
        echo "✓ Auth0 client credential registered from file"
        echo "  Credential fields available via keychain:"
        echo "    - keychain.auth0_credentials.domain"
        echo "    - keychain.auth0_credentials.client_id"
        echo "    - keychain.auth0_credentials.client_secret"
        echo "    - keychain.auth0_credentials.audience"
    else
        echo "✗ Failed to register credential: HTTP $http_code"
        echo "$body"
        exit 1
    fi
elif [ -n "$CLIENT_SECRET" ]; then
    echo "Step 1: Register Auth0 client secret via API"
    echo "WARNING: Direct SQL INSERT is deprecated. Use --use-file method instead."
    echo ""
    
    # Create temporary JSON payload
    temp_json=$(mktemp)
    cat > "$temp_json" << JSON
{
  "name": "auth0_client",
  "type": "auth0",
  "description": "Auth0 SPA client credentials for user authentication",
  "tags": ["auth0", "authentication", "oauth"],
  "data": {
    "domain": "mestumre-development.us.auth0.com",
    "client_id": "Jqop7YoaiZalLHdBRo5ScNQ1RJhbhbDN",
    "client_secret": "$CLIENT_SECRET",
    "audience": "https://mestumre-development.us.auth0.com/me/",
    "grant_types": ["password", "authorization_code"],
    "token_endpoint": "https://mestumre-development.us.auth0.com/oauth/token",
    "userinfo_endpoint": "https://mestumre-development.us.auth0.com/userinfo"
  }
}
JSON

    # Register via NoETL API
    response=$(curl -s -X POST "$NOETL_API/api/credentials" \
        -H 'Content-Type: application/json' \
        --data-binary "@$temp_json" \
        -w "\n%{http_code}")
    
    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | sed '$d')
    
    rm -f "$temp_json"
    
    if [ "$http_code" = "200" ] || [ "$http_code" = "201" ]; then
        echo "✓ Auth0 client credential registered via API"
    else
        echo "✗ Failed to register credential: HTTP $http_code"
        echo "$body"
        exit 1
    fi
else
    echo "Step 1: Check if Auth0 credential exists"
    CRED_CHECK=$(kubectl exec -n postgres deployment/postgres -- \
      psql -U demo -d demo_noetl -t -c \
      "SELECT COUNT(*) FROM noetl.credential WHERE key = 'auth0_client';" | tr -d '[:space:]')
    
    if [ "$CRED_CHECK" = "0" ]; then
        echo ""
        echo "ERROR: Auth0 client credential not found in database"
        echo ""
        echo "Please register it first using one of these methods:"
        echo ""
        echo "Method 1 (Recommended): Use credential file"
        echo "  cp ${CRED_FILE}.example $CRED_FILE"
        echo "  # Edit with your client_secret"
        echo "  $0 --use-file"
        echo ""
        echo "Method 2: Pass as argument"
        echo "  $0 'your_auth0_client_secret'"
        exit 1
    fi
    echo "✓ Auth0 client credential found"
fi

echo "Step 2: Register Auth0 playbooks"
python3 << 'PYTHON'
import requests

playbooks = [
    "tests/fixtures/playbooks/api_integration/auth0/auth0_login.yaml",
    "tests/fixtures/playbooks/api_integration/auth0/provision_auth_schema.yaml",
    "tests/fixtures/playbooks/api_integration/auth0/auth0_validate_session.yaml"
]

for playbook_file in playbooks:
    try:
        with open(playbook_file, 'r') as f:
            content = f.read()
        
        response = requests.post(
            "http://localhost:8082/api/catalog/register",
            json={"content": content}
        )
        if response.status_code == 200:
            data = response.json()
            print(f"✓ Registered: {data['path']} v{data['version']}")
        else:
            print(f"✗ Failed to register {playbook_file}: {response.text}")
    except Exception as e:
        print(f"✗ Error with {playbook_file}: {e}")
PYTHON

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Auth0 Configuration:"
echo "  Domain: mestumre-development.us.auth0.com"
echo "  Client ID: Jqop7YoaiZalLHdBRo5ScNQ1RJhbhbDN"
echo "  User: kadyapam@gmail.com"
echo "  Test User (local): test@example.com"
echo ""
echo "Next Steps:"
echo "  1. Go to: http://localhost:8080/login.html"
echo "  2. Click 'Sign In with Auth0'"
echo "  3. Login as kadyapam@gmail.com (Auth0 will redirect back with token)"
echo "  4. Check that user is created in auth.users table"
echo "  5. Verify session_token is stored"
echo ""
echo "Manual Testing Commands:"
echo ""
echo "  # Test auth0_login with real token from browser"
echo "  AUTH0_TOKEN='<paste_access_token>'"
echo "  curl -X POST http://localhost:8082/api/execute -H 'Content-Type: application/json' -d '{\"path\": \"api_integration/auth0/auth0_login\", \"workload\": {\"auth0_token\": \"'\$AUTH0_TOKEN'\", \"client_ip\": \"127.0.0.1\"}}'"
echo ""
echo "  # Verify user created"
echo "  kubectl exec -n postgres deployment/postgres -- psql -U demo -d demo_noetl -c \"SELECT * FROM auth.users;\""
echo ""
