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

CREATE OR REPLACE FUNCTION noetl.trg_execution_state_upsert()
RETURNS TRIGGER AS $$
DECLARE
    new_status VARCHAR;
    is_terminal BOOLEAN := FALSE;
BEGIN
    -- Determine the overall execution status from the event
    -- By default, it's RUNNING unless it's a terminal event.
    IF NEW.event_type IN ('playbook.completed', 'workflow.completed') THEN
        new_status := 'COMPLETED';
        is_terminal := TRUE;
    ELSIF NEW.event_type IN ('playbook.failed', 'workflow.failed', 'command.failed') THEN
        new_status := 'FAILED';
        is_terminal := TRUE;
    ELSIF NEW.event_type = 'execution.cancelled' THEN
        new_status := 'CANCELLED';
        is_terminal := TRUE;
    ELSE
        new_status := 'RUNNING';
    END IF;

    INSERT INTO noetl.execution (
        execution_id, catalog_id, parent_execution_id, status, last_event_type, last_node_name,
        last_event_id, start_time, end_time, error, created_at, updated_at
    )
    VALUES (
        NEW.execution_id, 
        NEW.catalog_id, 
        NEW.parent_execution_id,
        new_status,
        NEW.event_type,
        NEW.node_name,
        NEW.event_id,
        CASE WHEN NEW.event_type IN ('playbook.initialized', 'workflow.initialized') THEN NEW.created_at ELSE NULL END,
        CASE WHEN is_terminal THEN NEW.created_at ELSE NULL END,
        NEW.error,
        NEW.created_at, 
        NEW.created_at
    )
    ON CONFLICT (execution_id) DO UPDATE SET
        catalog_id = EXCLUDED.catalog_id,
        parent_execution_id = COALESCE(EXCLUDED.parent_execution_id, noetl.execution.parent_execution_id),
        -- Do not downgrade a terminal status back to RUNNING. 
        status = CASE 
            WHEN noetl.execution.status IN ('COMPLETED', 'FAILED', 'CANCELLED') THEN noetl.execution.status 
            ELSE EXCLUDED.status 
        END,
        last_event_type = CASE WHEN NEW.event_id >= COALESCE(noetl.execution.last_event_id, 0) THEN EXCLUDED.last_event_type ELSE noetl.execution.last_event_type END,
        last_node_name = CASE WHEN NEW.event_id >= COALESCE(noetl.execution.last_event_id, 0) THEN EXCLUDED.last_node_name ELSE noetl.execution.last_node_name END,
        last_event_id = GREATEST(noetl.execution.last_event_id, EXCLUDED.last_event_id),
        start_time = COALESCE(noetl.execution.start_time, EXCLUDED.start_time),
        end_time = CASE 
            WHEN is_terminal THEN COALESCE(noetl.execution.end_time, EXCLUDED.end_time)
            ELSE noetl.execution.end_time
        END,
        error = CASE WHEN NEW.error IS NOT NULL THEN NEW.error ELSE noetl.execution.error END,
        updated_at = EXCLUDED.updated_at;
        
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_event_to_execution ON noetl.event;
CREATE TRIGGER trg_event_to_execution
AFTER INSERT ON noetl.event
FOR EACH ROW
EXECUTE FUNCTION noetl.trg_execution_state_upsert();
