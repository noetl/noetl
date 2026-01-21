-- NoETL Infrastructure as Playbook (IaP) - State Schema
-- Version: 1.0.0
-- Description: DuckDB schema for tracking cloud infrastructure state
--
-- Usage:
--   duckdb /tmp/noetl-iap-state.duckdb < state_schema.sql
--
-- This schema supports both:
--   - Terraform-like: Mutable state with change tracking
--   - Crossplane-like: Declarative reconciliation with drift detection

-- ============================================================================
-- CORE TABLES
-- ============================================================================

-- Resource type registry (similar to Kubernetes CRDs)
CREATE TABLE IF NOT EXISTS resource_types (
    type_id VARCHAR PRIMARY KEY,          -- e.g., 'container.googleapis.com/Cluster'
    provider VARCHAR NOT NULL,             -- gcp, aws, azure, kubernetes
    api_version VARCHAR NOT NULL,          -- API version, e.g., 'v1', 'v1beta1'
    kind VARCHAR NOT NULL,                 -- Resource kind, e.g., 'Cluster', 'Instance'
    plural_name VARCHAR NOT NULL,          -- Plural form for REST API, e.g., 'clusters'
    description VARCHAR,
    schema JSON,                           -- JSON Schema for resource spec validation
    supported_operations VARCHAR[],        -- ['create', 'read', 'update', 'delete']
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Main resources table - tracks all managed infrastructure
CREATE TABLE IF NOT EXISTS resources (
    -- Identity
    resource_id VARCHAR PRIMARY KEY,       -- Unique identifier: {project}/{region}/{name}
    type_id VARCHAR NOT NULL,              -- Reference to resource_types.type_id
    name VARCHAR NOT NULL,                 -- Human-readable name
    namespace VARCHAR DEFAULT 'default',   -- Logical grouping (K8s namespace concept)
    
    -- Location
    project VARCHAR,                       -- GCP project / AWS account / Azure subscription
    region VARCHAR,                        -- Region or 'global'
    zone VARCHAR,                          -- Zone for zonal resources
    
    -- State (Terraform-like)
    desired_state JSON NOT NULL,           -- Target configuration from playbook
    current_state JSON,                    -- Last observed state from cloud API
    status VARCHAR DEFAULT 'pending',      -- pending, creating, running, updating, deleting, error, deleted
    
    -- Metadata (Crossplane-like)
    labels JSON DEFAULT '{}',              -- Key-value labels
    annotations JSON DEFAULT '{}',         -- Extended metadata
    finalizers VARCHAR[] DEFAULT ARRAY[]::VARCHAR[],  -- Cleanup hooks
    owner_references JSON DEFAULT '[]',    -- Parent resource references
    
    -- Sync tracking
    generation BIGINT DEFAULT 1,           -- Incremented on desired_state change
    observed_generation BIGINT DEFAULT 0,  -- Last generation successfully reconciled
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_synced_at TIMESTAMP,              -- Last successful API sync
    deleted_at TIMESTAMP,                  -- Soft delete timestamp
    
    -- Conditions (Crossplane-like status conditions)
    conditions JSON DEFAULT '[]'           -- Array of {type, status, reason, message, lastTransitionTime}
);

-- ============================================================================
-- VERSIONING & HISTORY
-- ============================================================================

-- Snapshots for point-in-time state capture
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id VARCHAR PRIMARY KEY,
    workspace VARCHAR NOT NULL DEFAULT 'default',
    
    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR,                    -- User or automation that created snapshot
    description VARCHAR,
    
    -- Content tracking
    resource_count INTEGER,
    checksum VARCHAR,                      -- SHA256 of snapshot content
    size_bytes BIGINT,
    
    -- Version control
    tags JSON DEFAULT '[]',                -- Version tags, e.g., ['v1.2.0', 'production']
    parent_snapshot_id VARCHAR,            -- For branching support
    is_locked BOOLEAN DEFAULT FALSE,       -- Prevent modification
    
    -- Export tracking
    exported_to VARCHAR,                   -- GCS path if exported
    exported_at TIMESTAMP
);

-- Resource states within each snapshot
CREATE TABLE IF NOT EXISTS snapshot_resources (
    snapshot_id VARCHAR NOT NULL,
    resource_id VARCHAR NOT NULL,
    resource_type VARCHAR NOT NULL,
    state JSON NOT NULL,
    
    PRIMARY KEY (snapshot_id, resource_id)
);

-- ============================================================================
-- OPERATIONS & AUDIT
-- ============================================================================

-- Operations log for complete audit trail
CREATE TABLE IF NOT EXISTS operations (
    operation_id VARCHAR PRIMARY KEY,
    resource_id VARCHAR NOT NULL,
    
    -- Operation details
    operation_type VARCHAR NOT NULL,       -- create, update, delete, sync, import
    status VARCHAR NOT NULL,               -- pending, in_progress, completed, failed, cancelled
    
    -- Change tracking
    before_state JSON,                     -- State before operation
    after_state JSON,                      -- State after operation
    diff JSON,                             -- Computed difference
    
    -- Execution details
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    duration_ms INTEGER,                   -- Duration in milliseconds
    error_message VARCHAR,
    error_details JSON,                    -- Full error context
    
    -- Context
    playbook_name VARCHAR,
    playbook_path VARCHAR,
    execution_id VARCHAR,
    step_name VARCHAR,
    user_name VARCHAR,
    
    -- Request/Response (for debugging)
    api_request JSON,                      -- HTTP request sent to cloud API
    api_response JSON,                     -- HTTP response received
    api_latency_ms INTEGER
);

