# Auth0 Integration Testing Guide

Complete testing guide for Auth0 authentication and authorization integration with NoETL.

## Prerequisites

- NoETL cluster running (kind or production)
- PostgreSQL database accessible
- Admin credentials registered (`pg_k8s`)
- Test playbooks registered in catalog

## Test Suite Overview

| Test # | Name | Category | Description |
|--------|------|----------|-------------|
| 1 | Schema Provisioning | Setup | Verify auth schema and tables creation |
| 2 | Database Structure | Setup | Validate schema structure and constraints |
| 3 | Login Flow | Authentication | Test Auth0 token validation and session creation |
| 4 | Session Validation | Authentication | Verify session token validation |
| 5 | Permission Check | Authorization | Test role-based playbook access control |
| 6 | Audit Logging | Security | Verify event logging |
| 7 | RBAC Testing | Authorization | Test different user roles |
| 8 | Session Expiration | Security | Test expired session handling |
| 9 | Cleanup Functions | Maintenance | Test session cleanup procedures |
| 10 | Pattern Permissions | Authorization | Test glob pattern matching |

## Setup Phase

### 1. Provision Auth Schema

**Objective**: Create auth schema, tables, roles, and seed default data.

**Steps**:
```bash
# 1. Register admin credential
noetlctl register-credential --file tests/fixtures/credentials/pg_k8s.json

# 2. Upload SQL script to GCS (if using remote script)
gsutil cp tests/fixtures/playbooks/api_integration/auth0/sql/provision_auth_schema.sql \
  gs://noetl-scripts/auth0/

# 3. Register provisioning playbook
noetlctl register-playbook \
  --file tests/fixtures/playbooks/api_integration/auth0/provision_auth_schema.yaml

# 4. Execute provisioning
noetlctl exec api_integration/auth0/provision_auth_schema
```

**Expected Result**:
```json
{
  "status": "success",
  "message": "Auth schema provisioned successfully",
  "details": {
    "schema_created": true,
    "tables_created": 8,
    "roles_seeded": 4,
    "permissions_seeded": 12,
    "auth_user_created": true
  },
  "next_steps": [
    "1. Change auth_user password: ALTER ROLE auth_user WITH PASSWORD 'new_secure_password';",
    "2. Register pg_auth_user credential with new password",
    "3. Deploy authentication playbooks"
  ]
}
```

**Verification**:
```sql
-- Connect to database
psql -h localhost -p 54321 -U demo -d demo_noetl

-- Check schema exists
SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'auth';

-- Count tables
SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'auth';
-- Expected: 8

-- List tables
SELECT table_name FROM information_schema.tables WHERE table_schema = 'auth' ORDER BY table_name;
-- Expected: audit_log, permissions, playbook_permissions, role_permissions, roles, sessions, user_roles, users

-- Check auth_user role
SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname = 'auth_user';
-- Expected: auth_user | t

-- Check default roles
SELECT role_name, is_system_role FROM auth.roles ORDER BY role_name;
-- Expected: admin (true), analyst (true), developer (true), viewer (true)

-- Check default permissions
SELECT COUNT(*) FROM auth.permissions;
-- Expected: 12+

-- Check role-permission mappings
SELECT r.role_name, COUNT(rp.permission_id) as perm_count
FROM auth.roles r
JOIN auth.role_permissions rp ON r.role_id = rp.role_id
GROUP BY r.role_name
ORDER BY r.role_name;
-- Expected: admin (12+), analyst (3), developer (6), viewer (2)
```

### 2. Configure auth_user Credential

**Steps**:
```bash
# 1. Change auth_user password
psql -h localhost -p 54321 -U demo -d demo_noetl -c \
  "ALTER ROLE auth_user WITH PASSWORD 'secure_password_123';"

# 2. Update credential file
cat > tests/fixtures/credentials/pg_auth_user.json <<EOF
{
  "name": "pg_auth_user",
  "type": "postgres",
  "description": "Auth schema user credential",
  "tags": ["postgres", "auth"],
  "data": {
    "db_host": "postgres.default.svc.cluster.local",
    "db_port": "5432",
    "db_user": "auth_user",
    "db_password": "secure_password_123",
    "db_name": "demo_noetl",
    "db_schema": "auth"
  }
}
EOF

# 3. Register credential
noetlctl register-credential --file tests/fixtures/credentials/pg_auth_user.json
```

### 3. Register Authentication Playbooks

