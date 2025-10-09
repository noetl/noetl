-- Canonical Schema DDL for NoETL (single source of truth)

CREATE SCHEMA IF NOT EXISTS noetl;
ALTER SCHEMA noetl OWNER TO noetl;
ALTER DEFAULT PRIVILEGES IN SCHEMA noetl GRANT ALL ON TABLES TO noetl;
ALTER DEFAULT PRIVILEGES IN SCHEMA noetl GRANT ALL ON SEQUENCES TO noetl;

-- Optional: create plpython3u if available (ignore errors if not present)
-- DO $$ BEGIN
--     CREATE EXTENSION IF NOT EXISTS plpython3u;
-- EXCEPTION WHEN others THEN NULL; END $$;

-- Resource
CREATE TABLE IF NOT EXISTS noetl.resource (
    name VARCHAR PRIMARY KEY,
    meta JSONB
);
ALTER TABLE noetl.resource OWNER TO noetl;

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
ALTER TABLE noetl.catalog OWNER TO noetl;

-- Workload
CREATE TABLE IF NOT EXISTS noetl.workload (
    execution_id BIGINT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    data JSONB,
    PRIMARY KEY (execution_id)
);
ALTER TABLE noetl.workload OWNER TO noetl;

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
    context TEXT,
    result TEXT,
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
ALTER TABLE noetl.event OWNER TO noetl;
ALTER TABLE noetl.event ADD COLUMN IF NOT EXISTS trace_component JSONB;
ALTER TABLE noetl.event ADD COLUMN IF NOT EXISTS parent_execution_id BIGINT;
ALTER TABLE noetl.event ADD COLUMN IF NOT EXISTS stack_trace TEXT;
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

-- Workflow/workbook/transition
CREATE TABLE IF NOT EXISTS noetl.workflow (
    execution_id BIGINT,
    step_id VARCHAR,
    step_name VARCHAR,
    step_type VARCHAR,
    description TEXT,
    raw_config TEXT,
    PRIMARY KEY (execution_id, step_id)
);
ALTER TABLE noetl.workflow OWNER TO noetl;

CREATE TABLE IF NOT EXISTS noetl.workbook (
    execution_id BIGINT,
    task_id VARCHAR,
    task_name VARCHAR,
    task_type VARCHAR,
    raw_config TEXT,
    PRIMARY KEY (execution_id, task_id)
);
ALTER TABLE noetl.workbook OWNER TO noetl;

CREATE TABLE IF NOT EXISTS noetl.transition (
    execution_id BIGINT,
    from_step VARCHAR,
    to_step VARCHAR,
    condition TEXT,
    with_params TEXT,
    PRIMARY KEY (execution_id, from_step, to_step, condition)
);
ALTER TABLE noetl.transition OWNER TO noetl;

-- Legacy compatibility view for event_log
CREATE OR REPLACE VIEW noetl.event_log AS SELECT * FROM noetl.event;

