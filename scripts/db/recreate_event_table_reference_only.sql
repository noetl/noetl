-- Recreate noetl.event with reference-only result contract
-- WARNING: Destructive operation. Drops noetl.event and all partitions/data.

BEGIN;

DROP VIEW IF EXISTS noetl.event_log;
DROP TABLE IF EXISTS noetl.event CASCADE;

CREATE TABLE noetl.event (
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
    CONSTRAINT chk_event_result_shape
        CHECK (
            result IS NULL
            OR (
                jsonb_typeof(result) = 'object'
                AND result ? 'status'
                AND (result - 'status' - 'reference' - 'context') = '{}'::jsonb
                AND (NOT (result ? 'reference') OR jsonb_typeof(result->'reference') = 'object')
                AND (NOT (result ? 'context') OR jsonb_typeof(result->'context') = 'object')
            )
        ),
    PRIMARY KEY (execution_id, event_id)
) PARTITION BY RANGE (execution_id);

CREATE TABLE noetl.event_pre_2026
    PARTITION OF noetl.event FOR VALUES FROM (MINVALUE) TO (264905529753600000);
CREATE TABLE noetl.event_2026_q1
    PARTITION OF noetl.event FOR VALUES FROM (264905529753600000) TO (297520437657600000);
CREATE TABLE noetl.event_2026_q2
    PARTITION OF noetl.event FOR VALUES FROM (297520437657600000) TO (330497733427200000);
CREATE TABLE noetl.event_2026_q3
    PARTITION OF noetl.event FOR VALUES FROM (330497733427200000) TO (363837417062400000);
CREATE TABLE noetl.event_2026_q4
    PARTITION OF noetl.event FOR VALUES FROM (363837417062400000) TO (397177100697600000);
CREATE TABLE noetl.event_2027_h1
    PARTITION OF noetl.event FOR VALUES FROM (397177100697600000) TO (462769304371200000);
CREATE TABLE noetl.event_2027_h2
    PARTITION OF noetl.event FOR VALUES FROM (462769304371200000) TO (529448671641600000);
CREATE TABLE noetl.event_2026_gke
    PARTITION OF noetl.event FOR VALUES FROM (569000000000000000) TO (600000000000000000);
CREATE TABLE noetl.event_default
    PARTITION OF noetl.event DEFAULT;

CREATE INDEX idx_event_execution_id          ON noetl.event (execution_id);
CREATE INDEX idx_event_catalog_id            ON noetl.event (catalog_id);
CREATE INDEX idx_event_type                  ON noetl.event (event_type);
CREATE INDEX idx_event_status                ON noetl.event (status);
CREATE INDEX idx_event_created_at            ON noetl.event (created_at);
CREATE INDEX idx_event_node_name             ON noetl.event (node_name);
CREATE INDEX idx_event_parent_event_id       ON noetl.event (parent_event_id);
CREATE INDEX idx_event_parent_execution_id   ON noetl.event (parent_execution_id);
CREATE INDEX idx_event_exec_id_event_id_desc ON noetl.event (execution_id, event_id DESC);
CREATE INDEX idx_event_exec_type             ON noetl.event (execution_id, event_type, event_id DESC);

CREATE INDEX idx_event_exec_type_meta_command_id_event_id_desc
    ON noetl.event (execution_id, event_type, ((meta->>'command_id')), event_id DESC)
    WHERE meta ? 'command_id';

CREATE INDEX idx_event_command_issued_created_event_id_desc
    ON noetl.event (created_at DESC, event_id DESC, execution_id, ((meta->>'command_id')))
    WHERE event_type = 'command.issued' AND meta ? 'command_id';

CREATE INDEX idx_event_result_reference_type
    ON noetl.event (((result->'reference'->>'type')))
    WHERE result ? 'reference';

CREATE INDEX idx_event_result_reference_record_id
    ON noetl.event (((result->'reference'->>'record_id')))
    WHERE (result->'reference') ? 'record_id';

CREATE INDEX idx_event_batch_request_event_id_desc
    ON noetl.event (((meta->>'batch_request_id')), event_id DESC)
    WHERE meta ? 'batch_request_id';

CREATE INDEX idx_event_playbook_init_event_id_desc
    ON noetl.event (event_id DESC)
    INCLUDE (execution_id, catalog_id, parent_execution_id, created_at)
    WHERE event_type = 'playbook.initialized';

CREATE OR REPLACE VIEW noetl.event_log AS SELECT * FROM noetl.event;

COMMIT;
