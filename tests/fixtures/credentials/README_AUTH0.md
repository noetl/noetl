# Auth0 Credential Setup

This directory contains credential files for NoETL integration tests.

## Auth0 Client Credential

The `auth0_client` credential is used by Auth0 authentication playbooks to obtain access tokens and validate users.

### Setup Instructions

1. **Copy the example file:**
   ```bash
   cp auth0_client.json.example auth0_client.json
   ```

2. **Get your Auth0 Client Secret:**
   - Go to [Auth0 Dashboard](https://manage.auth0.com/)
   - Navigate to: Applications → Your Application → Settings
   - Scroll down and copy the **Client Secret**

3. **Update the credential file:**
   ```bash
   # Edit auth0_client.json
   # Replace "YOUR_AUTH0_CLIENT_SECRET_HERE" with your actual client secret
   ```

4. **Register the credential:**
   ```bash
   # Option 1: Register all test credentials
   task register-test-credentials
   
   # Option 2: Register via test script
   ./tests/scripts/test_auth0_integration.sh 'your_client_secret'
   
   # Option 3: Manual registration via API
   curl -X POST http://localhost:8082/api/credentials \
     -H 'Content-Type: application/json' \
     -d @tests/fixtures/credentials/auth0_client.json
   ```

### Credential Structure

The credential file must follow this structure:

```json
{
  "name": "auth0_client",           // Key used in playbooks
  "type": "auth0",                  // Credential type
  "description": "...",             // Human-readable description
  "tags": ["auth0", ...],           // Tags for organization
  "data": {
    "domain": "...",                // Auth0 tenant domain
    "client_id": "...",             // Application Client ID
    "client_secret": "...",         // Application Client Secret (SENSITIVE)
    "audience": "...",              // API audience URL
    "grant_types": [...],           // Supported OAuth grant types
    "token_endpoint": "...",        // OAuth token endpoint
    "userinfo_endpoint": "..."      // User info endpoint
  }
}
```

### How Playbooks Use This Credential

Playbooks retrieve the client secret using the `secret[]` notation:

```yaml
workload:
  auth0_credential: "auth0_client"  # Reference to credential key

workflow:
  - step: get_token
    tool:
      kind: http
      url: "{{ secret[workload.auth0_credential].data.token_endpoint }}"
      body:
        client_id: "{{ secret[workload.auth0_credential].data.client_id }}"
        client_secret: "{{ secret[workload.auth0_credential].data.client_secret }}"
```

The NoETL server resolves `{{ secret[...] }}` at execution time by querying the `noetl.credential` table.

### Storage in Database

The credential is stored in the `noetl.credential` table:

```sql
-- View the credential (client_secret will be visible)
SELECT key, username, extra 
FROM noetl.credential 
WHERE key = 'auth0_client';

-- For security, the actual mapping is:
-- key = 'auth0_client'
-- username = client_id (for compatibility)
-- password = client_secret (sensitive)
-- extra = JSON with all other data fields
```

**Note:** The `client_secret` is stored in the `password` column for security and consistency with other credential types.

### Security Best Practices

1. **Never commit** `auth0_client.json` (with real secret) to version control
2. Use `.gitignore` to exclude non-example credential files
3. Rotate client secrets periodically in Auth0 Dashboard
4. Use environment-specific credentials (dev/staging/prod)
5. Limit Auth0 application permissions to minimum required scopes

### Testing Without Real Auth0

For development without Auth0 setup, use the test session token approach:

```sql
-- Create a test session directly in the database
INSERT INTO auth.sessions (user_id, session_token, expires_at, is_active)
VALUES (1, 'test-session-token-2026', NOW() + INTERVAL '24 hours', true);
```

Then test with the UI using this token directly.