-- ============================================================================
-- DRIFT DETECTION & RECONCILIATION
-- ============================================================================

-- Drift records for tracking configuration drift
CREATE TABLE IF NOT EXISTS drift_records (
    drift_id VARCHAR PRIMARY KEY,
    resource_id VARCHAR NOT NULL,
    
    -- Detection
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    detection_method VARCHAR DEFAULT 'sync', -- sync, scheduled, manual
    
    -- Drift details
    drift_type VARCHAR NOT NULL,           -- added, removed, modified
    field_path VARCHAR,                    -- JSON path of changed field, e.g., '$.spec.replicas'
    expected_value JSON,                   -- Value from desired_state
    actual_value JSON,                     -- Value from current_state
    severity VARCHAR DEFAULT 'medium',     -- low, medium, high, critical
    
    -- Resolution
    resolved_at TIMESTAMP,
    resolution_action VARCHAR,             -- accept, revert, ignore, manual
    resolved_by VARCHAR,
    resolution_notes VARCHAR,
    
    -- Related snapshot for rollback
    snapshot_id VARCHAR
);

-- ============================================================================
-- CONCURRENCY CONTROL
-- ============================================================================

-- Distributed locks for state file access
CREATE TABLE IF NOT EXISTS locks (
    lock_id VARCHAR PRIMARY KEY,
    workspace VARCHAR NOT NULL UNIQUE,
    
    -- Lock details
    acquired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    acquired_by VARCHAR NOT NULL,          -- Host or user that acquired lock
    expires_at TIMESTAMP NOT NULL,
    
    -- Context
    operation_type VARCHAR,                -- Type of operation holding lock
    lock_data JSON                         -- Additional lock context
);

-- ============================================================================
-- PROVIDER CONFIGURATIONS
-- ============================================================================

-- Provider configurations (like Crossplane ProviderConfigs)
CREATE TABLE IF NOT EXISTS provider_configs (
    config_id VARCHAR PRIMARY KEY,
    provider VARCHAR NOT NULL,             -- gcp, aws, azure
    name VARCHAR NOT NULL,
    
    -- Authentication
    auth_type VARCHAR NOT NULL,            -- adc, service_account, iam_role, etc.
    auth_source VARCHAR,                   -- Path or reference to credentials
    
    -- Configuration
    default_project VARCHAR,
    default_region VARCHAR,
    default_zone VARCHAR,
    
    -- Status
    status VARCHAR DEFAULT 'active',       -- active, inactive, error
    last_verified_at TIMESTAMP,
    error_message VARCHAR,
    
    -- Metadata
    labels JSON DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE (provider, name)
);

-- ============================================================================
-- VIEWS
-- ============================================================================

-- Resource summary by type and status
CREATE OR REPLACE VIEW resource_summary AS
SELECT 
    r.type_id,
    rt.provider,
    rt.kind,
    COUNT(*) as total_count,
    SUM(CASE WHEN r.status IN ('running', 'RUNNING', 'active', 'ACTIVE') THEN 1 ELSE 0 END) as healthy_count,
    SUM(CASE WHEN r.status IN ('pending', 'creating', 'updating') THEN 1 ELSE 0 END) as pending_count,
    SUM(CASE WHEN r.status IN ('error', 'ERROR', 'failed', 'FAILED') THEN 1 ELSE 0 END) as error_count,
    SUM(CASE WHEN r.generation != r.observed_generation THEN 1 ELSE 0 END) as out_of_sync_count
FROM resources r
LEFT JOIN resource_types rt ON r.type_id = rt.type_id
WHERE r.deleted_at IS NULL
GROUP BY r.type_id, rt.provider, rt.kind;

-- Pending drift records with resource details
CREATE OR REPLACE VIEW pending_drift AS
SELECT 
    d.drift_id,
    d.resource_id,
    d.drift_type,
    d.field_path,
    d.expected_value,
    d.actual_value,
    d.severity,
    d.detected_at,
    r.name as resource_name,
    r.type_id,
    r.project,
    r.status as resource_status
FROM drift_records d
JOIN resources r ON d.resource_id = r.resource_id
WHERE d.resolved_at IS NULL
ORDER BY 
    CASE d.severity 
        WHEN 'critical' THEN 1 
        WHEN 'high' THEN 2 
        WHEN 'medium' THEN 3 
        ELSE 4 
    END,
    d.detected_at DESC;

