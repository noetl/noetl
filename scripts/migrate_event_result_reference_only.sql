-- One-time migration for reference-only event.result contract.
-- Run during a maintenance window on existing installations.

-- 1) Add the result-shape constraint when missing.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_namespace n ON n.oid = c.connamespace
        JOIN pg_class t ON t.oid = c.conrelid
        WHERE c.conname = 'chk_event_result_shape'
          AND n.nspname = 'noetl'
          AND t.relname = 'event'
    ) THEN
        ALTER TABLE noetl.event
            ADD CONSTRAINT chk_event_result_shape
                CHECK (
                    result IS NULL
                    OR (
                        jsonb_typeof(result) = 'object'
                        AND result ? 'status'
                        AND jsonb_typeof(result->'status') = 'string'
                        AND (result - 'status' - 'reference' - 'context') = '{}'::jsonb
                        AND (NOT (result ? 'reference') OR jsonb_typeof(result->'reference') = 'object')
                        AND (NOT (result ? 'context') OR jsonb_typeof(result->'context') = 'object')
                    )
                ) NOT VALID;
    END IF;
END;
$$;

-- Optional strict validation of existing rows (may take time on large event tables):
-- ALTER TABLE noetl.event VALIDATE CONSTRAINT chk_event_result_shape;

-- 2) Drop legacy inline result index now obsolete under reference-only contract.
DROP INDEX IF EXISTS noetl.idx_event_exec_type_result_command_id_event_id_desc;

-- 3) Add reaper fast-path index for recent command.issued scans.
CREATE INDEX IF NOT EXISTS idx_event_command_issued_created_event_id_desc
    ON noetl.event (created_at DESC, event_id DESC, execution_id, ((meta->>'command_id')))
    WHERE event_type = 'command.issued' AND meta ? 'command_id';
