-- Canonical Schema DDL for NoETL Platform

-- Resource
CREATE TABLE IF NOT EXISTS noetl.resource (
    name VARCHAR PRIMARY KEY,
    meta JSONB
);

-- Catalog
CREATE TABLE IF NOT EXISTS noetl.catalog (
    catalog_id BIGINT PRIMARY KEY,
    path     TEXT            NOT NULL,
    version  SMALLSERIAL     NOT NULL,
    kind     VARCHAR         NOT NULL REFERENCES noetl.resource(name),
    content                  TEXT,
    layout                   JSONB,     -- Optional layout for UI Workflow Builder
    payload                  JSONB,
    meta                     JSONB,
    created_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (path, version)
);

-- Variables Cache
-- Stores runtime variables for playbook execution scope with access tracking
CREATE TABLE IF NOT EXISTS noetl.transient (
    execution_id BIGINT NOT NULL,
    var_name TEXT NOT NULL,
    var_type TEXT NOT NULL CHECK (var_type IN ('user_defined', 'step_result', 'computed', 'iterator_state')),
    var_value JSONB NOT NULL,
    source_step TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    accessed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    access_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (execution_id, var_name)
);

CREATE INDEX IF NOT EXISTS idx_transient_type ON noetl.transient (var_type);
CREATE INDEX IF NOT EXISTS idx_transient_source ON noetl.transient (source_step);
CREATE INDEX IF NOT EXISTS idx_transient_execution ON noetl.transient (execution_id);

COMMENT ON TABLE noetl.transient IS 'Execution-scoped variables for playbook runtime with cache tracking';
COMMENT ON COLUMN noetl.transient.var_type IS 'step_result: result from a step, user_defined: explicit variable, computed: derived value, iterator_state: iterator loop state';
COMMENT ON COLUMN noetl.transient.var_value IS 'Variable value stored as JSONB (supports any type)';
COMMENT ON COLUMN noetl.transient.source_step IS 'Step name that produced this variable';
COMMENT ON COLUMN noetl.transient.access_count IS 'Number of times this variable has been accessed';
COMMENT ON COLUMN noetl.transient.accessed_at IS 'Last time this variable was read';

-- Event
CREATE TABLE IF NOT EXISTS noetl.event (
    execution_id BIGINT,
    catalog_id BIGINT NOT NULL REFERENCES noetl.catalog(catalog_id),
    event_id BIGINT,
    parent_event_id BIGINT,
    parent_execution_id BIGINT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    event_type VARCHAR,
    node_id VARCHAR,
    node_name VARCHAR,
    node_type VARCHAR,
    status VARCHAR,
    duration DOUBLE PRECISION,
    context JSONB,
    result JSONB,
    meta   JSONB,
    error TEXT,
    current_index INTEGER,
    current_item TEXT,
    worker_id VARCHAR,
    distributed_state VARCHAR,
    context_key VARCHAR,
    context_value TEXT,
    trace_component JSONB,
    stack_trace TEXT,
    PRIMARY KEY (execution_id, event_id)
);
DO $$ BEGIN
    ALTER TABLE noetl.event ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP;
EXCEPTION WHEN others THEN NULL; END $$;

-- Add indexes for common event queries
CREATE INDEX IF NOT EXISTS idx_event_execution_id ON noetl.event (execution_id);
CREATE INDEX IF NOT EXISTS idx_event_catalog_id ON noetl.event (catalog_id);
CREATE INDEX IF NOT EXISTS idx_event_type ON noetl.event (event_type);
CREATE INDEX IF NOT EXISTS idx_event_status ON noetl.event (status);
CREATE INDEX IF NOT EXISTS idx_event_created_at ON noetl.event (created_at);
CREATE INDEX IF NOT EXISTS idx_event_node_name ON noetl.event (node_name);
CREATE INDEX IF NOT EXISTS idx_event_parent_event_id ON noetl.event (parent_event_id);
CREATE INDEX IF NOT EXISTS idx_event_parent_execution_id ON noetl.event (parent_execution_id);

-- Legacy compatibility view for event_log
CREATE OR REPLACE VIEW noetl.event_log AS SELECT * FROM noetl.event;