-- Recent operations with resource context
CREATE OR REPLACE VIEW recent_operations AS
SELECT 
    o.operation_id,
    o.operation_type,
    o.status,
    o.resource_id,
    r.name as resource_name,
    r.type_id as resource_type,
    o.started_at,
    o.completed_at,
    o.duration_ms,
    o.error_message,
    o.playbook_name,
    o.user_name
FROM operations o
LEFT JOIN resources r ON o.resource_id = r.resource_id
ORDER BY o.started_at DESC
LIMIT 100;

-- Resources needing reconciliation (out of sync)
CREATE OR REPLACE VIEW needs_reconciliation AS
SELECT 
    r.resource_id,
    r.name,
    r.type_id,
    r.project,
    r.status,
    r.generation,
    r.observed_generation,
    r.last_synced_at,
    DATEDIFF('minute', r.last_synced_at, CURRENT_TIMESTAMP) as minutes_since_sync
FROM resources r
WHERE r.deleted_at IS NULL
  AND (r.generation != r.observed_generation 
       OR r.last_synced_at IS NULL 
       OR DATEDIFF('minute', r.last_synced_at, CURRENT_TIMESTAMP) > 60)
ORDER BY r.last_synced_at ASC NULLS FIRST;

-- ============================================================================
-- INDEXES
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_resources_type ON resources(type_id);
CREATE INDEX IF NOT EXISTS idx_resources_status ON resources(status);
CREATE INDEX IF NOT EXISTS idx_resources_project ON resources(project);
CREATE INDEX IF NOT EXISTS idx_resources_namespace ON resources(namespace);
CREATE INDEX IF NOT EXISTS idx_resources_updated ON resources(updated_at);
CREATE INDEX IF NOT EXISTS idx_resources_synced ON resources(last_synced_at);

CREATE INDEX IF NOT EXISTS idx_snapshots_workspace ON snapshots(workspace);
CREATE INDEX IF NOT EXISTS idx_snapshots_created ON snapshots(created_at);

CREATE INDEX IF NOT EXISTS idx_operations_resource ON operations(resource_id);
CREATE INDEX IF NOT EXISTS idx_operations_status ON operations(status);
CREATE INDEX IF NOT EXISTS idx_operations_started ON operations(started_at);
CREATE INDEX IF NOT EXISTS idx_operations_playbook ON operations(playbook_name);

CREATE INDEX IF NOT EXISTS idx_drift_resource ON drift_records(resource_id);
CREATE INDEX IF NOT EXISTS idx_drift_resolved ON drift_records(resolved_at);
CREATE INDEX IF NOT EXISTS idx_drift_severity ON drift_records(severity);

-- ============================================================================
-- INITIAL DATA
-- ============================================================================

-- Insert common GCP resource types
INSERT OR IGNORE INTO resource_types (type_id, provider, api_version, kind, plural_name, description, supported_operations)
VALUES 
    ('container.googleapis.com/Cluster', 'gcp', 'v1', 'Cluster', 'clusters', 
     'Google Kubernetes Engine cluster', ARRAY['create', 'read', 'update', 'delete']),
    
    ('compute.googleapis.com/Instance', 'gcp', 'v1', 'Instance', 'instances', 
     'Google Compute Engine VM instance', ARRAY['create', 'read', 'update', 'delete']),
    
    ('compute.googleapis.com/Network', 'gcp', 'v1', 'Network', 'networks', 
     'Google Cloud VPC network', ARRAY['create', 'read', 'update', 'delete']),
    
    ('compute.googleapis.com/Subnetwork', 'gcp', 'v1', 'Subnetwork', 'subnetworks', 
     'Google Cloud VPC subnetwork', ARRAY['create', 'read', 'update', 'delete']),
    
    ('compute.googleapis.com/Firewall', 'gcp', 'v1', 'Firewall', 'firewalls', 
     'Google Cloud firewall rule', ARRAY['create', 'read', 'update', 'delete']),
    
    ('storage.googleapis.com/Bucket', 'gcp', 'v1', 'Bucket', 'buckets', 
     'Google Cloud Storage bucket', ARRAY['create', 'read', 'update', 'delete']),
    
    ('iam.googleapis.com/ServiceAccount', 'gcp', 'v1', 'ServiceAccount', 'serviceAccounts', 
     'Google Cloud IAM service account', ARRAY['create', 'read', 'update', 'delete']),
    
    ('sqladmin.googleapis.com/Instance', 'gcp', 'v1beta4', 'DatabaseInstance', 'instances', 
     'Google Cloud SQL instance', ARRAY['create', 'read', 'update', 'delete']),
    
    ('pubsub.googleapis.com/Topic', 'gcp', 'v1', 'Topic', 'topics', 
     'Google Cloud Pub/Sub topic', ARRAY['create', 'read', 'delete']),
    
    ('pubsub.googleapis.com/Subscription', 'gcp', 'v1', 'Subscription', 'subscriptions', 
     'Google Cloud Pub/Sub subscription', ARRAY['create', 'read', 'update', 'delete']);

-- Print schema summary
SELECT 'IaP State Schema initialized successfully' as message;
SELECT COUNT(*) as resource_types_count FROM resource_types;
