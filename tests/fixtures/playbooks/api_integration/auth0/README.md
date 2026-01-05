# Auth0 Integration Playbooks

This directory contains playbooks for Auth0 authentication integration with noetl-gateway.

## Quick Start

Get up and running with Auth0 integration in 5 minutes:

```bash
# 1. Register admin credential for provisioning
noetl register credential --file tests/fixtures/credentials/pg_k8s.json

# 2. Provision auth schema (creates tables, roles, permissions)
noetl register playbook --file tests/fixtures/playbooks/api_integration/auth0/provision_auth_schema.yaml
noetl exec api_integration/auth0/provision_auth_schema

# 3. Change auth_user password (IMPORTANT: do this before next step!)
psql -h localhost -p 54321 -U demo -d demo_noetl -c \
  "ALTER ROLE auth_user WITH PASSWORD 'your_secure_password_here';"

# 4. Update and register auth_user credential
# Edit tests/fixtures/credentials/pg_auth_user.json with new password
noetl register credential --file tests/fixtures/credentials/pg_auth_user.json

# 5. Register authentication playbooks
noetl register playbook --file tests/fixtures/playbooks/api_integration/auth0/auth0_login.yaml
noetl register playbook --file tests/fixtures/playbooks/api_integration/auth0/auth0_validate_session.yaml
noetl register playbook --file tests/fixtures/playbooks/api_integration/auth0/check_playbook_access.yaml

# 6. Create a test user (optional - for testing without Auth0)
psql -h localhost -p 54321 -U demo -d demo_noetl <<EOF
INSERT INTO auth.users (auth0_id, email, display_name)
VALUES ('auth0|test123', 'test@example.com', 'Test User')
RETURNING user_id;
-- Save the user_id and use it below

INSERT INTO auth.user_roles (user_id, role_id)
SELECT 1, role_id FROM auth.roles WHERE role_name = 'admin';
EOF

# 7. Test the setup (see TESTING.md for comprehensive tests)
noetl catalog list --filter "path like 'api_integration/auth0%'"
```

**What just happened?**
- ✅ Created `auth` schema with 8 tables (users, roles, permissions, sessions, audit_log, etc.)
- ✅ Created `auth_user` database role with appropriate permissions
- ✅ Seeded 4 system roles: admin, developer, analyst, viewer
- ✅ Seeded 12+ permissions with role mappings
- ✅ Registered 4 authentication playbooks in catalog
- ✅ Ready to test authentication flows (see [TESTING.md](TESTING.md))

**Next Steps:**
- Review [TESTING.md](TESTING.md) for comprehensive testing guide
- Configure Auth0 application and callbacks
- Integrate with noetl-gateway for production use
- See detailed setup instructions below for production deployment

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

### 2. Playbooks

#### `provision_auth_schema.yaml`
Creates the auth database schema and user using a Kubernetes job that executes SQL scripts.

**Features:**
- Creates dedicated `auth_user` database role
- Sets up schema structure with proper permissions
- Runs as K8s job for isolation and auditability
- Uses admin credentials (`demo` user) for provisioning

#### `auth0_login.yaml` (TODO)
Handles user login flow:
- Validates Auth0 token
- Creates/updates user record
- Establishes session
- Returns session token

#### `auth0_validate_session.yaml` (TODO)
Validates active user sessions:
- Checks session validity
- Verifies user permissions
- Returns authorized playbook list

#### `check_playbook_access.yaml` (TODO)
Validates if user can execute a specific playbook:
- Checks user roles
- Validates playbook permissions
- Returns access decision with reason

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
