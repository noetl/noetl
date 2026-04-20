-- =====================================================================
-- Migrate noetl.command from non-partitioned to HASH-partitioned by execution_id
-- =====================================================================
--
-- Aligns the command table with the planned hash-partitioning of noetl.event
-- so that:
--
--   1. Per-execution queries (`WHERE execution_id = X`) prune to ONE partition
--      instead of scanning the whole table. Today's `noetl.command` has 36k+
--      rows in a flat table and 38k+ sequential scans on it (~1 seq scan per
--      query). Partitioning collapses that to ~3% of the data per query.
--
--   2. Cross-table joins (`event JOIN command USING (execution_id)`) are
--      partition-wise once `noetl.event` is also hash-partitioned by
--      execution_id with the same modulus — Postgres ≥ 11 will do
--      partition-by-partition joins and skip 15/16 of the data.
--
--   3. Insert distribution: snowflake execution_id values hash uniformly
--      across the 16 partitions, balancing write contention and HOT update
--      pressure across separate b-tree pages.
--
-- Tradeoffs accepted:
--   - PRIMARY KEY changes from `(command_id)` to `(execution_id, command_id)`
--     because Postgres requires the partition key to participate in any UNIQUE
--     constraint on a partitioned table. command_id is already constructed
--     application-side as `<execution_id>:<step_name>:<seq>` so the composite
--     PK preserves the de-facto uniqueness contract.
--   - Retention by partition DROP is not available with hash partitioning.
--     Use `DELETE FROM noetl.command WHERE execution_id IN (SELECT execution_id
--     FROM noetl.execution WHERE end_time < now() - interval '30 days')`.
--
-- Run as the table owner (typically `demo`):
--   psql -U demo -d noetl -f migrate_command_to_hash_partitioned.sql
--
-- This script is idempotent: if `noetl.command` is already partitioned
-- (PARTITION BY HASH visible in pg_partitioned_table), it exits early.
-- =====================================================================

\set ON_ERROR_STOP on

BEGIN;

-- Idempotency guard: bail out if already partitioned.
DO $migrate$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_partitioned_table pt
        JOIN pg_class c ON c.oid = pt.partrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'noetl' AND c.relname = 'command'
    ) THEN
        RAISE NOTICE 'noetl.command is already partitioned; skipping migration';
        RETURN;
    END IF;

    RAISE NOTICE 'Migrating noetl.command to HASH partitioning by execution_id (16 partitions)';

    -- 1. Move the existing flat table out of the way. Indexes follow the
    --    rename, so we also drop them — they would otherwise collide with
    --    the new index names below. The legacy table's data is preserved
    --    until the explicit DROP TABLE at the end.
    EXECUTE 'ALTER TABLE noetl.command RENAME TO command_legacy_pre_hashpart';
    EXECUTE 'DROP INDEX IF EXISTS noetl.idx_command_execution_id';
    EXECUTE 'DROP INDEX IF EXISTS noetl.idx_command_execution_step';
    EXECUTE 'DROP INDEX IF EXISTS noetl.idx_command_loop';
    EXECUTE 'DROP INDEX IF EXISTS noetl.idx_command_status';
    EXECUTE 'DROP INDEX IF EXISTS noetl.idx_command_worker';
    EXECUTE 'DROP INDEX IF EXISTS noetl.idx_command_command_id';

    -- 2. Create the new partitioned parent. We define columns explicitly
    --    rather than using LIKE so PRIMARY KEY can be set inline (LIKE
    --    INCLUDING CONSTRAINTS rejects PARTITION BY).
    EXECUTE $sql$
        CREATE TABLE noetl.command (
            command_id          TEXT NOT NULL,
            event_id            BIGINT NOT NULL,
            execution_id        BIGINT NOT NULL,
            catalog_id          BIGINT NOT NULL,
            parent_execution_id BIGINT,
            parent_command_id   TEXT,

            step_name           TEXT NOT NULL,
            tool_kind           TEXT,

            status              TEXT NOT NULL DEFAULT 'PENDING',
            worker_id           TEXT,
            claimed_at          TIMESTAMPTZ,
            started_at          TIMESTAMPTZ,
            completed_at        TIMESTAMPTZ,
            attempt             INT NOT NULL DEFAULT 1,

            context             JSONB,
            context_key         TEXT,

            loop_event_id       TEXT,
            iter_index          INT,
            meta                JSONB,

            result              JSONB,
            error               TEXT,

            latest_event_id     BIGINT,

            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

            PRIMARY KEY (execution_id, command_id)
        ) PARTITION BY HASH (execution_id)
    $sql$;

    -- 3. Create 16 hash partitions.
    FOR i IN 0..15 LOOP
        EXECUTE format(
            'CREATE TABLE noetl.command_p%s PARTITION OF noetl.command FOR VALUES WITH (MODULUS 16, REMAINDER %s)',
            lpad(i::text, 2, '0'), i
        );
    END LOOP;

    -- 4. Recreate non-PK indexes on the partitioned parent. Postgres
    --    auto-propagates these to all 16 partitions and to any future ones.
    EXECUTE 'CREATE INDEX idx_command_execution_id ON noetl.command (execution_id)';
    EXECUTE 'CREATE INDEX idx_command_execution_step ON noetl.command (execution_id, step_name)';
    EXECUTE 'CREATE INDEX idx_command_loop ON noetl.command (execution_id, loop_event_id, status) WHERE loop_event_id IS NOT NULL';
    EXECUTE $sql$ CREATE INDEX idx_command_status ON noetl.command (status) WHERE status = ANY (ARRAY['PENDING'::text, 'CLAIMED'::text]) $sql$;
    EXECUTE $sql$ CREATE INDEX idx_command_worker ON noetl.command (worker_id, updated_at) WHERE status = 'CLAIMED'::text $sql$;

    -- 5. Optional: secondary lookup by command_id alone. A partitioned
    --    UNIQUE on just command_id is not allowed (Postgres requires the
    --    partition key in any UNIQUE), so we use a NON-UNIQUE index that
    --    still gives O(log n) lookups when a caller has only command_id.
    EXECUTE 'CREATE INDEX idx_command_command_id ON noetl.command (command_id)';

    -- 6. Copy data. Insert order doesn't matter; hash partitioning routes
    --    by execution_id automatically.
    EXECUTE 'INSERT INTO noetl.command SELECT * FROM noetl.command_legacy_pre_hashpart';

    -- 7. Drop the legacy table.
    EXECUTE 'DROP TABLE noetl.command_legacy_pre_hashpart';

    RAISE NOTICE 'noetl.command migration complete: 16 hash partitions';
END
$migrate$;

COMMIT;

-- Verification
\echo
\echo '=== Partition layout ==='
SELECT inhrelid::regclass AS partition,
       pg_size_pretty(pg_relation_size(inhrelid)) AS size,
       pg_stat_get_live_tuples(inhrelid) AS rows
FROM pg_inherits
WHERE inhparent = 'noetl.command'::regclass
ORDER BY inhrelid::regclass::text;

\echo
\echo '=== Indexes on partitioned parent (auto-propagated) ==='
\d+ noetl.command
