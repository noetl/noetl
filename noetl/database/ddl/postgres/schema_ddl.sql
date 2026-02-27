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

-- Event (range-partitioned by execution_id for instant per-execution cleanup)
--
-- Partition key: execution_id (snowflake bigint, epoch = 2024-01-01 UTC)
--   id = (elapsed_ms << 22) | (node_id << 12) | seq
--   IDs per quarter ≈ 33 trillion; quarterly boundaries below.
--
-- Cleanup: DROP TABLE noetl.event_<quarter> — instant, no VACUUM needed.
-- Add new partitions before each quarter starts:
--   CREATE TABLE noetl.event_2028_q1 PARTITION OF noetl.event
--     FOR VALUES FROM (595000000000000000) TO (628000000000000000);
--
-- Boundary reference (id_for_date, epoch=2024-01-01):
--   2026-01-01:  264_905_529_753_600_000
--   2026-04-01:  297_520_437_657_600_000
--   2026-07-01:  330_497_733_427_200_000
--   2026-10-01:  363_837_417_062_400_000
--   2027-01-01:  397_177_100_697_600_000
--   2027-07-01:  462_769_304_371_200_000
--   2028-01-01:  529_448_671_641_600_000
CREATE TABLE IF NOT EXISTS noetl.event (
    execution_id        BIGINT,
    catalog_id          BIGINT NOT NULL REFERENCES noetl.catalog(catalog_id),
    event_id            BIGINT,
    parent_event_id     BIGINT,
    parent_execution_id BIGINT,
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    event_type          VARCHAR,
    node_id             VARCHAR,
    node_name           VARCHAR,
    node_type           VARCHAR,
    status              VARCHAR,
    duration            DOUBLE PRECISION,
    context             JSONB,
    result              JSONB,
    meta                JSONB,
    error               TEXT,
    current_index       INTEGER,
    current_item        TEXT,
    worker_id           VARCHAR,
    distributed_state   VARCHAR,
    context_key         VARCHAR,
    context_value       TEXT,
    trace_component     JSONB,
    stack_trace         TEXT,
    PRIMARY KEY (execution_id, event_id)
) PARTITION BY RANGE (execution_id);

-- Partitions — idempotent (IF NOT EXISTS supported on partition tables in PG15)
CREATE TABLE IF NOT EXISTS noetl.event_pre_2026
    PARTITION OF noetl.event FOR VALUES FROM (MINVALUE) TO (264905529753600000);
CREATE TABLE IF NOT EXISTS noetl.event_2026_q1
    PARTITION OF noetl.event FOR VALUES FROM (264905529753600000) TO (297520437657600000);
CREATE TABLE IF NOT EXISTS noetl.event_2026_q2
    PARTITION OF noetl.event FOR VALUES FROM (297520437657600000) TO (330497733427200000);
CREATE TABLE IF NOT EXISTS noetl.event_2026_q3
    PARTITION OF noetl.event FOR VALUES FROM (330497733427200000) TO (363837417062400000);
CREATE TABLE IF NOT EXISTS noetl.event_2026_q4
    PARTITION OF noetl.event FOR VALUES FROM (363837417062400000) TO (397177100697600000);
CREATE TABLE IF NOT EXISTS noetl.event_2027_h1
    PARTITION OF noetl.event FOR VALUES FROM (397177100697600000) TO (462769304371200000);
CREATE TABLE IF NOT EXISTS noetl.event_2027_h2
    PARTITION OF noetl.event FOR VALUES FROM (462769304371200000) TO (529448671641600000);
-- GKE deployment uses a non-standard snowflake epoch producing IDs in the 569T–600T range
CREATE TABLE IF NOT EXISTS noetl.event_2026_gke
    PARTITION OF noetl.event FOR VALUES FROM (569000000000000000) TO (600000000000000000);
-- Default catches any IDs not covered by named partitions above
CREATE TABLE IF NOT EXISTS noetl.event_default
    PARTITION OF noetl.event DEFAULT;

-- Indexes on parent table — automatically inherited by all partitions
CREATE INDEX IF NOT EXISTS idx_event_execution_id          ON noetl.event (execution_id);
CREATE INDEX IF NOT EXISTS idx_event_catalog_id            ON noetl.event (catalog_id);
CREATE INDEX IF NOT EXISTS idx_event_type                  ON noetl.event (event_type);
CREATE INDEX IF NOT EXISTS idx_event_status                ON noetl.event (status);
CREATE INDEX IF NOT EXISTS idx_event_created_at            ON noetl.event (created_at);
CREATE INDEX IF NOT EXISTS idx_event_node_name             ON noetl.event (node_name);
CREATE INDEX IF NOT EXISTS idx_event_parent_event_id       ON noetl.event (parent_event_id);
CREATE INDEX IF NOT EXISTS idx_event_parent_execution_id   ON noetl.event (parent_execution_id);

