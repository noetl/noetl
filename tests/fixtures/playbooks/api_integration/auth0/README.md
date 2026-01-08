# Auth0 Integration Playbooks

This directory contains playbooks for Auth0 authentication integration with noetl-gateway.

## ⚡ Quick Start (Working Implementation)

The Auth0 integration uses **OAuth Implicit Flow** with browser-based authentication. No passwords are needed in environment variables.

### Prerequisites

- Kind cluster running with NoETL deployed
- Gateway UI deployed to `gateway` namespace
- PostgreSQL running in `postgres` namespace
- Auth0 application configured (see [Auth0 Setup](#auth0-setup-one-time-configuration))

### One-Time Setup

```bash
# 1. Register credentials (Postgres for database access)
cd /Users/akuksin/projects/noetl/noetl
task register-test-credentials

# 2. Register auth playbooks and provision schema
bash tests/scripts/test_auth0_integration.sh
```

**What this does:**
- Registers `auth0_login` playbook (handles OAuth callback, creates users and sessions)
- Registers `provision_auth_schema` playbook (creates auth database tables)
- Registers `auth0_validate_session` playbook (validates session tokens)
- Provisions `auth` schema with 8 tables (users, sessions, roles, permissions, etc.)

### Testing the Integration

1. **Open browser to:** http://localhost:8080/login.html
2. **Click "Sign In with Auth0"**
3. **Login with Auth0 credentials** (e.g., kadyapam@gmail.com)
4. **Auth0 redirects back** with id_token in URL hash
5. **UI automatically:**
   - Calls `/api/execute` with `payload: {auth0_token: idToken, client_ip: '127.0.0.1'}`
   - Polls database for session_token (20 attempts, 500ms interval)
   - Stores session_token in localStorage
   - Redirects to /dashboard.html

### Key Implementation Details

**OAuth Flow:**
- Response type: `id_token token` (gets both ID token and access token)
- Scopes: `openid profile email`
- No audience parameter (standard OpenID Connect only)
- ID token is JWT - decoded directly in playbook without external API calls

**JWT Decoding (No External Libraries):**
The `auth0_login` playbook decodes the JWT using Python's built-in base64 module:
```python
parts = token.split('.')
payload = parts[1]
padding = 4 - (len(payload) % 4)
if padding != 4: payload += '=' * padding
decoded = json.loads(base64.urlsafe_b64decode(payload))
```

**Session Token Generation:**
Uses PostgreSQL's built-in functions (no pgcrypto extension required):
```sql
md5(random()::text || clock_timestamp()::text)
```

**NoETL V2 API:**
- Endpoint: `POST /api/execute`
- Payload field: `payload` (NOT `workload` - workload is for playbook defaults only)
- Runtime parameters must be passed in `payload` field

**Postgres Tool Result Format:**
- Returns: `{command_0: {rows: [...], status: "success", columns: [...]}}`
- Access results: `stepname.command_0.rows[0].field`
- Case conditions check: `result.command_0 is defined`

**Database Query from UI:**
- API: `POST /api/postgres/execute`
- Returns: `{status: "ok", result: [["value1"], ["value2"]], error: null}`
- Format: Array of arrays (NOT array of objects)
- Access: `result[0][0]` for first row, first column

### Verifying the Setup

```bash
# Check auth tables exist
kubectl exec -n postgres deployment/postgres -- \
  psql -U demo -d demo_noetl -c "\dt auth.*"

# View recent sessions
kubectl exec -n postgres deployment/postgres -- \
  psql -U demo -d demo_noetl -c \
  "SELECT LEFT(session_token, 20), user_id, created_at 
   FROM auth.sessions ORDER BY created_at DESC LIMIT 3;"

# View users
kubectl exec -n postgres deployment/postgres -- \
  psql -U demo -d demo_noetl -c \
  "SELECT user_id, email, auth0_id, is_active 
   FROM auth.users;"
```

### Troubleshooting

**"Session token not found after login":**
- Check execution completed: `curl http://localhost:8082/api/executions | jq '.[] | select(.path == "api_integration/auth0/auth0_login") | {execution_id, status}'`
- Verify session created: `kubectl exec -n postgres deployment/postgres -- psql -U demo -d demo_noetl -c "SELECT COUNT(*) FROM auth.sessions WHERE created_at > NOW() - INTERVAL '5 minutes';"`
- Check browser console for detailed error messages

**"Execution stuck at create_session step":**
- This was a bug in v14 and earlier - case conditions were checking `response is defined` instead of `result.command_0 is defined`
- Upgrade to v15+ by re-running `bash tests/scripts/test_auth0_integration.sh`

**"gen_random_bytes() function does not exist":**
- This was fixed in v13+ by switching to `md5(random())` which doesn't require pgcrypto extension
- Re-register playbook to get the fix

### File Structure

- **`auth0_login.yaml`** (v15) - Main authentication playbook with JWT decoding
- **`provision_auth_schema.yaml`** - Creates database tables
- **`auth0_validate_session.yaml`** - Validates session tokens
- **`tests/scripts/test_auth0_integration.sh`** - Setup script
- **`tests/fixtures/gateway_ui/login.html`** - Frontend OAuth implementation
- **`ci/manifests/gateway/configmap-ui-files.yaml`** - Kubernetes ConfigMap with UI assets

---

This directory contains playbooks for Auth0 authentication integration with noetl-gateway.

## Auth0 Setup (One-Time Configuration)

### 1. Create Auth0 Application

1. Go to [Auth0 Dashboard](https://manage.auth0.com/)
2. Navigate to **Applications** → **Create Application**
3. Choose **Single Page Web Applications** (SPA)
4. Name it (e.g., "NoETL Gateway")
5. Click **Create**

### 2. Configure Application Settings

In your Auth0 application settings:

**Allowed Callback URLs:**
```
http://localhost:8080/callback
http://localhost:8080
```

**Allowed Logout URLs:**
```
http://localhost:8080
```

**Allowed Web Origins:**
```
http://localhost:8080
```

**Allowed Origins (CORS):**
```
http://localhost:8080
```

**Note:** For production, replace `localhost:8080` with your actual domain and use HTTPS.

### 3. Save Credentials

Copy these values from the Auth0 application **Settings** tab:
- **Domain** (e.g., `mestumre-development.us.auth0.com`)
- **Client ID** (e.g., `Jqop7YoaiZalLHdBRo5ScNQ1RJhbhbDN`)

These are already configured in:
- `tests/fixtures/gateway_ui/config.js` - Frontend configuration
- Auth playbooks workload defaults

### 4. Create Test User (Optional)

In Auth0 Dashboard:
1. Navigate to **User Management** → **Users**
2. Click **Create User**
3. Set email and password
4. Click **Create**

## Quick Start - Step by Step

### Step 1: Deploy Infrastructure

```bash
# Deploy gateway and UI to kind cluster
task gateway-deploy-all

# Verify services are running
kubectl get pods -n gateway
task gateway-status
```

**Expected output:**
```
gateway-<hash>     1/1  Running
gateway-ui-<hash>  1/1  Running
```

**Access URLs:**
- Gateway API: http://localhost:8090
- Gateway UI: http://localhost:8080

### Step 2: Provision Auth Schema

```bash
# Register credentials
task register-test-credentials

# Register and execute provisioning playbook
cd /Users/akuksin/projects/noetl/noetl
python3 << 'EOF'
import requests

with open("tests/fixtures/playbooks/api_integration/auth0/provision_auth_schema.yaml") as f:
    content = f.read()

response = requests.post(
    "http://localhost:8082/api/catalog/register",
    json={"content": content}
)
print(f"Register: {response.json()}")

response = requests.post(
    "http://localhost:8082/api/execute",
    json={
        "path": "api_integration/auth0/provision_auth_schema",
        "workload": {}
    }
)
print(f"Execute: {response.json()}")
EOF
```

**Verify schema created:**
```bash
kubectl exec -n postgres deployment/postgres -- \
  psql -U demo -d demo_noetl -c "\dt auth.*"
```

**Expected output:**
```
auth.users
auth.sessions
auth.roles
auth.permissions
auth.user_roles
auth.role_permissions
auth.audit_log
auth.playbook_permissions
```

### Step 3: Register Auth Playbooks

```bash
python3 << 'EOF'
import requests
import glob

playbooks = glob.glob("tests/fixtures/playbooks/api_integration/auth0/*.yaml")
for playbook_file in sorted(playbooks):
    with open(playbook_file, 'r') as f:
        content = f.read()
    
    response = requests.post(
        "http://localhost:8082/api/catalog/register",
        json={"content": content}
    )
    if response.status_code == 200:
        data = response.json()
        print(f"Registered: {data['path']} v{data['version']}")
EOF
```

**Expected output:**
```
Registered: api_integration/auth0/auth0_login v2
Registered: api_integration/auth0/auth0_validate_session v2
Registered: api_integration/auth0/check_playbook_access v2
Registered: api_integration/auth0/provision_auth_schema v5
```

### Step 4: Create Test User with Session Token

```bash
kubectl exec -n postgres deployment/postgres -- \
  psql -U demo -d demo_noetl << 'SQL'
-- Insert test user
INSERT INTO auth.users (auth0_id, email, display_name, is_active)
VALUES ('test|12345', 'test@example.com', 'Test User', true)
ON CONFLICT (auth0_id) DO UPDATE SET 
  email = EXCLUDED.email,
  display_name = EXCLUDED.display_name,
  is_active = true
RETURNING user_id;

-- Grant admin role (use user_id from above, typically 1)
INSERT INTO auth.user_roles (user_id, role_id)
SELECT 1, role_id FROM auth.roles WHERE role_name = 'admin'
ON CONFLICT DO NOTHING;

-- Create test session token
INSERT INTO auth.sessions (
  user_id, 
  session_token, 
  auth0_token,
  expires_at,
  is_active,
  ip_address
)
VALUES (
  1,
  'test-session-token-2026',
  'fake-auth0-token',
  NOW() + INTERVAL '24 hours',
  true,
  '127.0.0.1'
)
ON CONFLICT (session_token) DO UPDATE SET
  expires_at = EXCLUDED.expires_at,
  is_active = true
RETURNING session_id, session_token, expires_at;

-- Grant playbook permissions to admin role
INSERT INTO auth.playbook_permissions (role_id, allow_pattern, can_execute, can_view, can_modify)
SELECT role_id, '%', true, true, true
FROM auth.roles WHERE role_name = 'admin'
ON CONFLICT DO NOTHING;
SQL
```

**Expected output:**
```
user_id: 1
session_token: test-session-token-2026
expires_at: 2026-01-08 23:XX:XX
```

### Step 5: Test Authentication (Without Auth0)

Test session validation with direct token:

```bash
python3 << 'EOF'
import requests

response = requests.post(
    "http://localhost:8082/api/execute",
    json={
        "path": "api_integration/auth0/auth0_validate_session",
        "workload": {
            "session_token": "test-session-token-2026"
        }
    }
)
print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")
EOF
```

**Expected output:**
```json
{
  "execution_id": 123456,
  "status": "started",
  "commands_generated": 1
}
```

Wait 2-3 seconds, then check execution result:
```bash
kubectl exec -n postgres deployment/postgres -- \
  psql -U noetl -d noetl -c \
  "SELECT event_type, status, node_name FROM noetl.event 
   WHERE node_name LIKE '%validate%' 
   ORDER BY event_id DESC LIMIT 5;"
```

### Step 6: Test with Real Auth0 Integration

#### Testing Options

**Option A: UI Testing (Recommended for Manual Testing)**

Test the full OAuth flow through the browser UI:

1. **Open the login page:**
   ```
   http://localhost:8080/login.html
   ```

2. **Click "Sign In with Auth0" button**
   - Redirects to Auth0 Universal Login page
   - Enter your Auth0 credentials (kadyapam@gmail.com)
   - Auth0 redirects back with access token
   - UI calls `auth0_login` playbook automatically
   - Creates NoETL session and redirects to dashboard

3. **No passwords in environment variables needed!**
   - User authenticates directly with Auth0
   - Browser handles the OAuth flow
   - Session token stored in localStorage

**Option B: Automated Backend Testing**

For automated testing without browser interaction:

**⚠️ Note:** This option requires `AUTH0_USER_PASSWORD` environment variable because it uses Resource Owner Password Grant (machine-to-machine flow) instead of browser OAuth. This is for CI/CD and automated testing only.

#### Current Auth0 Configuration:
- **Domain:** `mestumre-development.us.auth0.com`
- **Client ID:** `Jqop7YoaiZalLHdBRo5ScNQ1RJhbhbDN`
- **Test User:** `kadyapam@gmail.com`
- **Auth0 User ID:** `auth0|695f4fd8ae18560f879320bf`

#### Auth0 API Audiences:

Auth0 provides different API audiences for different purposes:

1. **My Account API** (recommended for user authentication):
   - Audience: `https://mestumre-development.us.auth0.com/me/`
   - Purpose: User profile management, password changes, MFA enrollment
   - Used by: `get_auth0_token` playbook (default)

2. **Management API** (for administrative operations):
   - Audience: `https://mestumre-development.us.auth0.com/api/v2/`
   - Purpose: User management, role assignment, application configuration
   - Requires: Admin permissions and proper scopes

3. **No specific audience** (OpenID/OAuth only):
   - Used for: Basic authentication, userinfo endpoint access
   - Scopes: `openid profile email`

Our playbooks default to **My Account API** for user authentication flows.

#### Recommended: Automated Full Flow Test

Use the automated test script to test the complete Auth0 integration:

**1. Get Auth0 Client Secret:**
   - Go to [Auth0 Dashboard](https://manage.auth0.com/) → Applications → Your Application
   - Click **Settings** tab
   - Scroll down and copy **Client Secret**

**2. Enable Resource Owner Password Grant (if not already enabled):**
   - In Auth0 Dashboard → Applications → Your Application → Settings
   - Scroll to **Advanced Settings** → **Grant Types**
   - Check ✓ **Password**
   - Click **Save Changes**

**3. Store client secret - Choose one method:**

**Method A: Using Credential File (Recommended)**
```bash
# Copy the example file
cp tests/fixtures/credentials/auth0_client.json.example \
   tests/fixtures/credentials/auth0_client.json

# Edit the file and replace YOUR_AUTH0_CLIENT_SECRET_HERE with your actual secret
# Then register it
export AUTH0_USER_PASSWORD='password_for_kadyapam@gmail.com'
./tests/scripts/test_auth0_integration.sh --use-file
```

**Method B: Using Command Line Argument**
```bash
# Pass client secret directly as argument (one-time setup)
export AUTH0_USER_PASSWORD='password_for_kadyapam@gmail.com'
./tests/scripts/test_auth0_integration.sh 'your_client_secret_from_auth0'
```

**4. Subsequent runs (client secret already stored):**
```bash
# After initial setup, only user password is needed
export AUTH0_USER_PASSWORD='password_for_kadyapam@gmail.com'
./tests/scripts/test_auth0_integration.sh
```

**How credential storage works:**
- Client secret stored in `noetl.credential` table with key `auth0_client`
- Playbooks retrieve it using `{{ secret[workload.auth0_credential].password }}`
- Credential file format matches other NoETL credentials (see `tests/fixtures/credentials/`)
- No need to pass sensitive data via environment variables
- Follows same pattern as database credentials (e.g., `pg_k8s`)

**What the script does:**
1. Stores Auth0 client secret in NoETL credential table (if provided as argument)
2. Registers two playbooks:
   - `get_auth0_token` - Gets Auth0 access token via password grant
   - `test_auth0_full_flow` - Complete flow: get token → validate → create session
3. Executes the full flow test with your credentials
4. Verifies user creation in `auth.users` table
5. Displays the session token for UI testing

**Expected output:**
```
✓ Auth0 client credential registered
✓ Registered: api_integration/auth0/get_auth0_token v1
✓ Registered: api_integration/auth0/test_auth0_full_flow v1
✓ Token request started: execution_id=123456
✓ Full flow test started: execution_id=123457

user_id | auth0_id                       | email
--------|--------------------------------|-------------------
2       | auth0|695f4fd8ae18560f879320bf | kadyapam@gmail.com

session_token              | expires_at           | is_active
---------------------------|----------------------|-----------
a1b2c3d4e5f6...           | 2026-01-08 10:30:00 | t
```

#### Option 2: Manual Token Testing (Alternative)

If you want to test individual steps manually:

**Get Auth0 Token Manually:**

```bash
# Use get_auth0_token playbook (retrieves client_secret from credential table)
curl -X POST http://localhost:8082/api/execute \
  -H "Content-Type: application/json" \
  -d '{
    "path": "api_integration/auth0/get_auth0_token",
    "workload": {
      "username": "kadyapam@gmail.com",
      "password": "YOUR_PASSWORD"
    }
  }'
```

Or use cURL directly to Auth0:

```bash
curl --request POST \
  --url https://mestumre-development.us.auth0.com/oauth/token \
  --header 'content-type: application/json' \
  --data '{
    "grant_type": "password",
    "username": "kadyapam@gmail.com",
    "password": "YOUR_PASSWORD",
    "audience": "https://mestumre-development.us.auth0.com/me/",
    "client_id": "Jqop7YoaiZalLHdBRo5ScNQ1RJhbhbDN",
    "client_secret": "YOUR_CLIENT_SECRET",
    "scope": "openid profile email"
  }'
```

**Response:**
```json
{
  "access_token": "eyJhbGc...",
  "token_type": "Bearer",
  "expires_in": 86400
}
```

#### Option 3: Test Auth0 Login via UI

1. **Open browser:**
   ```
   http://localhost:8080/login.html
   ```

2. **Use the top form ("Sign in with Auth0"):**
   - Paste your Auth0 access token (from Option 1 or 2)
   - Enter domain: `mestumre-development.us.auth0.com`
   - Click **"Sign In with Auth0"**

3. **What happens:**
   - UI calls `auth0_login` playbook via NoETL API
   - Playbook validates token with Auth0 userinfo endpoint
   - Creates user record in `auth.users` (if doesn't exist)
   - Generates NoETL session token
   - Returns session token to UI
   - Redirects to dashboard

#### Option 4: Test Auth0 Login Playbook Directly

```bash
# Get Auth0 token first (from Option 1 or 2)
AUTH0_TOKEN="eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIs..."

# Execute auth0_login playbook
curl -X POST http://localhost:8082/api/execute \
  -H "Content-Type: application/json" \
  -d "{
    \"path\": \"api_integration/auth0/auth0_login\",
    \"workload\": {
      \"auth0_token\": \"$AUTH0_TOKEN\",
      \"client_ip\": \"127.0.0.1\"
    }
  }"
```

**Expected response:**
```json
{
  "execution_id": 123456789,
  "status": "started",
  "commands_generated": 4
}
```

**Wait 2-3 seconds, then check result:**
```bash
# Query execution events to get session token
kubectl exec -n postgres deployment/postgres -- \
  psql -U noetl -d noetl -c \
  "SELECT event_type, status, result_summary 
   FROM noetl.event 
   WHERE execution_id = 123456789 
   ORDER BY event_id DESC LIMIT 10;"
```

**Verify user was created:**
```bash
kubectl exec -n postgres deployment/postgres -- \
  psql -U demo -d demo_noetl -c \
  "SELECT user_id, auth0_id, email, display_name, is_active, created_at 
   FROM auth.users 
   WHERE email = 'kadyapam@gmail.com';"
```

**Expected output:**
```
user_id | auth0_id                       | email               | display_name | is_active | created_at
--------|--------------------------------|---------------------|--------------|-----------|------------------
2       | auth0|695f4fd8ae18560f879320bf | kadyapam@gmail.com  | Kadya Pam    | t         | 2026-01-07 ...
```

**Get the session token:**
```bash
kubectl exec -n postgres deployment/postgres -- \
  psql -U demo -d demo_noetl -c \
  "SELECT session_token, expires_at 
   FROM auth.sessions 
   WHERE user_id = (SELECT user_id FROM auth.users WHERE email = 'kadyapam@gmail.com')
   ORDER BY created_at DESC 
   LIMIT 1;"
```

**Test the session token:**
```bash
# Use the session token from above query
SESSION_TOKEN="<token_from_query>"

curl -X POST http://localhost:8082/api/execute \
  -H "Content-Type: application/json" \
  -d "{
    \"path\": \"api_integration/auth0/auth0_validate_session\",
    \"workload\": {
      \"session_token\": \"$SESSION_TOKEN\"
    }
  }"
```

### Step 8: Test Full OAuth Flow (Advanced)

To implement full Auth0 Universal Login (redirect to Auth0 login page):

1. **Current Implementation:**
   - UI expects you to paste Auth0 token manually
   - Token obtained from Auth0 Dashboard or API

2. **Full OAuth Flow (Future Enhancement):**
   - Click "Sign in with Auth0" button
   - Redirect to Auth0 Universal Login page
   - User logs in at Auth0
   - Auth0 redirects back to callback URL with authorization code
   - Frontend exchanges code for access token
   - Frontend calls `auth0_login` playbook
   - Stores session token and redirects to dashboard

3. **Implementation Notes:**
   - Requires Auth0 SDK (auth0-spa-js)
   - Need callback handler page
   - Token exchange handled by Auth0 library
   - Current manual token flow works for testing/development

### Step 9: Verify Everything Works

```bash
# Check gateway logs
task gateway-logs

# Check recent auth events
kubectl exec -n postgres deployment/postgres -- \
  psql -U demo -d demo_noetl -c \
  "SELECT event_type, event_status, user_id, created_at 
   FROM auth.audit_log 
   ORDER BY created_at DESC LIMIT 10;"

# Check active sessions
kubectl exec -n postgres deployment/postgres -- \
  psql -U demo -d demo_noetl -c \
  "SELECT session_id, user_id, session_token, expires_at, is_active 
   FROM auth.sessions 
   WHERE is_active = true 
   ORDER BY created_at DESC;"
```

## Quick Testing Without Auth0

For development/testing without Auth0:

```bash
# Use the test session token created in Step 4
SESSION_TOKEN="test-session-token-2026"

# Test session validation
curl -X POST http://localhost:8090/api/validate \
  -H "Content-Type: application/json" \
  -d "{\"session_token\": \"$SESSION_TOKEN\"}"

# Test playbook access check
curl -X POST http://localhost:8090/api/check-access \
  -H "Content-Type: application/json" \
  -d "{
    \"session_token\": \"$SESSION_TOKEN\",
    \"playbook_path\": \"data/etl/sample\",
    \"action\": \"execute\"
  }"
```

**What just happened?**
- ✅ Auth0 application configured
- ✅ Auth schema provisioned with 8 tables
- ✅ 4 authentication playbooks registered
- ✅ Test user created with admin role
- ✅ Test session token created
- ✅ Auth flow tested (with and without Auth0)
- ✅ Gateway integrated with authentication

**Next Steps:**
- Review [TESTING.md](TESTING.md) for comprehensive tests
- Configure production Auth0 callbacks
- Set up user role management
- See detailed setup instructions below for advanced configuration

## Overview

The Auth0 integration enables user authentication and authorization for the noetl-gateway, allowing clients to connect and execute playbooks based on their roles and permissions. All backend functionality is managed through playbooks.

## Architecture

```
Client → noetl-gateway → Auth0 (authentication) → noetl-server (playbook execution)
                    ↓
              auth schema (user tracking, roles, playbook permissions)
```

## Components

### 1. Database Schema (`auth`)

The `auth` schema in the `demo_noetl` database stores:
- **users**: User accounts, Auth0 IDs, profiles
- **roles**: Role definitions (admin, developer, analyst, viewer)
- **permissions**: Granular permission definitions
- **user_roles**: User-to-role mappings
- **playbook_permissions**: Playbook access control by role
- **sessions**: Active user sessions and tokens
- **audit_log**: Authentication and authorization events

### 2. Playbooks (V2 DSL)

All playbooks use NoETL V2 DSL format (`apiVersion: noetl.io/v2`).

#### `provision_auth_schema.yaml`
Creates the auth database schema and tables.

**Features:**
- Creates auth schema with 8 tables
- Seeds default roles (admin, developer, analyst, viewer)
- Seeds default permissions
- Uses postgres tool for schema creation
- Requires `pg_k8s` credential

**Input:**
- No workload required (uses defaults)

**Output:**
- Schema verification results

#### `auth0_login.yaml`
Handles user login flow with Auth0.

**Features:**
- Validates Auth0 token via HTTP call to Auth0 /userinfo
- Creates/updates user record in auth.users
- Creates session with random session token
- Returns session token for API access
- Requires `pg_k8s` credential

**Input (workload):**
- `auth0_token`: Auth0 access token (required)
- `client_ip`: Client IP address (optional, default: 0.0.0.0)
- `auth0_domain`: Auth0 domain (default: mestumre-development.us.auth0.com)

**Output:**
- `session_token`: NoETL session token
- `user_id`: Internal user ID
- `email`: User email
- `expires_at`: Session expiration timestamp

#### `auth0_validate_session.yaml`
Validates active user sessions.

**Features:**
- Looks up session by token
- Verifies session is active and not expired
- Updates last_activity_at timestamp
- Retrieves user roles
- Returns user and session details
- Requires `pg_k8s` credential

**Input (workload):**
- `session_token`: NoETL session token (required)

**Output:**
- `valid`: Boolean indicating session validity
- `user`: User details (user_id, email, display_name, roles)
- `message`: Status message

#### `check_playbook_access.yaml`
Validates if user can access a specific playbook.

**Features:**
- Validates session token
- Checks user roles and playbook permissions
- Supports exact path and pattern matching
- Returns access decision with details
- Requires `pg_k8s` credential

**Input (workload):**
- `session_token`: NoETL session token (required)
- `playbook_path`: Path to playbook (required)
- `action`: Action type - execute, view, modify (optional, default: execute)

**Output:**
- `allowed`: Boolean indicating if access is granted
- `playbook_path`: Requested playbook path
- `action`: Requested action
- `message`: Access decision message

## Credentials

### Admin Credential (`pg_k8s.json`)
Used for schema provisioning and administrative tasks.
```json
{
  "db_user": "demo",
  "db_password": "demo",
  "db_name": "demo_noetl"
}
```

### Auth User Credential (`pg_auth_user.json`)
Used by auth playbooks for runtime operations.
```json
{
  "db_user": "auth_user",
  "db_password": "<generated>",
  "db_name": "demo_noetl"
}
```

## Setup

### Step 1: Provision Database Schema
```bash
# Register admin credential
noetl credential register -f tests/fixtures/credentials/pg_k8s.json

# Run provisioning playbook
noetl playbook register -f tests/fixtures/playbooks/api_integration/auth0/provision_auth_schema.yaml
noetl playbook run tests/api_integration/auth0/provision_auth_schema
```

### Step 2: Register Auth User Credential
```bash
noetl credential register -f tests/fixtures/credentials/pg_auth_user.json
```

### Step 3: Configure Auth0
1. Create Auth0 application
2. Configure callback URLs for noetl-gateway
3. Set up API permissions
4. Store Auth0 credentials in keychain

### Step 4: Deploy Authentication Playbooks
```bash
# Register auth playbooks
noetl playbook register -f tests/fixtures/playbooks/api_integration/auth0/auth0_login.yaml
noetl playbook register -f tests/fixtures/playbooks/api_integration/auth0/auth0_validate_session.yaml
noetl playbook register -f tests/fixtures/playbooks/api_integration/auth0/check_playbook_access.yaml
```

## Usage Flow

### 1. User Login
```
POST /auth/login
{
  "auth0_token": "eyJ..."
}

→ Runs: auth0_login playbook
← Returns: { "session_token": "...", "user_id": "..." }
```

### 2. Session Validation
```
POST /auth/validate
{
  "session_token": "..."
}

→ Runs: auth0_validate_session playbook
← Returns: { "valid": true, "user": {...}, "permissions": [...] }
```

### 3. Playbook Execution Request
```
POST /playbook/execute
{
  "session_token": "...",
  "playbook_path": "data/transform",
  "payload": {...}
}

→ Runs: check_playbook_access playbook
→ If authorized: Executes requested playbook
← Returns: Execution result
```

## Security Considerations

1. **Password Security**: Auth user password should be generated and stored securely
2. **Session Tokens**: Use secure random tokens with expiration
3. **SQL Injection**: All playbooks use parameterized queries
4. **Audit Trail**: All authentication events are logged
5. **Least Privilege**: Auth user has minimal required permissions

## Database Schema Structure

### users
```sql
- user_id (PK)
- auth0_id (unique)
- email
- display_name
- created_at
- updated_at
- last_login_at
- is_active
```

### roles
```sql
- role_id (PK)
- role_name (unique)
- description
- created_at
```

### user_roles
```sql
- user_id (FK)
- role_id (FK)
- granted_at
- granted_by
```

### playbook_permissions
```sql
- permission_id (PK)
- role_id (FK)
- playbook_path
- can_execute
- can_view
- created_at
```

### sessions
```sql
- session_id (PK)
- user_id (FK)
- session_token (unique)
- auth0_token
- created_at
- expires_at
- last_activity_at
- is_active
```

### audit_log
```sql
- log_id (PK)
- user_id (FK)
- event_type
- event_details (jsonb)
- ip_address
- user_agent
- created_at
```

## Testing

```bash
# Run schema provisioning test
task test:auth0:provision

# Run authentication flow test
task test:auth0:login

# Run authorization test
task test:auth0:permissions
```

## Future Enhancements

- Multi-factor authentication support
- API key management
- Role-based data filtering
- Audit log retention policies
- Session refresh mechanism
- OAuth2 scope mapping
