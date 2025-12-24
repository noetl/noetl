-- ============================================================================
-- NoETL Auth Schema Provisioning Script
-- ============================================================================
-- Purpose: Create database schema and user for Auth0 integration
-- Database: demo_noetl
-- Schema: auth
-- User: auth_user
-- 
-- This script is executed as a Kubernetes job with admin credentials (demo user)
-- to provision the auth schema and dedicated auth_user role.
-- ============================================================================

-- ============================================================================
-- 1. CREATE SCHEMA
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS auth;

COMMENT ON SCHEMA auth IS 'Authentication and authorization data for gateway Auth0 integration';

-- ============================================================================
-- 2. CREATE DATABASE USER
-- ============================================================================
-- Create dedicated user for auth schema operations
-- Password should be changed after first deployment
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'auth_user') THEN
        CREATE ROLE auth_user WITH LOGIN PASSWORD 'auth_user_temp_password_change_me';
    END IF;
END
$$;

-- Grant schema usage to auth_user
GRANT USAGE ON SCHEMA auth TO auth_user;

-- Grant default privileges for future objects
ALTER DEFAULT PRIVILEGES IN SCHEMA auth GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO auth_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA auth GRANT USAGE, SELECT ON SEQUENCES TO auth_user;

-- ============================================================================
-- 3. CREATE TABLES
-- ============================================================================

-- Users table: Core user information from Auth0
CREATE TABLE IF NOT EXISTS auth.users (
    user_id BIGSERIAL PRIMARY KEY,
    auth0_id VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    display_name VARCHAR(255),
    profile_data JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_login_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT true,
    CONSTRAINT email_format CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
);

CREATE INDEX idx_users_auth0_id ON auth.users(auth0_id);
CREATE INDEX idx_users_email ON auth.users(email);
CREATE INDEX idx_users_is_active ON auth.users(is_active) WHERE is_active = true;

COMMENT ON TABLE auth.users IS 'User accounts synchronized with Auth0';
COMMENT ON COLUMN auth.users.auth0_id IS 'Auth0 unique user identifier (sub claim)';
COMMENT ON COLUMN auth.users.profile_data IS 'Additional user profile data from Auth0 (name, picture, etc.)';

-- Roles table: Role definitions for RBAC
CREATE TABLE IF NOT EXISTS auth.roles (
    role_id SERIAL PRIMARY KEY,
    role_name VARCHAR(50) UNIQUE NOT NULL,
    description TEXT,
    is_system_role BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT role_name_lowercase CHECK (role_name = lower(role_name))
);

CREATE INDEX idx_roles_name ON auth.roles(role_name);

COMMENT ON TABLE auth.roles IS 'Role definitions for role-based access control';
COMMENT ON COLUMN auth.roles.is_system_role IS 'System roles cannot be deleted or modified';

-- Permissions table: Granular permission definitions
CREATE TABLE IF NOT EXISTS auth.permissions (
    permission_id SERIAL PRIMARY KEY,
    permission_name VARCHAR(100) UNIQUE NOT NULL,
    resource_type VARCHAR(50) NOT NULL, -- playbook, catalog, credential, etc.
    action VARCHAR(50) NOT NULL, -- execute, view, create, update, delete
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT permission_name_format CHECK (permission_name ~ '^[a-z0-9_:]+$')
);

CREATE INDEX idx_permissions_resource ON auth.permissions(resource_type);
CREATE INDEX idx_permissions_action ON auth.permissions(action);

COMMENT ON TABLE auth.permissions IS 'Granular permission definitions';
COMMENT ON COLUMN auth.permissions.permission_name IS 'Format: resource_type:action (e.g., playbook:execute)';

-- User-Role mapping: Many-to-many relationship
CREATE TABLE IF NOT EXISTS auth.user_roles (
    user_id BIGINT NOT NULL REFERENCES auth.users(user_id) ON DELETE CASCADE,
    role_id INTEGER NOT NULL REFERENCES auth.roles(role_id) ON DELETE CASCADE,
    granted_at TIMESTAMPTZ DEFAULT NOW(),
    granted_by BIGINT REFERENCES auth.users(user_id),
    expires_at TIMESTAMPTZ,
    PRIMARY KEY (user_id, role_id)
);

CREATE INDEX idx_user_roles_user ON auth.user_roles(user_id);
CREATE INDEX idx_user_roles_role ON auth.user_roles(role_id);
CREATE INDEX idx_user_roles_active ON auth.user_roles(user_id) WHERE expires_at IS NULL OR expires_at > NOW();

