---
sidebar_position: 5
title: Auth Integration
description: Auth0 authentication flow and session management
---

# Gateway Auth0 Integration - Complete Setup

This document describes the complete Auth0 authentication integration between the NoETL Gateway (Rust) and NoETL server playbooks.

**Important**: The Gateway is a pure API gateway that does not connect to any database. All authentication logic and data access goes through NoETL server playbooks via REST API calls.

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                     Browser (UI Client)                           │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  login.html → Auth0 → Get Token → POST /api/auth/login   │  │
│  │  index.html → Check Session → Authenticated GraphQL       │  │
│  └────────────────────────────────────────────────────────────┘  │
└─────────────────────────┬────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│                  Gateway (Rust - Port 8090)                       │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  Session Cache (NATS K/V):                                 │  │
│  │    1. Check NATS K/V for cached session (fast path)       │  │
│  │    2. Cache miss → Call NoETL playbook (slow path)        │  │
│  │                                                            │  │
│  │  Public Routes:                                            │  │
│  │    POST /api/auth/login        → NoETL auth0_login        │  │
│  │    POST /api/auth/validate     → NoETL auth0_validate     │  │
│  │    POST /api/auth/check-access → NoETL check_access       │  │
│  │                                                            │  │
│  │  Protected Routes (middleware validates session):         │  │
│  │    POST /graphql → Authenticated GraphQL Mutations        │  │
│  │                                                            │  │
│  │  Static Files:                                             │  │
│  │    GET  /              → index.html                        │  │
│  │    GET  /static/*      → Static assets                     │  │
│  └────────────────────────────────────────────────────────────┘  │
└─────────────────────────┬────────────────────────────────────────┘
                          │
            ┌─────────────┴─────────────┐
            ▼                           ▼
┌───────────────────────┐   ┌──────────────────────────────────────┐
│  NATS K/V (sessions)  │   │  NoETL Server (Python - Port 8082)   │
│  ┌─────────────────┐  │   │  ┌────────────────────────────────┐  │
│  │ Fast session    │  │   │  │  Auth0 Playbooks:              │  │
│  │ cache lookups   │  │   │  │    auth0_login                 │  │
│  │ (sub-ms)        │  │   │  │    auth0_validate_session      │  │
│  └─────────────────┘  │   │  │    check_playbook_access       │  │
└───────────────────────┘   │  │                                │  │
                            │  │  Playbooks update NATS K/V     │  │
                            │  │  after Postgres operations     │  │
                            │  └────────────────────────────────┘  │
                            └─────────────────────┬────────────────┘
                                                  │
                                                  ▼
                            ┌──────────────────────────────────────┐
                            │         PostgreSQL Database          │
                            │  ┌────────────────────────────────┐  │
                            │  │  auth schema (source of truth):│  │
                            │  │    - users (Auth0 profiles)    │  │
                            │  │    - sessions (tokens, expiry) │  │
                            │  │    - roles, permissions        │  │
                            │  │    - audit_log                 │  │
                            │  └────────────────────────────────┘  │
                            └──────────────────────────────────────┘
```

## Session Caching with NATS K/V

The Gateway uses NATS JetStream K/V as a fast session cache to avoid calling NoETL playbooks for every authenticated request.

### Cache Flow

**Login Request:**
1. Gateway receives Auth0 token from UI
2. Gateway calls `auth0_login` playbook via NoETL
3. Playbook validates token, creates user/session in Postgres
4. Gateway receives callback with session details
5. **Gateway caches session in NATS K/V** (bucket: `sessions`, TTL: 5 min)

**Subsequent Requests (Middleware & Validate):**
1. **Gateway checks NATS K/V for session** (sub-millisecond lookup)
2. If found and valid → use cached session data (fast path, no playbook call)
3. If not found (cache miss) → call `auth0_validate_session` playbook
4. Playbook validates from Postgres (source of truth)
5. Gateway receives callback and **caches result in NATS K/V**

**Session Invalidation:**
- Invalid sessions are removed from cache
- Cache entries auto-expire via NATS K/V TTL (default: 5 minutes)
- Postgres remains source of truth

### NATS K/V Session Data

```json
{
  "session_token": "abc123...",
  "user_id": 42,
  "email": "user@example.com",
  "display_name": "User Name",
  "expires_at": "2026-01-15T10:00:00Z",
  "is_active": true
}
```

### Configuration

**Environment Variables:**
```bash
# NATS connection (with credentials for JetStream K/V access)
export NATS_URL=nats://noetl:noetl@nats.nats.svc.cluster.local:4222

# Session cache settings
export NATS_SESSION_BUCKET=sessions        # K/V bucket name (default: sessions)
export NATS_SESSION_CACHE_TTL_SECS=300     # Cache TTL in seconds (default: 300 = 5 min)

# For Kind cluster (NodePort)
export NATS_URL=nats://noetl:noetl@localhost:30422
```

**NATS Server Configuration (accounts-based):**
```conf
accounts {
  NOETL {
    jetstream: enabled
    users: [
      { user: noetl, password: noetl }
    ]
  }
}
```

### Graceful Degradation

If NATS K/V is unavailable (connection fails, permissions issue), the gateway:
- Logs a warning: `Session cache disabled (NATS K/V unavailable)`
- Continues to work using playbooks for all validations
- No downtime or errors for users

### Benefits

- **Performance**: Sub-millisecond session lookups from NATS K/V
- **Scalability**: Reduced load on NoETL server and PostgreSQL
- **Reliability**: Postgres remains source of truth, graceful degradation
- **Simplicity**: Gateway handles caching automatically after login/validation

## Components

### 1. Gateway Rust Code

**Files Created:**
- `crates/gateway/src/auth/mod.rs` - Auth endpoints (login, validate, check_access) - all delegate to NoETL playbooks
- `crates/gateway/src/auth/middleware.rs` - Session validation middleware - calls NoETL validation playbook
- `crates/gateway/src/auth/types.rs` - User context types
- `crates/gateway/src/main.rs` - Updated with auth routes and middleware (no database connection)

**Key Features:**
- Pure API gateway - no direct database access
- REST endpoints call NoETL playbooks via `NoetlClient` for all auth operations
- Session middleware validates tokens by calling NoETL validation playbook
- Extracts session token from `Authorization: Bearer <token>`, `X-Session-Token` header, or `session_token` cookie
- Injects `UserContext` into request extensions for downstream use
- All authentication state managed by NoETL server and PostgreSQL backend

### 2. GMoved to:** `tests/fixtures/gateway_ui/`

- `login.html` - Login page with Auth0 and direct token options
- `auth.js` - Auth utilities (checkAuth, validateSession, authenticatedGraphQL)
- `index.html` - Main page with user menu and session check
- `app.js` - Flight search demo with authenticated GraphQL requests
- `styles.css` - Shared UI styles

**Note**: UI is served separately from gateway. Use any static file server:
```bash
cd tests/fixtures/gateway_ui
python3 -m http.server 8080
```

**Key Features:**
- Login page supports Auth0 token login or direct session token (testing)
- Session validation on page load, redirects to login if invalid
- All GraphQL requests include `Authorization: Bearer <token>` header
- Logout button clears session and redirects to login
- Permission check before executing playbooks

### 3. NoETL Auth0 Playbooks

**Already Created** (in `tests/fixtures/playbooks/api_integration/auth0/`):
- `provision_auth_schema.yaml` - Creates database schema
- `auth0_login.yaml` - Authenticates with Auth0 and creates session
- `auth0_validate_session.yaml` - Validates session token
- `check_playbook_access.yaml` - Checks user permission for playbook

## Setup Instructions

### Prerequisites

1. **PostgreSQL running** (localhost:54321 or K8s)
2. **NoETL server running** (port 8082/8083)
3. **Auth0 tenant configured** (or use test tokens)

### Step 1: Provision Auth Schema

The auth schema is **automatically provisioned** during bootstrap when deploying from scratch:

```bash
# Full bootstrap (includes auth schema provisioning)
noetl run boot
```

To provision manually or check status:

```bash
# Provision auth schema (if not using bootstrap)
noetl run automation/setup/provision_auth.yaml

# Check auth schema status
noetl run automation/setup/provision_auth.yaml --set action=status

# Reset auth schema (WARNING: deletes all user data)
noetl run automation/setup/provision_auth.yaml --set action=reset
```

**What this creates:**

| Table | Description |
|-------|-------------|
| `auth.users` | User accounts from Auth0 (email, display_name, profile) |
| `auth.roles` | Role definitions (admin, developer, analyst, viewer) |
| `auth.permissions` | Granular permissions (playbook:execute, catalog:view, etc.) |
| `auth.user_roles` | User-to-role mapping with expiration support |
| `auth.role_permissions` | Role-to-permission mapping |
| `auth.playbook_permissions` | Playbook-level access control with glob patterns |
| `auth.sessions` | Active user sessions with Auth0 tokens |
| `auth.audit_log` | Authentication and authorization event trail |

**Default Roles:**

| Role | Description | Permissions |
|------|-------------|-------------|
| `admin` | Full system access | All permissions, all playbooks |
| `developer` | Create and manage playbooks | Execute, view, create, modify playbooks (except system/*) |
| `analyst` | Execute and view results | Execute and view data/* playbooks |
| `viewer` | Read-only access | View playbooks and execution history |

### Step 1b: Grant Admin Role to First User

After the first user logs in via Auth0, grant them admin access:

```bash
# Using the provision_auth playbook (recommended)
noetl run automation/setup/provision_auth.yaml \
  --set action=grant_admin \
  --set email=your-email@example.com

# Or using kubectl directly
kubectl exec -n postgres deploy/postgres -- psql -U demo -d demo_noetl -c \
  "INSERT INTO auth.user_roles (user_id, role_id)
   SELECT u.user_id, r.role_id
   FROM auth.users u, auth.roles r
   WHERE u.email = 'your-email@example.com' AND r.role_name = 'admin'
   ON CONFLICT DO NOTHING;"
```

**Note**: The user must have logged in via Auth0 first to create their account in `auth.users`.

### User Management from Dashboard

Once logged in as admin, you can manage users from the dashboard:

1. Navigate to http://localhost:8080/dashboard.html
2. Click **Users** in the sidebar
3. View all users and their roles
4. Click **Edit Roles** to assign/remove roles

The dashboard uses the `user_management` playbook which supports:
- `list_users` - Get all users with roles
- `list_roles` - Get available roles
- `update_user_roles` - Modify user role assignments
- `get_user` - Get single user details

### Step 2: Update auth_user Credential

```bash
# Change password in database
psql -h localhost -p 54321 -U demo -d demo_noetl -c \
  "ALTER ROLE auth_user WITH PASSWORD 'your_secure_password';"

# Update credential file
vim tests/fixtures/credentials/pg_auth_user.json
# Set password to match above

# Register credential
noetl register credential --file tests/fixtures/credentials/pg_auth_user.json
```

### Step 3: Register Auth Playbooks

```bash
noetl register playbook --file tests/fixtures/playbooks/api_integration/auth0/auth0_login.yaml
noetl register playbook --file tests/fixtures/playbooks/api_integration/auth0/auth0_validate_session.yaml
noetl register playbook --file tests/fixtures/playbooks/api_integration/auth0/check_playbook_access.yaml
```

### Step 4: Build and Run Gateway
 (no database credentials needed!)
export ROUTER_PORT=8090
export NOETL_BASE_URL=http://localhost:8082

# Run gateway
cargo run --release
```

**Gateway will start on:** `http://localhost:8090`

**Note**: Gateway does NOT require database connection. All data access goes through NoETL server API.
export POSTGRES_DB=demo_noetl

# Run gateway
cargo run --release
```

**Gateway will start on:** `http://localhost:8090`

### Step 5: Create Test User (Optional)

```bash
psql -h localhost -p 54321 -U demo -d demo_noetl <<EOF
-- Create test user
INSERT INTO auth.users (auth0_id, email, display_name, is_active)
VALUES ('auth0|test123', 'test@example.com', 'Test User', true)
RETURNING user_id;

-- Grant admin role (use user_id from above)
INSERT INTO auth.user_roles (user_id, role_id)
SELECT 1, role_id FROM auth.roles WHERE role_name = 'admin';

-- Create test session (expires in 8 hours)
INSERT INTO auth.sessions (user_id, session_token, expires_at)
VALUES (
  1,
  'test-session-token-12345',
  NOW() + INTERVAL '8 hours'
)
RETURNING session_id, session_token;
EOF
```

**Save the `session_token` for testing!**

## Testing the Integration

### Test 1: Direct Login with Session Token

1. Open browser: `http://localhost:8090/static/login.html`
2. Scroll to "Direct Login" section
3. Enter session token: `test-session-token-12345`
4. Click "Sign In with Token"
5. Should redirect to `http://localhost:8090/` with authenticated session

### Test 2: Auth0 Login Flow

1. Get Auth0 access token from Auth0 dashboard or authentication
2. Open browser: `http://localhost:8090/static/login.html`
3. Enter Auth0 token and domain (e.g., `your-tenant.auth0.com`)
4. Click "Sign In with Auth0"
5. Gateway calls NoETL `auth0_login` playbook
6. If successful, redirects to main app with session

### Test 3: Protected GraphQL Request

1. After logging in, open browser: `http://localhost:8090/`
2. Should see user name and logout button in header
3. Type flight search query: "I want a flight from SFO to JFK tomorrow"
4. Gateway validates session via middleware
5. Checks playbook access permission
6. Executes GraphQL mutation with authenticated request
7. Returns flight search results

### Test 4: Session Expiration

1. Wait for session to expire (8 hours by default)
2. Refresh page
3. Should automatically redirect to login page
4. Session validation fails, localStorage cleared

### Test 5: Permission Check

```bash
# Remove user's execute permission for amadeus playbook
psql -h localhost -p 54321 -U demo -d demo_noetl <<EOF
DELETE FROM auth.playbook_permissions
WHERE role_id IN (
  SELECT role_id FROM auth.user_roles WHERE user_id = 1
)
AND playbook_path_pattern = 'api_integration/amadeus%';
EOF
```

Now try to execute playbook - should get "Permission denied" error.

## API Reference

### POST /api/auth/login

**Request:**
```json
{
  "auth0_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "auth0_domain": "your-tenant.auth0.com",
  "auth0_refresh_token": "optional-refresh-token",
  "session_duration_hours": 8,
  "client_ip": "192.168.1.100",
  "client_user_agent": "Mozilla/5.0..."
}
```

**Response (Success):**
```json
{
  "status": "authenticated",
  "session_token": "abc123def456...",
  "user": {
    "user_id": 1,
    "email": "user@example.com",
    "display_name": "John Doe"
  },
  "expires_at": "2026-01-08T08:00:00Z",
  "message": "Authentication successful"
}
```

**Response (Error):**
```json
{
  "error": "Invalid credentials"
}
```

### POST /api/auth/validate

**Request:**
```json
{
  "session_token": "abc123def456..."
}
```

**Response:**
```json
{
  "valid": true,
  "user": {
    "user_id": 1,
    "email": "user@example.com",
    "display_name": "John Doe"
  },
  "expires_at": "2026-01-08T08:00:00Z",
  "message": "Session is valid"
}
```

### POST /api/auth/check-access

**Request:**
```json
{
  "session_token": "abc123def456...",
  "playbook_path": "api_integration/amadeus_ai_api",
  "permission_type": "execute"
}
```

**Response:**
```json
{
  "allowed": true,
  "user": {
    "user_id": 1,
    "email": "user@example.com",
    "display_name": "John Doe"
  },
  "playbook_path": "api_integration/amadeus_ai_api",
  "permission_type": "execute",
  "message": "Access granted"
}
```

### POST /graphql (Protected)

**Headers:**
```
Authorization: Bearer abc123def456...
Content-Type: application/json
```

**Request:**
```json
{
  "query": "mutation ExecutePlaybook($name: String!, $vars: JSON) { executePlaybook(name: $name, variables: $vars) { id name status textOutput } }",
  "variables": {
    "name": "api_integration/amadeus_ai_api",
    "vars": {
      "query": "Flight from SFO to JFK tomorrow"
    }
  }
}
```

**Response:**
```json
{
  "data": {
    "executePlaybook": {
      "id": "123456",
      "name": "amadeus_ai_api",
      "status": "completed",
      "textOutput": "Found 5 flights from SFO to JFK..."
    }
  }
}
```

## Security Considerations

1. **HTTPS Required**: In production, use HTTPS for all endpoints
2. **Secure Cookies**: Set `HttpOnly`, `Secure`, `SameSite` cookie attributes
3. **CORS**: Configure allowed origins (don't use `Any` in production)
4. **Token Storage**: Consider using cookies instead of localStorage
5. **Session Expiration**: Configure appropriate session duration
6. **Rate Limiting**: Add rate limiting to auth endpoints
7. **Audit Logging**: All auth events logged to `auth.audit_log`
8. **Password Security**: Use strong passwords for database roles

## Troubleshooting

### Issue: "No session token provided"
- Check browser localStorage for `session_token`
- Verify `Authorization` header is sent with GraphQL requests
- Check browser console for auth.js errors

### Issue: "Session validation failed"
- Verify NoETL server is running and accessible
- Check auth playbooks are registered
- Verify `pg_auth_user` credential is configured correctly
- Check session hasn't expired in database

### Issue: "Permission denied"
- Verify user has correct role assignment in `auth.user_roles`
- Check playbook path pattern matches in `auth.playbook_permissions`
- Review permission type (execute, view, edit, delete)

### Issue: "NoETL execute playbook: send"
- Verify `NOETL_BASE_URL` environment variable is correct
- Check NoETL server is running and accessible from Gateway
- Review Gateway logs for connection errors

## Next Steps

1. ~~**Implement NATS K/V Cache in Gateway**~~: ✅ Implemented - Gateway checks NATS K/V before calling playbooks
2. ~~**Session TTL**~~: ✅ Implemented - NATS K/V bucket configured with automatic TTL (default: 5 min)
3. ~~**Cache Invalidation**~~: ✅ Implemented - Invalid sessions removed from cache automatically
4. **Integrate Auth0 SDK**: Use Auth0 JavaScript SDK for proper OAuth flow
5. **Add Refresh Tokens**: Implement token refresh before expiration
6. **Role Management UI**: Build admin interface for role/permission management
7. **Multi-Tenant Support**: Extend schema for organization-based access
8. **SSO Integration**: Add SAML/OAuth provider support
9. **Audit Dashboard**: Visualize authentication events and access patterns
10. **Rate Limiting**: Add protection against brute force attacks

## Files Summary

**Gateway Rust:**
- `src/auth/mod.rs` - Auth endpoints with cache-first validation
- `src/auth/middleware.rs` - Session validation middleware with cache support
- `src/auth/types.rs` - User context types
- `src/session_cache.rs` - NATS JetStream K/V session cache module
- `src/config/gateway_config.rs` - Configuration with session cache settings
- `src/main.rs` - Gateway startup with session cache initialization

**Gateway UI:**
- `static/login.html` (446 lines)
- `static/auth.js` (186 lines)
- `static/index.html` (updated)
- `static/app.js` (updated)
- `static/styles.css` (updated)

**Total**: ~1200 lines of new code + 4 playbooks already created

## Support

For issues or questions:
- Review NoETL logs: `kubectl logs -n noetl deployment/noetl-server`
- Review Gateway logs: Check terminal output
- Check database: `psql -h localhost -p 54321 -U demo -d demo_noetl`
- Consult playbook documentation: `tests/fixtures/playbooks/api_integration/auth0/README.md`
