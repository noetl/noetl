CREATE TABLE IF NOT EXISTS noetl.execution (
    execution_id          BIGINT PRIMARY KEY,
    catalog_id            BIGINT NOT NULL REFERENCES noetl.catalog(catalog_id),
    parent_execution_id   BIGINT,
    status                VARCHAR NOT NULL,
    last_event_type       VARCHAR,
    last_node_name        VARCHAR,
    last_event_id         BIGINT,
    start_time            TIMESTAMP WITH TIME ZONE,
    end_time              TIMESTAMP WITH TIME ZONE,
    error                 TEXT,
    created_at            TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_execution_status ON noetl.execution (status);
CREATE INDEX IF NOT EXISTS idx_execution_catalog_id ON noetl.execution (catalog_id);
CREATE INDEX IF NOT EXISTS idx_execution_start_time ON noetl.execution (start_time DESC);
-- Execution projection is maintained by application-side projection/state code.
-- Remove the legacy trigger during migrations so recovery/bootstrap flows do not
-- recreate the hot row-locking path on noetl.execution.
DROP TRIGGER IF EXISTS trg_event_to_execution ON noetl.event;
DROP FUNCTION IF EXISTS noetl.trg_execution_state_upsert();