COMMENT ON TABLE auth.user_roles IS 'User role assignments';
COMMENT ON COLUMN auth.user_roles.expires_at IS 'Role expiration timestamp (NULL = no expiration)';

-- Role-Permission mapping: Many-to-many relationship
CREATE TABLE IF NOT EXISTS auth.role_permissions (
    role_id INTEGER NOT NULL REFERENCES auth.roles(role_id) ON DELETE CASCADE,
    permission_id INTEGER NOT NULL REFERENCES auth.permissions(permission_id) ON DELETE CASCADE,
    granted_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (role_id, permission_id)
);

CREATE INDEX idx_role_permissions_role ON auth.role_permissions(role_id);
CREATE INDEX idx_role_permissions_permission ON auth.role_permissions(permission_id);

COMMENT ON TABLE auth.role_permissions IS 'Permission assignments to roles';

-- Playbook permissions: Fine-grained playbook access control
CREATE TABLE IF NOT EXISTS auth.playbook_permissions (
    permission_id BIGSERIAL PRIMARY KEY,
    role_id INTEGER NOT NULL REFERENCES auth.roles(role_id) ON DELETE CASCADE,
    playbook_path VARCHAR(500) NOT NULL,
    can_execute BOOLEAN DEFAULT false,
    can_view BOOLEAN DEFAULT false,
    can_modify BOOLEAN DEFAULT false,
    allow_pattern VARCHAR(500), -- Glob pattern for bulk permissions
    deny_pattern VARCHAR(500),  -- Explicit deny pattern (takes precedence)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT playbook_path_format CHECK (playbook_path ~ '^[a-z0-9/_-]+$')
);

CREATE INDEX idx_playbook_perms_role ON auth.playbook_permissions(role_id);
CREATE INDEX idx_playbook_perms_path ON auth.playbook_permissions(playbook_path);
CREATE INDEX idx_playbook_perms_pattern ON auth.playbook_permissions(allow_pattern) WHERE allow_pattern IS NOT NULL;

COMMENT ON TABLE auth.playbook_permissions IS 'Playbook-level access control';
COMMENT ON COLUMN auth.playbook_permissions.allow_pattern IS 'Glob pattern for bulk allow (e.g., data/*, api/public/*)';
COMMENT ON COLUMN auth.playbook_permissions.deny_pattern IS 'Explicit deny pattern overrides allow patterns';

-- Sessions table: Active user sessions
CREATE TABLE IF NOT EXISTS auth.sessions (
    session_id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES auth.users(user_id) ON DELETE CASCADE,
    session_token VARCHAR(255) UNIQUE NOT NULL,
    auth0_token TEXT,
    auth0_refresh_token TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    last_activity_at TIMESTAMPTZ DEFAULT NOW(),
    ip_address INET,
    user_agent TEXT,
    is_active BOOLEAN DEFAULT true,
    CONSTRAINT valid_expiration CHECK (expires_at > created_at)
);

CREATE INDEX idx_sessions_user ON auth.sessions(user_id);
CREATE INDEX idx_sessions_token ON auth.sessions(session_token);
CREATE INDEX idx_sessions_active ON auth.sessions(is_active, expires_at) WHERE is_active = true;
CREATE INDEX idx_sessions_expiry ON auth.sessions(expires_at);

COMMENT ON TABLE auth.sessions IS 'Active user sessions with Auth0 tokens';
COMMENT ON COLUMN auth.sessions.session_token IS 'NoETL session token returned to client';
COMMENT ON COLUMN auth.sessions.auth0_token IS 'Auth0 access token for validation';