-- Credential
CREATE TABLE IF NOT EXISTS noetl.credential (
    id BIGINT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL,
    data_encrypted TEXT NOT NULL,
    meta JSONB,
    tags TEXT[],
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE noetl.credential OWNER TO noetl;
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
ALTER TABLE noetl.runtime OWNER TO noetl;
CREATE UNIQUE INDEX IF NOT EXISTS idx_runtime_kind_name ON noetl.runtime (kind, name);
CREATE INDEX IF NOT EXISTS idx_runtime_kind ON noetl.runtime (kind);
CREATE INDEX IF NOT EXISTS idx_runtime_status ON noetl.runtime (status);
CREATE INDEX IF NOT EXISTS idx_runtime_runtime_type ON noetl.runtime ((runtime->>'type'));

CREATE TABLE IF NOT EXISTS noetl.metric (
    metric_id BIGINT,
    runtime_id BIGINT NOT NULL REFERENCES noetl.runtime(runtime_id) ON DELETE CASCADE,
    metric_name TEXT NOT NULL,
    metric_type TEXT NOT NULL CHECK (metric_type IN ('counter', 'gauge', 'histogram', 'summary')),
    metric_value DOUBLE PRECISION NOT NULL,
    labels JSONB,
    help_text TEXT,
    unit TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- TTL: automatically delete metrics older than 1 day
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (now() + INTERVAL '1 day'),
    PRIMARY KEY (metric_id, created_at)
) PARTITION BY RANGE (created_at);
ALTER TABLE noetl.metric OWNER TO noetl;

-- Create indexes on the parent table (will be inherited by partitions)
CREATE INDEX IF NOT EXISTS idx_metric_runtime_id ON noetl.metric (runtime_id);
CREATE INDEX IF NOT EXISTS idx_metric_name ON noetl.metric (metric_name);
CREATE INDEX IF NOT EXISTS idx_metric_created_at ON noetl.metric (created_at);
CREATE INDEX IF NOT EXISTS idx_metric_runtime_name ON noetl.metric (runtime_id, metric_name);
CREATE INDEX IF NOT EXISTS idx_metric_labels ON noetl.metric USING GIN (labels);

-- Function to create daily partitions for metrics
CREATE OR REPLACE FUNCTION noetl.create_metric_partition(partition_date DATE)
RETURNS TEXT AS $$
DECLARE
    partition_name TEXT;
    start_date DATE;
    end_date DATE;
BEGIN
    partition_name := 'metric_' || to_char(partition_date, 'YYYY_MM_DD');
    start_date := partition_date;
    end_date := partition_date + INTERVAL '1 day';
    
    EXECUTE format('CREATE TABLE IF NOT EXISTS noetl.%I PARTITION OF noetl.metric
                    FOR VALUES FROM (%L) TO (%L)',
                   partition_name, start_date, end_date);
    
    -- Set ownership
    EXECUTE format('ALTER TABLE noetl.%I OWNER TO noetl', partition_name);
    
    RETURN partition_name;
END;
$$ LANGUAGE plpgsql;

-- Function to create partitions for the next N days
CREATE OR REPLACE FUNCTION noetl.create_metric_partitions_ahead(days_ahead INTEGER DEFAULT 7)
RETURNS TEXT[] AS $$
DECLARE
    partition_names TEXT[] := '{}';
    current_date_iter DATE;
    partition_name TEXT;
BEGIN
    -- Create partitions for today and the next N days
    FOR i IN 0..days_ahead LOOP
        current_date_iter := CURRENT_DATE + (i || ' days')::INTERVAL;
        partition_name := noetl.create_metric_partition(current_date_iter);
        partition_names := partition_names || partition_name;
    END LOOP;
    
    RETURN partition_names;
END;
$$ LANGUAGE plpgsql;

-- TTL cleanup function for metrics (drops expired partitions)
CREATE OR REPLACE FUNCTION noetl.cleanup_expired_metrics()
RETURNS TEXT[] AS $$
DECLARE
    dropped_partitions TEXT[] := '{}';
    partition_record RECORD;
    cutoff_date DATE;
BEGIN
    -- Calculate cutoff date (1 day ago)
    cutoff_date := CURRENT_DATE - INTERVAL '1 day';
    
    -- Find and drop expired partitions
    FOR partition_record IN
        SELECT schemaname, tablename 
        FROM pg_tables 
        WHERE schemaname = 'noetl' 
          AND tablename LIKE 'metric_%'
          AND tablename ~ '^metric_\d{4}_\d{2}_\d{2}$'
    LOOP
        -- Extract date from partition name (format: metric_YYYY_MM_DD)
        DECLARE
            partition_date_str TEXT;
            partition_date DATE;
        BEGIN
            partition_date_str := substring(partition_record.tablename from 8);
            partition_date_str := replace(partition_date_str, '_', '-');
            partition_date := partition_date_str::DATE;
            
            -- Drop if older than cutoff
            IF partition_date < cutoff_date THEN
                EXECUTE format('DROP TABLE IF EXISTS noetl.%I', partition_record.tablename);
                dropped_partitions := dropped_partitions || partition_record.tablename;
            END IF;
        EXCEPTION
            WHEN OTHERS THEN
                -- Skip invalid partition names
                CONTINUE;
        END;
    END LOOP;
    
    RETURN dropped_partitions;
END;
$$ LANGUAGE plpgsql;

-- Function to set custom TTL for specific metrics (updates expires_at)
CREATE OR REPLACE FUNCTION noetl.set_metric_ttl(
    p_metric_name TEXT,
    p_ttl_interval INTERVAL DEFAULT INTERVAL '1 day'
)
RETURNS INTEGER AS $$
DECLARE
    updated_count INTEGER;
BEGIN
    UPDATE noetl.metric 
    SET expires_at = now() + p_ttl_interval 
    WHERE metric_name = p_metric_name 
      AND expires_at > now();  -- Only update non-expired metrics
    
    GET DIAGNOSTICS updated_count = ROW_COUNT;
    RETURN updated_count;
END;
$$ LANGUAGE plpgsql;

-- Function to extend TTL for all metrics of a specific component (updates expires_at)
CREATE OR REPLACE FUNCTION noetl.extend_component_metrics_ttl(
    p_component_name TEXT,
    p_ttl_interval INTERVAL DEFAULT INTERVAL '1 day'
)
RETURNS INTEGER AS $$
DECLARE
    updated_count INTEGER;
BEGIN
    UPDATE noetl.metric 
    SET expires_at = now() + p_ttl_interval 
    WHERE runtime_id IN (
        SELECT runtime_id FROM noetl.runtime WHERE name = p_component_name
    )
    AND expires_at > now();  -- Only update non-expired metrics
    
    GET DIAGNOSTICS updated_count = ROW_COUNT;
    RETURN updated_count;
END;
$$ LANGUAGE plpgsql;

-- Function to initialize metric partitions (call this after schema creation)
CREATE OR REPLACE FUNCTION noetl.initialize_metric_partitions()
RETURNS TEXT[] AS $$
DECLARE
    partition_names TEXT[];
    yesterday_partition TEXT;
BEGIN
    -- Create partitions for today and next 7 days
    SELECT noetl.create_metric_partitions_ahead(8) INTO partition_names;
    
    -- Also create yesterday's partition to handle any late-arriving data
    SELECT noetl.create_metric_partition((CURRENT_DATE - INTERVAL '1 day')::DATE) INTO yesterday_partition;
    partition_names := partition_names || yesterday_partition;
    
    RETURN partition_names;
END;
$$ LANGUAGE plpgsql;

-- Queue
CREATE TABLE IF NOT EXISTS noetl.queue (
    queue_id BIGINT PRIMARY KEY,
    execution_id BIGINT NOT NULL,
    catalog_id BIGINT NOT NULL REFERENCES noetl.catalog(catalog_id),
    node_id VARCHAR NOT NULL,
    action TEXT NOT NULL,
    context JSONB,
    status TEXT NOT NULL DEFAULT 'queued',
    priority INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    available_at TIMESTAMPTZ,
    lease_until TIMESTAMPTZ,
    worker_id TEXT,
    last_heartbeat TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    parent_execution_id BIGINT,
    parent_event_id BIGINT,
    event_id BIGINT,
    node_name VARCHAR,
    node_type VARCHAR,
    UNIQUE(execution_id, node_id)
);
ALTER TABLE noetl.queue OWNER TO noetl;

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
ALTER TABLE noetl.schedule OWNER TO noetl;
CREATE INDEX IF NOT EXISTS idx_schedule_next_run ON noetl.schedule (next_run_at) WHERE enabled = TRUE;
CREATE INDEX IF NOT EXISTS idx_schedule_playbook ON noetl.schedule (playbook_path);

-- Identity & collaboration tables
CREATE TABLE IF NOT EXISTS noetl.role (
    id BIGINT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT
);
ALTER TABLE noetl.role OWNER TO noetl;

CREATE TABLE IF NOT EXISTS noetl.profile (
    id BIGINT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE,
    password_hash TEXT,
    role_id BIGINT REFERENCES noetl.role(id),
    type TEXT NOT NULL CHECK (type IN ('user','bot')),
    created_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE noetl.profile OWNER TO noetl;

CREATE TABLE IF NOT EXISTS noetl.session (
    id BIGINT PRIMARY KEY,
    profile_id BIGINT REFERENCES noetl.profile(id),
    session_type TEXT NOT NULL CHECK (session_type IN ('user','bot','ai')),
    connected_at TIMESTAMPTZ DEFAULT now(),
    disconnected_at TIMESTAMPTZ,
    meta JSONB
);
ALTER TABLE noetl.session OWNER TO noetl;

-- Dentry-based hierarchy replacing label/attachment
CREATE TABLE IF NOT EXISTS noetl.dentry (
    id BIGINT PRIMARY KEY,
    parent_id BIGINT REFERENCES noetl.dentry(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('folder')),
    meta JSONB,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(parent_id, name)
);
ALTER TABLE noetl.dentry OWNER TO noetl;




-- Indexes for dentry and messages
CREATE INDEX IF NOT EXISTS idx_dentry_parent ON noetl.dentry(parent_id);
CREATE INDEX IF NOT EXISTS idx_dentry_kind ON noetl.dentry(kind);

-- Snowflake-like id helpers
CREATE SEQUENCE IF NOT EXISTS noetl.snowflake_seq;
ALTER SEQUENCE noetl.snowflake_seq OWNER TO noetl;
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
ALTER FUNCTION noetl.snowflake_id() OWNER TO noetl;
ALTER TABLE noetl.role ALTER COLUMN id SET DEFAULT noetl.snowflake_id();
ALTER TABLE noetl.catalog ALTER COLUMN catalog_id SET DEFAULT noetl.snowflake_id();
ALTER TABLE noetl.profile ALTER COLUMN id SET DEFAULT noetl.snowflake_id();
ALTER TABLE noetl.session ALTER COLUMN id SET DEFAULT noetl.snowflake_id();
ALTER TABLE noetl.dentry ALTER COLUMN id SET DEFAULT noetl.snowflake_id();
ALTER TABLE noetl.queue ALTER COLUMN queue_id SET DEFAULT noetl.snowflake_id();
ALTER TABLE noetl.schedule ALTER COLUMN schedule_id SET DEFAULT noetl.snowflake_id();
alter table noetl.credential ALTER COLUMN id SET DEFAULT noetl.snowflake_id();
alter table noetl.metric ALTER COLUMN metric_id SET DEFAULT noetl.snowflake_id();
alter table noetl.metric ALTER COLUMN runtime_id SET DEFAULT noetl.snowflake_id();

-- Seed sample roles (ids via function)
INSERT INTO noetl.role(id, name, description) VALUES (noetl.snowflake_id(), 'admin', 'Administrator') ON CONFLICT (name) DO NOTHING;
INSERT INTO noetl.role(id, name, description) VALUES (noetl.snowflake_id(), 'user', 'Standard user') ON CONFLICT (name) DO NOTHING;
INSERT INTO noetl.role(id, name, description) VALUES (noetl.snowflake_id(), 'bot', 'Automation bot') ON CONFLICT (name) DO NOTHING;
