-- Helper utilities for managing noetl.event partitions
-- Usage (psql): \i scripts/db/manage_event_partitions.sql
-- Then call procedures, e.g.:
--   CALL noetl.ensure_event_partition('2026-07-01', '2026-10-01', 'event_2026_q3');
--   CALL noetl.drop_event_partition('event_2025_q4');

-- Epoch used by noetl.snowflake_id() (2024-01-01 UTC)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'noetl') THEN
    RAISE EXCEPTION 'Schema noetl does not exist';
  END IF;
END$$;

CREATE OR REPLACE FUNCTION noetl.partition_id_for_ts(ts timestamptz)
RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
  our_epoch BIGINT := 1704067200000; -- 2024-01-01 UTC in ms
  now_ms BIGINT;
BEGIN
  now_ms := (EXTRACT(EPOCH FROM ts) * 1000)::BIGINT;
  RETURN ((now_ms - our_epoch) << 23);
END;
$$;

CREATE OR REPLACE PROCEDURE noetl.ensure_event_partition(
  start_ts timestamptz,
  end_ts   timestamptz,
  partition_name text
)
LANGUAGE plpgsql
AS $$
DECLARE
  start_id BIGINT;
  end_id   BIGINT;
  sql_text text;
BEGIN
  start_id := noetl.partition_id_for_ts(start_ts);
  end_id   := noetl.partition_id_for_ts(end_ts);

  sql_text := format(
    'CREATE TABLE IF NOT EXISTS noetl.%I PARTITION OF noetl.event FOR VALUES FROM (%s) TO (%s);',
    partition_name, start_id, end_id
  );

  EXECUTE sql_text;
END;
$$;

CREATE OR REPLACE PROCEDURE noetl.drop_event_partition(partition_name text)
LANGUAGE plpgsql
AS $$
DECLARE
  sql_text text;
BEGIN
  sql_text := format('DROP TABLE IF EXISTS noetl.%I;', partition_name);
  EXECUTE sql_text;
END;
$$;

-- Quick helper view of current event partitions
CREATE OR REPLACE VIEW noetl.event_partitions AS
SELECT
  inhrelid::regclass AS name,
  pg_get_expr(pg_class.relpartbound, pg_class.oid) AS boundary,
  pg_size_pretty(pg_total_relation_size(inhrelid)) AS total_size
FROM pg_inherits
JOIN pg_class ON inhrelid = pg_class.oid
JOIN pg_namespace ns ON pg_class.relnamespace = ns.oid
WHERE inhparent = 'noetl.event'::regclass
  AND ns.nspname = 'noetl'
ORDER BY inhrelid::regclass::text;