-- Composite index for paginated event queries (sorted by event_id DESC for most recent first)
CREATE INDEX IF NOT EXISTS idx_event_exec_id_event_id_desc ON noetl.event (execution_id, event_id DESC);

-- Composite index for filtering by event_type within execution
CREATE INDEX IF NOT EXISTS idx_event_exec_type ON noetl.event (execution_id, event_type, event_id DESC);

-- Fast seed for /api/executions polling (latest started executions)
CREATE INDEX IF NOT EXISTS idx_event_playbook_init_event_id_desc
    ON noetl.event (event_id DESC)
    INCLUDE (execution_id, catalog_id, parent_execution_id, created_at)
    WHERE event_type = 'playbook.initialized';

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

-- ============================================================================
-- Result Storage Tables
-- ============================================================================
-- Zero-copy reference system for efficient data passing between steps.
-- Metadata index for temp storage. Actual data resides in NATS KV/Object,
-- S3/GCS, or PostgreSQL temp tables.

CREATE TABLE IF NOT EXISTS noetl.result_ref (
    ref_id BIGINT PRIMARY KEY DEFAULT noetl.snowflake_id(),
    ref TEXT UNIQUE NOT NULL,  -- noetl://execution/<eid>/result/<name>/<id>
    execution_id BIGINT NOT NULL,
    parent_execution_id BIGINT,  -- For workflow scope tracking

    -- Identification
    name TEXT NOT NULL,
    scope TEXT NOT NULL CHECK (scope IN ('step', 'execution', 'workflow', 'permanent')),
    source_step TEXT,

    -- Storage tier
    store_tier TEXT NOT NULL CHECK (store_tier IN ('memory', 'kv', 'object', 's3', 'gcs', 'db', 'duckdb', 'eventlog')),
    physical_uri TEXT,  -- Actual storage location (s3://..., gs://..., kv://bucket/key)

    -- Metadata
    content_type TEXT DEFAULT 'application/json',
    bytes_size BIGINT DEFAULT 0,
    sha256 TEXT,
    compression TEXT DEFAULT 'none' CHECK (compression IN ('none', 'gzip', 'lz4')),

    -- Lifecycle
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ,
    accessed_at TIMESTAMPTZ DEFAULT now(),
    access_count INTEGER DEFAULT 0,

    -- Preview and correlation
    preview JSONB,  -- Truncated sample for UI (max 1KB)
    extracted JSONB,  -- Fields from output.select (available without resolution)
    correlation JSONB,  -- Loop/pagination tracking keys
    meta JSONB,  -- Additional metadata

    -- Accumulation tracking
    is_accumulated BOOLEAN DEFAULT FALSE,
    accumulation_index INTEGER,
    accumulation_manifest_ref TEXT
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_result_ref_execution ON noetl.result_ref (execution_id);
CREATE INDEX IF NOT EXISTS idx_result_ref_parent ON noetl.result_ref (parent_execution_id) WHERE parent_execution_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_result_ref_scope ON noetl.result_ref (scope);
CREATE INDEX IF NOT EXISTS idx_result_ref_expires ON noetl.result_ref (expires_at) WHERE expires_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_result_ref_name_exec ON noetl.result_ref (execution_id, name);
CREATE INDEX IF NOT EXISTS idx_result_ref_step ON noetl.result_ref (execution_id, source_step) WHERE source_step IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_result_ref_store_tier ON noetl.result_ref (store_tier);

COMMENT ON TABLE noetl.result_ref IS 'ResultRef projection table - metadata index for result storage. Actual data in NATS/cloud storage.';
COMMENT ON COLUMN noetl.result_ref.ref IS 'Logical URI: noetl://execution/<eid>/result/<name>/<id>';
COMMENT ON COLUMN noetl.result_ref.scope IS 'Lifecycle scope: step (cleanup on step done), execution (cleanup on playbook done), workflow (cleanup on root done), permanent (never auto-cleaned)';
COMMENT ON COLUMN noetl.result_ref.store_tier IS 'Storage backend: memory, kv (NATS KV), object (NATS Object), s3, gcs, db (PostgreSQL), duckdb, eventlog';
COMMENT ON COLUMN noetl.result_ref.physical_uri IS 'Actual storage URI (s3://bucket/key, kv://bucket/key, etc.)';
COMMENT ON COLUMN noetl.result_ref.preview IS 'Truncated sample of data for UI preview (max 1KB JSON)';
COMMENT ON COLUMN noetl.result_ref.extracted IS 'Fields from output.select available without resolution';
COMMENT ON COLUMN noetl.result_ref.correlation IS 'Loop/pagination tracking: iteration, page, cursor, batch_id';

-- Legacy alias view for backwards compatibility
CREATE OR REPLACE VIEW noetl.temp_ref AS SELECT * FROM noetl.result_ref;

-- ============================================================================
-- Manifest Table
-- ============================================================================
-- Aggregated results for pagination and loops. Instead of merging large
-- datasets in memory, a manifest references the parts for streaming access.

CREATE TABLE IF NOT EXISTS noetl.manifest (
    manifest_id BIGINT PRIMARY KEY DEFAULT noetl.snowflake_id(),
    ref TEXT UNIQUE NOT NULL,  -- noetl://execution/<eid>/manifest/<name>/<id>
    execution_id BIGINT NOT NULL,

    -- Configuration
    strategy TEXT NOT NULL CHECK (strategy IN ('append', 'replace', 'merge', 'concat')),
    merge_path TEXT,  -- JSONPath for nested array merge (e.g., $.data.items)

    -- Statistics
    total_parts INTEGER DEFAULT 0,
    total_bytes BIGINT DEFAULT 0,

    -- Lifecycle
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,

    -- Metadata
    source_step TEXT,
    correlation JSONB,
    meta JSONB
);

CREATE INDEX IF NOT EXISTS idx_manifest_execution ON noetl.manifest (execution_id);
CREATE INDEX IF NOT EXISTS idx_manifest_step ON noetl.manifest (source_step) WHERE source_step IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_manifest_completed ON noetl.manifest (completed_at) WHERE completed_at IS NOT NULL;

COMMENT ON TABLE noetl.manifest IS 'Manifest for aggregated results from pagination/loops. References parts rather than merging.';
COMMENT ON COLUMN noetl.manifest.ref IS 'Logical URI: noetl://execution/<eid>/manifest/<name>/<id>';
COMMENT ON COLUMN noetl.manifest.strategy IS 'Combination strategy: append (list), replace (overwrite), merge (deep merge), concat (flatten arrays)';
COMMENT ON COLUMN noetl.manifest.merge_path IS 'JSONPath for nested array extraction in concat strategy';

-- ============================================================================
-- Manifest Parts Table
-- ============================================================================
-- Individual parts referenced by a manifest

CREATE TABLE IF NOT EXISTS noetl.manifest_part (
    manifest_id BIGINT NOT NULL REFERENCES noetl.manifest(manifest_id) ON DELETE CASCADE,
    part_index INTEGER NOT NULL,
    part_ref TEXT NOT NULL,  -- ResultRef URI
    bytes_size BIGINT DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    meta JSONB,
    PRIMARY KEY (manifest_id, part_index)
);

CREATE INDEX IF NOT EXISTS idx_manifest_part_ref ON noetl.manifest_part (part_ref);

COMMENT ON TABLE noetl.manifest_part IS 'Individual parts of a manifest, ordered by part_index';
COMMENT ON COLUMN noetl.manifest_part.part_ref IS 'Reference to part data (ResultRef URI or inline)';

-- ============================================================================
-- Extend transient table for ResultRef integration
-- ============================================================================
-- Add scope and expires_at columns if not present

DO $$ BEGIN
    ALTER TABLE noetl.transient ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE noetl.transient ADD COLUMN IF NOT EXISTS scope TEXT DEFAULT 'execution' CHECK (scope IN ('step', 'execution', 'workflow', 'permanent'));
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

-- Index for TTL-based cleanup
CREATE INDEX IF NOT EXISTS idx_transient_expires ON noetl.transient (expires_at) WHERE expires_at IS NOT NULL;

-- ============================================================================
-- Cleanup function for expired ResultRefs
-- ============================================================================
CREATE OR REPLACE FUNCTION noetl.cleanup_expired_result_refs()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    -- Delete expired result_refs (permanent scope never expires via TTL)
    WITH deleted AS (
        DELETE FROM noetl.result_ref
        WHERE expires_at IS NOT NULL AND expires_at < NOW()
          AND scope != 'permanent'
        RETURNING ref_id
    )
    SELECT COUNT(*) INTO deleted_count FROM deleted;

    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION noetl.cleanup_expired_result_refs() IS 'Clean up expired ResultRefs. Call periodically or via pg_cron.';

-- ============================================================================
-- Cleanup function for execution-scoped refs
-- ============================================================================
CREATE OR REPLACE FUNCTION noetl.cleanup_execution_result_refs(p_execution_id BIGINT)
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    -- Delete execution-scoped result_refs (not permanent)
    WITH deleted AS (
        DELETE FROM noetl.result_ref
        WHERE execution_id = p_execution_id
          AND scope IN ('step', 'execution')
        RETURNING ref_id
    )
    SELECT COUNT(*) INTO deleted_count FROM deleted;

    -- Delete manifests for this execution
    DELETE FROM noetl.manifest WHERE execution_id = p_execution_id;

    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION noetl.cleanup_execution_result_refs(BIGINT) IS 'Clean up all result refs for a completed execution (excludes permanent scope).';