**Steps**:
```bash
# Register all auth playbooks
noetlctl register-playbook \
  --file tests/fixtures/playbooks/api_integration/auth0/auth0_login.yaml

noetlctl register-playbook \
  --file tests/fixtures/playbooks/api_integration/auth0/auth0_validate_session.yaml

noetlctl register-playbook \
  --file tests/fixtures/playbooks/api_integration/auth0/check_playbook_access.yaml
```

**Verification**:
```bash
# List registered playbooks
noetlctl catalog list --filter "path like 'api_integration/auth0%'"

# Expected output:
# - api_integration/auth0/provision_auth_schema
# - api_integration/auth0/auth0_login
# - api_integration/auth0/auth0_validate_session
# - api_integration/auth0/check_playbook_access
```

### 4. Create Test Users

Create test users for different roles:

```sql
-- Admin user
INSERT INTO auth.users (auth0_id, email, display_name)
VALUES ('auth0|admin_test', 'admin@test.noetl.io', 'Admin Test User')
RETURNING user_id;
-- Save user_id (e.g., 1)

INSERT INTO auth.user_roles (user_id, role_id)
SELECT 1, role_id FROM auth.roles WHERE role_name = 'admin';

-- Developer user
INSERT INTO auth.users (auth0_id, email, display_name)
VALUES ('auth0|dev_test', 'dev@test.noetl.io', 'Developer Test User')
RETURNING user_id;
-- Save user_id (e.g., 2)

INSERT INTO auth.user_roles (user_id, role_id)
SELECT 2, role_id FROM auth.roles WHERE role_name = 'developer';

-- Analyst user
INSERT INTO auth.users (auth0_id, email, display_name)
VALUES ('auth0|analyst_test', 'analyst@test.noetl.io', 'Analyst Test User')
RETURNING user_id;
-- Save user_id (e.g., 3)

INSERT INTO auth.user_roles (user_id, role_id)
SELECT 3, role_id FROM auth.roles WHERE role_name = 'analyst';

-- Viewer user
INSERT INTO auth.users (auth0_id, email, display_name)
VALUES ('auth0|viewer_test', 'viewer@test.noetl.io', 'Viewer Test User')
RETURNING user_id;
-- Save user_id (e.g., 4)

INSERT INTO auth.user_roles (user_id, role_id)
SELECT 4, role_id FROM auth.roles WHERE role_name = 'viewer';

-- Verify users created
SELECT u.user_id, u.email, u.display_name, r.role_name
FROM auth.users u
JOIN auth.user_roles ur ON u.user_id = ur.user_id
JOIN auth.roles r ON ur.role_id = r.role_id
ORDER BY u.user_id;
```

## Authentication Tests

### Test 3: Login Flow (Mock)

**Objective**: Test session creation without real Auth0 validation.

**Note**: The login playbook requires real Auth0 token validation. For testing without Auth0, create sessions manually.

**Steps**:
```sql
-- Create test session for admin user
INSERT INTO auth.sessions (
  user_id,
  session_token,
  auth0_token,
  expires_at,
  ip_address,
  user_agent
)
VALUES (
  1,  -- admin user_id
  encode(gen_random_bytes(32), 'hex'),
  'mock_auth0_token_for_testing',
  NOW() + INTERVAL '24 hours',
  '127.0.0.1'::inet,
  'test-client/1.0'
)
RETURNING session_token;
-- Save token: e.g., 'abc123...'
```

**Store tokens for subsequent tests**:
```bash
# Save tokens as environment variables
export ADMIN_TOKEN="<token_from_above>"

# Create sessions for other test users
psql -h localhost -p 54321 -U demo -d demo_noetl <<EOF
-- Developer session
INSERT INTO auth.sessions (user_id, session_token, auth0_token, expires_at)
VALUES (2, encode(gen_random_bytes(32), 'hex'), 'mock_dev_token', NOW() + INTERVAL '24 hours')
RETURNING session_token;

-- Analyst session
INSERT INTO auth.sessions (user_id, session_token, auth0_token, expires_at)
VALUES (3, encode(gen_random_bytes(32), 'hex'), 'mock_analyst_token', NOW() + INTERVAL '24 hours')
RETURNING session_token;

-- Viewer session
INSERT INTO auth.sessions (user_id, session_token, auth0_token, expires_at)
VALUES (4, encode(gen_random_bytes(32), 'hex'), 'mock_viewer_token', NOW() + INTERVAL '24 hours')
RETURNING session_token;
EOF

export DEV_TOKEN="<dev_token>"
export ANALYST_TOKEN="<analyst_token>"
export VIEWER_TOKEN="<viewer_token>"
```

