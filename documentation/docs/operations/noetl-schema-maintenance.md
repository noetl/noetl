---
id: noetl-schema-maintenance
title: NoETL Schema & Partition Maintenance
sidebar_position: 12
---

This page explains how the core Postgres schema is organized, how the Snowflake-style IDs map to time, and how to manage the `noetl.event` partitions over time. It also ships a reusable helper script.

## Schema highlights
- `noetl.event` is **range-partitioned by `execution_id`** (not `created_at`).
- `execution_id` comes from `noetl.snowflake_id()` in `noetl/database/ddl/postgres/schema_ddl.sql`.
- Snowflake layout: `((now_ms - 2024-01-01T00:00:00Z) << 23) | (shard_id << 18) | seq`. The timestamp bits make IDs monotonically increasing with wall clock time.
- Because time sits in the high bits, time windows correspond to ID ranges. That’s why partitions are defined as numeric ranges instead of timestamps.

## Why partition this way
- **Instant retention:** dropping an old partition is O(1) and doesn’t require VACUUM.
- **Small indexes:** pruning picks one partition per execution, keeping per-partition indexes tiny.
- **Predictable boundaries:** you can pre-create future partitions by computing the ID for a date.

## Helper script
Path: `scripts/db/manage_event_partitions.sql`

What it provides:
- `noetl.partition_id_for_ts(ts)` → boundary ID for any timestamp.
- `CALL noetl.ensure_event_partition(start_ts, end_ts, name)` → creates a partition covering that window.
- `CALL noetl.drop_event_partition(name)` → drops a partition safely.
- View `noetl.event_partitions` showing current partitions and their sizes.

How to load and use (psql):
```bash
psql "$NOETL_DATABASE_URL" -f scripts/db/manage_event_partitions.sql
-- create next quarter (example: 2026 Q3)
CALL noetl.ensure_event_partition('2026-07-01', '2026-10-01', 'event_2026_q3');
-- drop an old partition
CALL noetl.drop_event_partition('event_2025_q4');
-- list partitions
SELECT * FROM noetl.event_partitions;
```

## Routine tasks
- **Before a new quarter starts:** run `ensure_event_partition` for the upcoming window (or half-year if you prefer fewer partitions).
- **Retention cleanup:** decide on a keep window (e.g., last 180 days) and drop older partitions with `drop_event_partition`. Because partitions are by ID/time, this instantly frees space.
- **GKE special partition:** `event_2026_gke` exists for a build that used a different epoch (IDs ~569T–600T). Keep it only if that build still runs; drop it otherwise.

## How boundaries are chosen
- Boundaries in `schema_ddl.sql` are labeled per quarter/half-year with comments showing the ID for the UTC date. They come from `partition_id_for_ts(<boundary_date>)` using the 2024-01-01 epoch.
- To compute manually:
```sql
SELECT noetl.partition_id_for_ts('2026-10-01');
```
Use the result as the `FROM/TO` bounds if you need custom windows.

## Cleanup and safety notes
- Dropping a partition only removes that time slice; other partitions stay online.
- If you need to archive first, `ALTER TABLE noetl.event DETACH PARTITION ...`, copy data, then drop.
- The default partition `noetl.event_default` catches any IDs outside the predefined ranges—keep it in place.

## Quick checklist
- [ ] Load the helper script once per environment.
- [ ] Create the next partition ahead of the boundary date.
- [ ] Drop partitions older than your retention window.
- [ ] Verify with `SELECT * FROM noetl.event_partitions;`.