-- Credential
CREATE TABLE IF NOT EXISTS noetl.credential (
    id BIGINT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL,
    data_encrypted TEXT NOT NULL,
    schema JSONB,
    meta JSONB,
    tags TEXT[],
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_credential_type ON noetl.credential (type);
ALTER TABLE noetl.catalog ADD COLUMN IF NOT EXISTS credential_id INTEGER;

-- Runtime
CREATE TABLE IF NOT EXISTS noetl.runtime (
    runtime_id BIGINT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('worker_pool','server_api','broker')),
    uri TEXT,  -- Resource URI (endpoint for servers, resource location for workers)
    status TEXT NOT NULL,
    labels JSONB,
    capabilities JSONB,
    capacity INTEGER,
    runtime JSONB,
    heartbeat TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_runtime_kind_name ON noetl.runtime (kind, name);
CREATE INDEX IF NOT EXISTS idx_runtime_kind ON noetl.runtime (kind);
CREATE INDEX IF NOT EXISTS idx_runtime_status ON noetl.runtime (status);

-- Schedule
CREATE TABLE IF NOT EXISTS noetl.schedule (
    schedule_id BIGSERIAL PRIMARY KEY,
    playbook_path TEXT NOT NULL,
    playbook_version TEXT,
    cron TEXT,
    interval_seconds INTEGER,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    timezone TEXT DEFAULT 'UTC',
    next_run_at TIMESTAMPTZ,
    last_run_at TIMESTAMPTZ,
    last_status TEXT,
    input_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    meta JSONB
);
CREATE INDEX IF NOT EXISTS idx_schedule_next_run ON noetl.schedule (next_run_at) WHERE enabled = TRUE;
CREATE INDEX IF NOT EXISTS idx_schedule_playbook ON noetl.schedule (playbook_path);
-- Keychain
-- Stores decrypted credentials and tokens with TTL for playbook execution scope
CREATE TABLE IF NOT EXISTS noetl.keychain (
    cache_key TEXT PRIMARY KEY,
    keychain_name TEXT NOT NULL,
    catalog_id BIGINT NOT NULL REFERENCES noetl.catalog(catalog_id),
    credential_type TEXT NOT NULL,
    cache_type TEXT NOT NULL CHECK (cache_type IN ('secret', 'token')),
    scope_type TEXT NOT NULL CHECK (scope_type IN ('local', 'global', 'shared')),
    execution_id BIGINT,
    parent_execution_id BIGINT,
    data_encrypted TEXT NOT NULL,
    schema JSONB,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    accessed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    access_count INTEGER DEFAULT 0,
    auto_renew BOOLEAN DEFAULT false,
    renew_config JSONB
);

CREATE INDEX IF NOT EXISTS idx_keychain_execution ON noetl.keychain (execution_id) WHERE execution_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_keychain_parent_execution ON noetl.keychain (parent_execution_id) WHERE parent_execution_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_keychain_expires ON noetl.keychain (expires_at);
CREATE INDEX IF NOT EXISTS idx_keychain_type ON noetl.keychain (cache_type, scope_type);
CREATE INDEX IF NOT EXISTS idx_keychain_name ON noetl.keychain (keychain_name);
CREATE INDEX IF NOT EXISTS idx_keychain_catalog ON noetl.keychain (catalog_id);
CREATE INDEX IF NOT EXISTS idx_keychain_name_catalog ON noetl.keychain (keychain_name, catalog_id);

COMMENT ON TABLE noetl.keychain IS 'Caches decrypted credentials and tokens with TTL, scoped to playbook catalog. Schema field defines expected data structure for validation.';
COMMENT ON COLUMN noetl.keychain.cache_key IS 'Unique cache key: <keychain_name>:<catalog_id>:<execution_id> for local scope, <keychain_name>:<catalog_id>:global for global tokens';
COMMENT ON COLUMN noetl.keychain.keychain_name IS 'Name of the keychain entry defined in playbook (e.g., amadeus_token, postgres_creds)';
COMMENT ON COLUMN noetl.keychain.catalog_id IS 'References the playbook catalog entry that defined this keychain';
COMMENT ON COLUMN noetl.keychain.cache_type IS 'secret: raw credential data, token: derived authentication token (OAuth, JWT, etc.)';
COMMENT ON COLUMN noetl.keychain.scope_type IS 'local: limited to playbook execution and sub-playbooks, global: shared across all executions until token expires, shared: shared within execution tree';
COMMENT ON COLUMN noetl.keychain.execution_id IS 'Execution scope: credential tied to this execution and its sub-playbooks';
COMMENT ON COLUMN noetl.keychain.parent_execution_id IS 'Top-level execution ID for cleanup when parent completes';
COMMENT ON COLUMN noetl.keychain.expires_at IS 'TTL: local-scoped expires when playbook completes, global expires based on token expiration';
COMMENT ON COLUMN noetl.keychain.auto_renew IS 'If true, automatically renew token when expired using renew_config';
COMMENT ON COLUMN noetl.keychain.renew_config IS 'Configuration for automatic token renewal (endpoint, method, auth, etc.)';

-- Snowflake-like id helpers
CREATE SEQUENCE IF NOT EXISTS noetl.snowflake_seq;
CREATE OR REPLACE FUNCTION noetl.snowflake_id() RETURNS BIGINT AS $$
DECLARE
    our_epoch BIGINT := 1704067200000;
    seq_id BIGINT;
    now_ms BIGINT;
    shard_id INT := 1;
BEGIN
    SELECT nextval('noetl.snowflake_seq') % 1024 INTO seq_id;
    now_ms := (EXTRACT(EPOCH FROM clock_timestamp()) * 1000)::BIGINT;
    RETURN ((now_ms - our_epoch) << 23) |
           ((shard_id & 31) << 18) |
           (seq_id & 262143);
END;
$$ LANGUAGE plpgsql;
ALTER TABLE noetl.catalog ALTER COLUMN catalog_id SET DEFAULT noetl.snowflake_id();
ALTER TABLE noetl.schedule ALTER COLUMN schedule_id SET DEFAULT noetl.snowflake_id();
alter table noetl.credential ALTER COLUMN id SET DEFAULT noetl.snowflake_id();