### Test 4: Session Validation

**Objective**: Verify session token validation returns user details and roles.

**Steps**:
```bash
# Test admin session validation
noetlctl exec api_integration/auth0/auth0_validate_session \
  --payload "{
    \"session_token\": \"$ADMIN_TOKEN\",
    \"validate_auth0\": false,
    \"client_ip\": \"127.0.0.1\"
  }"
```

**Expected Result**:
```json
{
  "valid": true,
  "user": {
    "user_id": 1,
    "email": "admin@test.noetl.io",
    "display_name": "Admin Test User",
    "roles": ["admin"],
    "permissions": [
      "playbook:execute",
      "playbook:view",
      "playbook:create",
      "playbook:modify",
      "playbook:delete",
      "catalog:view",
      "catalog:manage",
      "credential:view",
      "credential:manage",
      "execution:view",
      "execution:cancel",
      "system:admin"
    ]
  },
  "session": {
    "session_id": 1,
    "expires_at": "2024-12-22T10:30:00Z",
    "last_activity_at": "2024-12-21T10:30:00Z"
  },
  "message": "Session is valid"
}
```

**Verification**:
```sql
-- Check last_activity_at was updated
SELECT session_id, user_id, last_activity_at
FROM auth.sessions
WHERE session_token = '<ADMIN_TOKEN>';

-- Check audit log entry
SELECT event_type, event_status, user_id, created_at
FROM auth.audit_log
WHERE event_type = 'session_validation'
ORDER BY created_at DESC
LIMIT 1;
-- Expected: session_validation | success | 1 | <timestamp>
```

**Test invalid session**:
```bash
# Test with non-existent token
noetlctl exec api_integration/auth0/auth0_validate_session \
  --payload '{
    "session_token": "invalid_token_123",
    "validate_auth0": false
  }'
```

**Expected Result**:
```json
{
  "valid": false,
  "reason": "session_not_found",
  "message": "Session token not found"
}
```

## Authorization Tests

### Test 5: Permission Check - Admin Role

**Objective**: Verify admin role has full access to all playbooks.

**Steps**:
```bash
# Test system playbook access (admin only)
noetlctl exec api_integration/auth0/check_playbook_access \
  --payload "{
    \"session_token\": \"$ADMIN_TOKEN\",
    \"playbook_path\": \"system/admin/backup\",
    \"action\": \"execute\",
    \"client_ip\": \"127.0.0.1\"
  }"
```

**Expected Result**:
```json
{
  "allowed": true,
  "user": {
    "user_id": 1,
    "email": "admin@test.noetl.io",
    "roles": ["admin"]
  },
  "playbook_path": "system/admin/backup",
  "action": "execute",
  "matched_permissions": [
    {
      "role_name": "admin",
      "permission_type": "pattern_match",
      "can_execute": true,
      "can_view": true,
      "can_modify": true
    }
  ],
  "message": "Access granted to execute playbook: system/admin/backup"
}
```

### Test 6: Permission Check - Developer Role

**Objective**: Verify developer can access non-system playbooks.

**Steps**:
```bash
# Test data playbook access (should succeed)
noetlctl exec api_integration/auth0/check_playbook_access \
  --payload "{
    \"session_token\": \"$DEV_TOKEN\",
    \"playbook_path\": \"data/etl/load_users\",
    \"action\": \"execute\"
  }"

# Expected: {"allowed": true, ...}

# Test system playbook access (should fail)
noetlctl exec api_integration/auth0/check_playbook_access \
  --payload "{
    \"session_token\": \"$DEV_TOKEN\",
    \"playbook_path\": \"system/admin/backup\",
    \"action\": \"execute\"
  }"

# Expected: {"allowed": false, "reason": "insufficient_permissions"}
```

**Verification**:
```sql
-- Check developer playbook permissions
SELECT pp.playbook_path, pp.can_execute, pp.allow_pattern, pp.deny_pattern
FROM auth.playbook_permissions pp
JOIN auth.roles r ON pp.role_id = r.role_id
WHERE r.role_name = 'developer';
-- Expected: allow_pattern = '*', deny_pattern = 'system/*'
```

### Test 7: Permission Check - Analyst Role

