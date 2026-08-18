-- noetl/ai-meta#155 -- add the missing `noetl.command (event_id)` index ONLINE.
--
-- WHY
--   `POST /api/commands/{event_id}/claim` resolves a command from the bus
--   notification by `event_id` alone; it has no `execution_id` to give.
--   `noetl.command` is HASH-partitioned on `execution_id` and every existing
--   index leads with that column, so the predicate is unservable and the
--   planner does a parallel seq scan of all 16 partitions.  Measured on a
--   428,585-row table: 88,199 buffers (74,241 read) and ~295ms per claim,
--   paid twice per playbook hop -- ~79% of a turn's wall clock.
--
-- WHY NOT JUST `CREATE INDEX`
--   A plain CREATE INDEX on the parent takes ACCESS EXCLUSIVE on every
--   partition and blocks all command writes for the duration -- i.e. it stops
--   dispatch.  PostgreSQL does not accept CREATE INDEX CONCURRENTLY on a
--   partitioned parent, so the online form is: build each partition's index
--   concurrently, create an INVALID parent index with ONLY, then attach.  The
--   parent index flips to valid automatically once all 16 are attached.
--
-- SAFETY
--   Purely additive; changes no query results, only plans.  Reversible at any
--   point with `DROP INDEX CONCURRENTLY noetl.idx_command_event_id;` (dropping
--   the parent cascades to the attached partition indexes).  Cost afterwards
--   is one more btree to maintain on insert into noetl.command.
--
-- RUN
--   Each statement separately (CONCURRENTLY cannot run inside a transaction
--   block).  psql -f runs them autocommit, which is what we want; do NOT wrap
--   this file in BEGIN/COMMIT.

CREATE INDEX CONCURRENTLY IF NOT EXISTS command_p00_event_id_idx ON noetl.command_p00 (event_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS command_p01_event_id_idx ON noetl.command_p01 (event_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS command_p02_event_id_idx ON noetl.command_p02 (event_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS command_p03_event_id_idx ON noetl.command_p03 (event_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS command_p04_event_id_idx ON noetl.command_p04 (event_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS command_p05_event_id_idx ON noetl.command_p05 (event_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS command_p06_event_id_idx ON noetl.command_p06 (event_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS command_p07_event_id_idx ON noetl.command_p07 (event_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS command_p08_event_id_idx ON noetl.command_p08 (event_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS command_p09_event_id_idx ON noetl.command_p09 (event_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS command_p10_event_id_idx ON noetl.command_p10 (event_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS command_p11_event_id_idx ON noetl.command_p11 (event_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS command_p12_event_id_idx ON noetl.command_p12 (event_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS command_p13_event_id_idx ON noetl.command_p13 (event_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS command_p14_event_id_idx ON noetl.command_p14 (event_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS command_p15_event_id_idx ON noetl.command_p15 (event_id);

-- Parent: created INVALID (ON ONLY), flips to valid as the attaches complete.
CREATE INDEX IF NOT EXISTS idx_command_event_id ON ONLY noetl.command (event_id);

ALTER INDEX noetl.idx_command_event_id ATTACH PARTITION noetl.command_p00_event_id_idx;
ALTER INDEX noetl.idx_command_event_id ATTACH PARTITION noetl.command_p01_event_id_idx;
ALTER INDEX noetl.idx_command_event_id ATTACH PARTITION noetl.command_p02_event_id_idx;
ALTER INDEX noetl.idx_command_event_id ATTACH PARTITION noetl.command_p03_event_id_idx;
ALTER INDEX noetl.idx_command_event_id ATTACH PARTITION noetl.command_p04_event_id_idx;
ALTER INDEX noetl.idx_command_event_id ATTACH PARTITION noetl.command_p05_event_id_idx;
ALTER INDEX noetl.idx_command_event_id ATTACH PARTITION noetl.command_p06_event_id_idx;
ALTER INDEX noetl.idx_command_event_id ATTACH PARTITION noetl.command_p07_event_id_idx;
ALTER INDEX noetl.idx_command_event_id ATTACH PARTITION noetl.command_p08_event_id_idx;
ALTER INDEX noetl.idx_command_event_id ATTACH PARTITION noetl.command_p09_event_id_idx;
ALTER INDEX noetl.idx_command_event_id ATTACH PARTITION noetl.command_p10_event_id_idx;
ALTER INDEX noetl.idx_command_event_id ATTACH PARTITION noetl.command_p11_event_id_idx;
ALTER INDEX noetl.idx_command_event_id ATTACH PARTITION noetl.command_p12_event_id_idx;
ALTER INDEX noetl.idx_command_event_id ATTACH PARTITION noetl.command_p13_event_id_idx;
ALTER INDEX noetl.idx_command_event_id ATTACH PARTITION noetl.command_p14_event_id_idx;
ALTER INDEX noetl.idx_command_event_id ATTACH PARTITION noetl.command_p15_event_id_idx;

-- Verify: must return indisvalid = t.  An invalid parent means an attach was
-- missed and the planner will still seq-scan.
--   SELECT indisvalid FROM pg_index
--    WHERE indexrelid = 'noetl.idx_command_event_id'::regclass;