-- Audit log: Authentication and authorization events
CREATE TABLE IF NOT EXISTS auth.audit_log (
    log_id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES auth.users(user_id) ON DELETE SET NULL,
    session_id BIGINT REFERENCES auth.sessions(session_id) ON DELETE SET NULL,
    event_type VARCHAR(50) NOT NULL, -- login, logout, permission_check, playbook_execute, etc.
    event_status VARCHAR(20) NOT NULL, -- success, failure, denied
    resource_type VARCHAR(50),
    resource_id VARCHAR(255),
    event_details JSONB DEFAULT '{}',
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_audit_log_user ON auth.audit_log(user_id);
CREATE INDEX idx_audit_log_event_type ON auth.audit_log(event_type);
CREATE INDEX idx_audit_log_created ON auth.audit_log(created_at DESC);
CREATE INDEX idx_audit_log_status ON auth.audit_log(event_status);

COMMENT ON TABLE auth.audit_log IS 'Authentication and authorization audit trail';
COMMENT ON COLUMN auth.audit_log.event_details IS 'Additional event context (playbook path, error messages, etc.)';

-- ============================================================================
-- 4. CREATE FUNCTIONS
-- ============================================================================

-- Function: Update timestamp on row modification
CREATE OR REPLACE FUNCTION auth.update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Function: Cleanup expired sessions
CREATE OR REPLACE FUNCTION auth.cleanup_expired_sessions()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    UPDATE auth.sessions 
    SET is_active = false 
    WHERE is_active = true 
      AND expires_at < NOW();
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION auth.cleanup_expired_sessions() IS 'Deactivate expired sessions';

-- Function: Check if user has permission for playbook
CREATE OR REPLACE FUNCTION auth.check_playbook_permission(
    p_user_id BIGINT,
    p_playbook_path VARCHAR,
    p_action VARCHAR DEFAULT 'execute'
)
RETURNS BOOLEAN AS $$
DECLARE
    has_permission BOOLEAN := false;
BEGIN
    -- Check if user has active roles with permission for this playbook
    SELECT EXISTS(
        SELECT 1
        FROM auth.user_roles ur
        JOIN auth.playbook_permissions pp ON ur.role_id = pp.role_id
        WHERE ur.user_id = p_user_id
          AND (ur.expires_at IS NULL OR ur.expires_at > NOW())
          AND (
              -- Exact match
              pp.playbook_path = p_playbook_path
              -- Pattern match
              OR (pp.allow_pattern IS NOT NULL AND p_playbook_path LIKE pp.allow_pattern)
          )
          -- Check deny patterns (explicit deny overrides allow)
          AND (pp.deny_pattern IS NULL OR p_playbook_path NOT LIKE pp.deny_pattern)
          -- Check action permission
          AND CASE 
              WHEN p_action = 'execute' THEN pp.can_execute
              WHEN p_action = 'view' THEN pp.can_view
              WHEN p_action = 'modify' THEN pp.can_modify
              ELSE false
          END
    ) INTO has_permission;
    
    RETURN has_permission;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION auth.check_playbook_permission IS 'Check if user has permission to access playbook';

-- ============================================================================
-- 5. CREATE TRIGGERS
-- ============================================================================

CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON auth.users
    FOR EACH ROW
    EXECUTE FUNCTION auth.update_updated_at();

CREATE TRIGGER trg_playbook_perms_updated_at
    BEFORE UPDATE ON auth.playbook_permissions
    FOR EACH ROW
    EXECUTE FUNCTION auth.update_updated_at();

-- ============================================================================
-- 6. INSERT DEFAULT DATA
-- ============================================================================

-- Insert default roles
INSERT INTO auth.roles (role_name, description, is_system_role)
VALUES 
    ('admin', 'Full system access', true),
    ('developer', 'Create and manage playbooks', true),
    ('analyst', 'Execute playbooks and view results', true),
    ('viewer', 'View playbooks and execution history', true)
ON CONFLICT (role_name) DO NOTHING;

-- Insert default permissions
INSERT INTO auth.permissions (permission_name, resource_type, action, description)
VALUES 
    ('playbook:execute', 'playbook', 'execute', 'Execute playbooks'),
    ('playbook:view', 'playbook', 'view', 'View playbook definitions'),
    ('playbook:create', 'playbook', 'create', 'Create new playbooks'),
    ('playbook:modify', 'playbook', 'modify', 'Modify existing playbooks'),
    ('playbook:delete', 'playbook', 'delete', 'Delete playbooks'),
    ('catalog:view', 'catalog', 'view', 'View catalog entries'),
    ('catalog:manage', 'catalog', 'manage', 'Manage catalog'),
    ('credential:view', 'credential', 'view', 'View credentials'),
    ('credential:manage', 'credential', 'manage', 'Manage credentials'),
    ('execution:view', 'execution', 'view', 'View execution history'),
    ('execution:cancel', 'execution', 'cancel', 'Cancel running executions'),
    ('system:admin', 'system', 'admin', 'System administration')
ON CONFLICT (permission_name) DO NOTHING;

-- Assign permissions to admin role
INSERT INTO auth.role_permissions (role_id, permission_id)
SELECT r.role_id, p.permission_id
FROM auth.roles r
CROSS JOIN auth.permissions p
WHERE r.role_name = 'admin'
ON CONFLICT DO NOTHING;

-- Assign permissions to developer role
INSERT INTO auth.role_permissions (role_id, permission_id)
SELECT r.role_id, p.permission_id
FROM auth.roles r
JOIN auth.permissions p ON p.permission_name IN (
    'playbook:execute', 'playbook:view', 'playbook:create', 'playbook:modify',
    'catalog:view', 'credential:view', 'execution:view'
)
WHERE r.role_name = 'developer'
ON CONFLICT DO NOTHING;

-- Assign permissions to analyst role
INSERT INTO auth.role_permissions (role_id, permission_id)
SELECT r.role_id, p.permission_id
FROM auth.roles r
JOIN auth.permissions p ON p.permission_name IN (
    'playbook:execute', 'playbook:view', 'execution:view'
)
WHERE r.role_name = 'analyst'
ON CONFLICT DO NOTHING;

-- Assign permissions to viewer role
INSERT INTO auth.role_permissions (role_id, permission_id)
SELECT r.role_id, p.permission_id
FROM auth.roles r
JOIN auth.permissions p ON p.permission_name IN (
    'playbook:view', 'execution:view'
)
WHERE r.role_name = 'viewer'
ON CONFLICT DO NOTHING;

-- Grant admin full playbook access
INSERT INTO auth.playbook_permissions (role_id, playbook_path, can_execute, can_view, can_modify, allow_pattern)
SELECT role_id, '*', true, true, true, '*'
FROM auth.roles
WHERE role_name = 'admin'
ON CONFLICT DO NOTHING;

-- Grant developer access to non-system playbooks
INSERT INTO auth.playbook_permissions (role_id, playbook_path, can_execute, can_view, can_modify, allow_pattern, deny_pattern)
SELECT role_id, '*', true, true, true, '*', 'system/*'
FROM auth.roles
WHERE role_name = 'developer'
ON CONFLICT DO NOTHING;

-- Grant analyst execute access
INSERT INTO auth.playbook_permissions (role_id, playbook_path, can_execute, can_view, can_modify, allow_pattern)
SELECT role_id, '*', true, true, false, 'data/*'
FROM auth.roles
WHERE role_name = 'analyst'
ON CONFLICT DO NOTHING;

-- Grant viewer read-only access
INSERT INTO auth.playbook_permissions (role_id, playbook_path, can_execute, can_view, can_modify, allow_pattern)
SELECT role_id, '*', false, true, false, '*'
FROM auth.roles
WHERE role_name = 'viewer'
ON CONFLICT DO NOTHING;

-- ============================================================================
-- 7. GRANT PERMISSIONS TO auth_user
-- ============================================================================

-- Grant table-level permissions
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA auth TO auth_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA auth TO auth_user;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA auth TO auth_user;

-- ============================================================================
-- 8. VERIFICATION
-- ============================================================================

-- Output summary of created objects
DO $$
DECLARE
    table_count INTEGER;
    function_count INTEGER;
    role_count INTEGER;
    perm_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO table_count FROM information_schema.tables WHERE table_schema = 'auth';
    SELECT COUNT(*) INTO function_count FROM pg_proc p JOIN pg_namespace n ON p.pronamespace = n.oid WHERE n.nspname = 'auth';
    SELECT COUNT(*) INTO role_count FROM auth.roles;
    SELECT COUNT(*) INTO perm_count FROM auth.permissions;
    
    RAISE NOTICE '========================================';
    RAISE NOTICE 'Auth Schema Provisioning Complete';
    RAISE NOTICE '========================================';
    RAISE NOTICE 'Tables created: %', table_count;
    RAISE NOTICE 'Functions created: %', function_count;
    RAISE NOTICE 'Roles defined: %', role_count;
    RAISE NOTICE 'Permissions defined: %', perm_count;
    RAISE NOTICE '========================================';
    RAISE NOTICE 'Next steps:';
    RAISE NOTICE '1. Change auth_user password';
    RAISE NOTICE '2. Register pg_auth_user credential';
    RAISE NOTICE '3. Deploy authentication playbooks';
    RAISE NOTICE '========================================';
END;
$$;