**Objective**: Verify analyst can only execute data/* playbooks.

**Steps**:
```bash
# Test data playbook access (should succeed)
noetlctl exec api_integration/auth0/check_playbook_access \
  --payload "{
    \"session_token\": \"$ANALYST_TOKEN\",
    \"playbook_path\": \"data/reports/monthly\",
    \"action\": \"execute\"
  }"

# Expected: {"allowed": true}

# Test modify action (should fail - analyst can't modify)
noetlctl exec api_integration/auth0/check_playbook_access \
  --payload "{
    \"session_token\": \"$ANALYST_TOKEN\",
    \"playbook_path\": \"data/reports/monthly\",
    \"action\": \"modify\"
  }"

# Expected: {"allowed": false}
```

### Test 8: Permission Check - Viewer Role

**Objective**: Verify viewer has read-only access.

**Steps**:
```bash
# Test view action (should succeed)
noetlctl exec api_integration/auth0/check_playbook_access \
  --payload "{
    \"session_token\": \"$VIEWER_TOKEN\",
    \"playbook_path\": \"data/reports/monthly\",
    \"action\": \"view\"
  }"

# Expected: {"allowed": true}

# Test execute action (should fail)
noetlctl exec api_integration/auth0/check_playbook_access \
  --payload "{
    \"session_token\": \"$VIEWER_TOKEN\",
    \"playbook_path\": \"data/reports/monthly\",
    \"action\": \"execute\"
  }"

# Expected: {"allowed": false}
```

## Security Tests

### Test 9: Session Expiration Handling

**Objective**: Verify expired sessions are rejected.

**Steps**:
```sql
-- Create expired session
INSERT INTO auth.sessions (
  user_id,
  session_token,
  auth0_token,
  expires_at,
  created_at
)
VALUES (
  1,
  encode(gen_random_bytes(32), 'hex'),
  'expired_token',
  NOW() - INTERVAL '1 hour',  -- Already expired
  NOW() - INTERVAL '25 hours'
)
RETURNING session_token;
-- Save token as EXPIRED_TOKEN
```

```bash
# Test validation with expired token
noetlctl exec api_integration/auth0/auth0_validate_session \
  --payload "{
    \"session_token\": \"$EXPIRED_TOKEN\",
    \"validate_auth0\": false
  }"
```

**Expected Result**:
```json
{
  "valid": false,
  "reason": "session_expired_or_inactive",
  "message": "Session is expired or inactive"
}
```

### Test 10: Cleanup Expired Sessions

**Objective**: Test session cleanup function.

**Steps**:
```sql
-- Check expired sessions before cleanup
SELECT COUNT(*) 
FROM auth.sessions 
WHERE expires_at < NOW() AND is_active = true;
-- Expected: 1+ (from expired session test)

-- Run cleanup
SELECT auth.cleanup_expired_sessions();
-- Returns: number of sessions deactivated

-- Verify expired sessions are now inactive
SELECT session_id, is_active, expires_at
FROM auth.sessions
WHERE expires_at < NOW()
ORDER BY expires_at DESC;
-- Expected: All is_active = false
```

### Test 11: Audit Log Verification

**Objective**: Verify all authentication events are logged.

**Steps**:
```sql
-- Count events by type
SELECT 
  event_type,
  event_status,
  COUNT(*) as event_count
FROM auth.audit_log
GROUP BY event_type, event_status
ORDER BY event_type, event_status;

-- Expected output:
-- permission_check | allowed   | 5+
-- permission_check | denied    | 3+
-- session_validation | success | 8+
-- session_validation | failure | 2+

-- View recent audit log entries
SELECT 
  log_id,
  user_id,
  event_type,
  event_status,
  resource_type,
  resource_id,
  event_details,
  ip_address,
  created_at
FROM auth.audit_log
ORDER BY created_at DESC
LIMIT 20;

-- Check for permission_check events
SELECT 
  log_id,
  user_id,
  event_status,
  resource_id as playbook_path,
  event_details->>'action' as action,
  event_details->>'reason' as reason,
  created_at
FROM auth.audit_log
WHERE event_type = 'permission_check'
ORDER BY created_at DESC
LIMIT 10;
```

### Test 12: SQL Injection Protection

**Objective**: Verify parameterized queries prevent SQL injection.

**Steps**:
```bash
# Attempt SQL injection in session token
noetlctl exec api_integration/auth0/auth0_validate_session \
  --payload '{
    "session_token": "'; DROP TABLE auth.users; --",
    "validate_auth0": false
  }'

# Expected: {"valid": false, "reason": "session_not_found"}
# Verify auth.users table still exists:
```

```sql
SELECT COUNT(*) FROM auth.users;
-- Expected: 4 (test users intact)
```

## Performance Tests

### Test 13: Permission Check Performance

**Objective**: Measure permission check query performance.

**Steps**:
```sql
-- Enable timing
\timing on

-- Test permission check function
EXPLAIN ANALYZE
SELECT auth.check_playbook_permission(1, 'data/etl/load_users', 'execute');

-- Expected: < 5ms execution time

-- Test with pattern matching
EXPLAIN ANALYZE
SELECT auth.check_playbook_permission(2, 'api_integration/auth0/auth0_login', 'view');

-- Check index usage
SELECT schemaname, tablename, indexname, idx_scan
FROM pg_stat_user_indexes
WHERE schemaname = 'auth'
ORDER BY idx_scan DESC;
```

### Test 14: Session Validation Performance

**Objective**: Measure session lookup performance.

**Steps**:
```sql
\timing on

-- Test session lookup query
EXPLAIN ANALYZE
SELECT * FROM auth.sessions s
JOIN auth.users u ON s.user_id = u.user_id
WHERE s.session_token = '<ADMIN_TOKEN>';

-- Expected: Index scan on session_token, < 2ms

-- Verify index exists
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'sessions' AND schemaname = 'auth';
-- Expected: idx_sessions_token on session_token column
```

## Integration Tests

### Test 15: End-to-End Authentication Flow

**Objective**: Test complete authentication flow from login to playbook execution.

**Prerequisites**: Requires Auth0 application configured or mock setup.

**Steps** (pseudo-code with mock):
```bash
# 1. Mock login (create session)
SESSION_TOKEN=$(psql -h localhost -p 54321 -U demo -d demo_noetl -t -c \
  "INSERT INTO auth.sessions (user_id, session_token, auth0_token, expires_at)
   SELECT 1, encode(gen_random_bytes(32), 'hex'), 'mock', NOW() + INTERVAL '24h'
   FROM auth.users WHERE email = 'admin@test.noetl.io'
   RETURNING session_token;" | xargs)

echo "Session token: $SESSION_TOKEN"

# 2. Validate session
noetlctl exec api_integration/auth0/auth0_validate_session \
  --payload "{\"session_token\": \"$SESSION_TOKEN\", \"validate_auth0\": false}"

# 3. Check playbook permission
noetlctl exec api_integration/auth0/check_playbook_access \
  --payload "{
    \"session_token\": \"$SESSION_TOKEN\",
    \"playbook_path\": \"data/test/simple\",
    \"action\": \"execute\"
  }"

# 4. If allowed, execute playbook (mock - would be done by noetl-gateway)
# noetlctl exec data/test/simple --payload '{...}'

# 5. Verify audit trail
psql -h localhost -p 54321 -U demo -d demo_noetl -c \
  "SELECT event_type, event_status, resource_id
   FROM auth.audit_log
   WHERE user_id = 1
   ORDER BY created_at DESC
   LIMIT 5;"
```

## Cleanup

### Reset Test Data

```sql
-- Truncate audit log
TRUNCATE auth.audit_log CASCADE;

-- Delete test sessions
DELETE FROM auth.sessions WHERE user_id IN (1, 2, 3, 4);

-- Delete test users
DELETE FROM auth.users WHERE auth0_id LIKE 'auth0|%test';

-- Reset sequences
SELECT setval('auth.users_user_id_seq', 1, false);
SELECT setval('auth.sessions_session_id_seq', 1, false);
SELECT setval('auth.audit_log_log_id_seq', 1, false);
```

### Drop Auth Schema (if needed)

```sql
-- Drop entire auth schema (WARNING: destructive)
DROP SCHEMA IF EXISTS auth CASCADE;
DROP ROLE IF EXISTS auth_user;
```

## Summary

This testing guide covers:
- ✅ Schema provisioning and setup
- ✅ User and role management
- ✅ Session creation and validation
- ✅ Role-based access control (RBAC)
- ✅ Permission checking with pattern matching
- ✅ Audit logging verification
- ✅ Security testing (expiration, SQL injection)
- ✅ Performance testing
- ✅ End-to-end integration flow

For production deployment:
1. Replace mock sessions with real Auth0 integration
2. Implement token refresh mechanism
3. Add rate limiting for login attempts
4. Set up monitoring for audit log
5. Configure automated session cleanup
6. Deploy noetl-gateway with Auth0 configuration
