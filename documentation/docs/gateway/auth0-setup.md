---
sidebar_position: 4
title: Auth0 Setup
description: Configuring Auth0 authentication for the NoETL Gateway
---

# Auth0 Setup Guide

Complete guide for configuring Auth0 authentication with the NoETL Gateway.

:::info Related Files
- UI Config: [`tests/fixtures/gateway_ui/config.js`](https://github.com/noetl/noetl/blob/master/tests/fixtures/gateway_ui/config.js)
- Auth Playbooks: [`tests/fixtures/playbooks/api_integration/auth0/`](https://github.com/noetl/noetl/tree/master/tests/fixtures/playbooks/api_integration/auth0)
:::

## Overview

The NoETL Gateway uses Auth0 for user authentication via the OAuth2/OIDC implicit flow, with NATS K/V providing fast session caching:

### Authentication Flow

1. User clicks "Login with Auth0" on the gateway UI
2. Browser redirects to Auth0 Universal Login
3. User authenticates (email/password, social, etc.)
4. Auth0 redirects back with an ID token
5. Gateway calls `auth0_login` playbook via NoETL
6. Playbook validates token, creates user/session in PostgreSQL
7. Playbook caches session in NATS K/V (`sessions` bucket)
8. User receives a session token for subsequent API calls

### Session Validation (Subsequent Requests)

```
Gateway Request → Check NATS K/V → Cache Hit? → Use cached session (sub-ms)
                                 → Cache Miss? → Call playbook → Refresh cache
```

1. Gateway checks NATS K/V for cached session (sub-millisecond lookup)
2. **Cache hit:** Use cached session data immediately
3. **Cache miss:** Call `auth0_validate_session` playbook
4. Playbook validates from PostgreSQL (source of truth) and refreshes cache

**Benefits:**
- Sub-millisecond session lookups from NATS K/V
- Reduced load on NoETL server and PostgreSQL
- PostgreSQL remains source of truth
- Automatic cache refresh on validation

## Auth0 Account Setup

### Create Auth0 Account

1. Go to [auth0.com](https://auth0.com)
2. Sign up for a free account
3. Create a new tenant (e.g., `mycompany-dev`)

### Create Application

1. Navigate to **Applications** > **Applications**
2. Click **+ Create Application**
3. Enter name: `NoETL Gateway`
4. Select **Single Page Application**
5. Click **Create**

### Configure Application Settings

In your application's **Settings** tab:

#### Basic Information
- **Name**: NoETL Gateway
- **Application Type**: Single Page Application

#### Application URIs

**Allowed Callback URLs** (comma-separated):
```
http://localhost:8090/login.html,
https://gateway.yourdomain.com/login.html
```

**Allowed Logout URLs**:
```
http://localhost:8090/login.html,
https://gateway.yourdomain.com/login.html
```

**Allowed Web Origins**:
```
http://localhost:8090,
https://gateway.yourdomain.com
```

#### ID Token Configuration

Scroll to **ID Token** section:
- **ID Token Expiration**: 36000 (10 hours)

#### Advanced Settings

Click **Show Advanced Settings**:

**Grant Types** tab:
- [x] Implicit
- [x] Authorization Code

**Endpoints** tab - note these values:
- OAuth Authorization URL
- OAuth Token URL
- OpenID Configuration

### Save Credentials

Note these values from your application settings:
- **Domain**: `your-tenant.us.auth0.com`
- **Client ID**: `xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`

> **Important**: Never commit the Client Secret. For SPAs using implicit flow, you don't need the Client Secret.

## Gateway UI Configuration

### config.js

Update `tests/fixtures/gateway_ui/config.js`:

```javascript
// Auth0 Configuration
const isLocalDev = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
const auth0Config = {
  domain: 'your-tenant.us.auth0.com',        // Your Auth0 domain
  clientId: 'YOUR_CLIENT_ID',                 // Your Client ID
  // Redirect back to login.html - use port 8090 for local dev
  redirectUri: isLocalDev
    ? 'http://localhost:8090/login.html'
    : window.location.origin + '/login.html'
};
```

### login.html

The login flow is handled in `tests/fixtures/gateway_ui/login.html`:

```javascript
// Auth0 Universal Login redirect
function loginWithAuth0() {
  const auth0Domain = auth0Config.domain;
  const clientId = auth0Config.clientId;
  const redirectUri = auth0Config.redirectUri;

  // Build Auth0 authorization URL
  const authUrl = `https://${auth0Domain}/authorize?` +
    `response_type=id_token token&` +
    `client_id=${clientId}&` +
    `redirect_uri=${encodeURIComponent(redirectUri)}&` +
    `scope=openid profile email&` +
    `nonce=${Math.random().toString(36).substring(7)}`;

  // Redirect to Auth0
  window.location.href = authUrl;
}
```

## NoETL Playbook Configuration

### Register the Auth0 Login Playbook

```bash
noetl register playbook -f tests/fixtures/playbooks/api_integration/auth0/auth0_login.yaml
```

### Playbook Overview

The `auth0_login.yaml` playbook:

1. **Validates Auth0 Token**: Fetches user info from Auth0
2. **Upserts User**: Creates or updates user in the auth.users table
3. **Creates Session**: Generates a session token with expiration
4. **Returns Result**: Returns session token and user info

### Required Database Schema

Ensure the auth schema exists:

```sql
CREATE SCHEMA IF NOT EXISTS auth;

CREATE TABLE IF NOT EXISTS auth.users (
  user_id SERIAL PRIMARY KEY,
  email VARCHAR(255) UNIQUE NOT NULL,
  auth0_sub VARCHAR(255) UNIQUE,
  display_name VARCHAR(255),
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS auth.sessions (
  session_id SERIAL PRIMARY KEY,
  user_id INTEGER REFERENCES auth.users(user_id),
  session_token VARCHAR(64) UNIQUE NOT NULL,
  created_at TIMESTAMP DEFAULT NOW(),
  expires_at TIMESTAMP NOT NULL,
  client_ip VARCHAR(45),
  user_agent TEXT
);
```

### Required Credentials

#### PostgreSQL Credential

Create a PostgreSQL credential for the auth schema:

```bash
# Create credential file
cat > tests/fixtures/credentials/pg_auth.json << 'EOF'
{
  "name": "pg_auth",
  "type": "postgres",
  "data": {
    "host": "postgres.postgres.svc.cluster.local",
    "port": 5432,
    "user": "your_user",
    "password": "your_password",
    "database": "your_database"
  }
}
EOF

# Register credential
noetl register credential -f tests/fixtures/credentials/pg_auth.json
```

#### NATS Credential (for Session Caching)

Create a NATS credential for K/V session storage:

```bash
# Create credential file
cat > tests/fixtures/credentials/nats_credential.json << 'EOF'
{
  "name": "nats_credential",
  "type": "nats",
  "description": "NATS JetStream credential for K/V Store session management",
  "tags": ["nats", "jetstream", "kv", "sessions", "auth0"],
  "data": {
    "nats_url": "nats://nats.nats.svc.cluster.local:4222",
    "nats_user": "noetl",
    "nats_password": "noetl"
  }
}
EOF

# Register credential
noetl register credential -f tests/fixtures/credentials/nats_credential.json
```

The auth0 playbooks use `nats_credential` to cache sessions in the NATS K/V `sessions` bucket for fast gateway lookups.

## Auth0 Customization

### Universal Login Branding

1. Go to **Branding** > **Universal Login**
2. Customize:
   - Logo
   - Colors
   - Background

### Social Connections

1. Go to **Authentication** > **Social**
2. Enable desired providers:
   - Google
   - GitHub
   - Microsoft
   - etc.

### Custom Database Connection

For enterprise users with existing user databases:

1. Go to **Authentication** > **Database**
2. Create custom database connection
3. Configure login/signup scripts

## Security Best Practices

### Token Handling

1. **Never log tokens**: Ensure tokens aren't written to logs
2. **Use HTTPS**: Always use HTTPS in production
3. **Token expiration**: Set reasonable token expiration times
4. **Secure storage**: Store session tokens in HttpOnly cookies when possible

### Auth0 Security Settings

1. **Brute Force Protection**: Enable in **Security** > **Attack Protection**
2. **Bot Detection**: Enable in **Security** > **Attack Protection**
3. **Breached Password Detection**: Enable in **Security** > **Attack Protection**

### CORS Configuration

Ensure CORS is properly configured in the gateway:

```yaml
# values.yaml
env:
  corsAllowedOrigins: "https://your-app.com"  # Only allow your domain
```

## Testing Authentication

### Local Testing

1. Start the gateway (port-forwarded or local):
```bash
kubectl port-forward -n gateway svc/gateway 8091:80
```

2. Start the UI server:
```bash
cd tests/fixtures/gateway_ui
python3 -m http.server 8090
```

3. Open http://localhost:8090/login.html

4. Click "Login with Auth0"

5. Authenticate with your Auth0 credentials

6. Verify redirect back to login.html with session established

### Debug Authentication

Check gateway logs:
```bash
kubectl logs -n gateway deployment/gateway -f | grep -i auth
```

Expected log sequence:
```
INFO Auth login request for domain: your-tenant.us.auth0.com
INFO Auth login execution_id: 123456789
INFO Auth login successful for user: user@example.com
```

### Test API Directly

```bash
# Get an ID token from Auth0 (use browser dev tools after login)
TOKEN="eyJhbGciOiJSUzI1NiIs..."

# Call gateway auth endpoint
curl -X POST http://localhost:8091/api/auth/login \
  -H "Content-Type: application/json" \
  -d "{
    \"auth0_token\": \"$TOKEN\",
    \"auth0_domain\": \"your-tenant.us.auth0.com\"
  }"
```

Expected response:
```json
{
  "status": "authenticated",
  "session_token": "abc123...",
  "user": {
    "user_id": 1,
    "email": "user@example.com",
    "display_name": "user@example.com"
  },
  "expires_at": "2026-01-28T20:00:00Z",
  "message": "Authentication successful"
}
```

## Troubleshooting

### "Callback URL mismatch"

**Cause**: Redirect URI doesn't match Auth0 settings

**Solution**:
1. Check `redirectUri` in config.js
2. Verify exact match in Auth0 Allowed Callback URLs
3. Ensure protocol (http/https) matches

### "Invalid state"

**Cause**: State parameter mismatch (usually from browser back button)

**Solution**: Clear browser cache and try again

### "No output from login playbook"

**Cause**: Gateway can't parse playbook response

**Solution**:
1. Check playbook is registered
2. Verify credential exists and has correct permissions
3. Check NoETL logs for playbook execution errors

### "User not found in Auth0"

**Cause**: Auth0 token expired or invalid

**Solution**:
1. Check token expiration
2. Verify token is ID token (not access token)
3. Try logging in again

### CORS Errors

**Cause**: Origin not in allowed list

**Solution**:
1. Add your origin to `corsAllowedOrigins`
2. Redeploy gateway
3. Check Cloudflare isn't caching preflight responses
