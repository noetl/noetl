# `noetl.outbox` — Transactional Outbox Publisher

Standalone worker that drains the `noetl.outbox` table and publishes each
row to NATS. The companion in-process helpers live in
[`noetl.core.outbox`](../core/outbox.py) — they own the DDL, the enqueue
path called from `PostgresEventStore.append`, and the publish-batch loop.
This `noetl.outbox` package is the long-running publisher service.

## Status

- **Helpers:** [`noetl/core/outbox.py`](../core/outbox.py)
- **Worker entry point:** `python -m noetl.outbox` →
  [`noetl/outbox/__main__.py`](__main__.py) → [`worker.py`](worker.py)
- **Phase:** v2 distributed-runtime spec phase 2 (event mirror + outbox).

## Why an outbox

`PostgresEventStore.append()` writes to `noetl.event` and (when mirror is
enabled) enqueues to `noetl.outbox` **in the same transaction**. A separate
publisher process drains the outbox and publishes to NATS at-least-once.
This decouples event durability from NATS availability: a NATS outage
causes outbox rows to back up but never blocks a producer's commit.

## Schema

DDL is owned by `noetl.core.outbox.OUTBOX_DDL`. `ensure_outbox_schema()`
applies it idempotently at worker start.

```sql
CREATE TABLE noetl.outbox (
    outbox_id      BIGSERIAL PRIMARY KEY,
    execution_id   BIGINT,
    event_id       BIGINT NOT NULL,
    subject        TEXT,
    payload        JSONB NOT NULL,
    payload_bytes  BYTEA,
    payload_codec  TEXT NOT NULL DEFAULT 'arrow-feather',
    status         TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'IN_FLIGHT', 'PUBLISHED', 'FAILED')),
    attempts       INTEGER NOT NULL DEFAULT 0,
    available_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_at      TIMESTAMPTZ,
    published_at   TIMESTAMPTZ,
    last_error     TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (execution_id, event_id)
);

CREATE INDEX idx_outbox_ready
    ON noetl.outbox (status, available_at, outbox_id)
    WHERE status IN ('PENDING', 'FAILED');

CREATE INDEX idx_outbox_execution_event
    ON noetl.outbox (execution_id, event_id);
```

- `(execution_id, event_id)` is unique — re-enqueueing the same event is a
  no-op (`ON CONFLICT DO NOTHING`).
- Status transitions: `PENDING → IN_FLIGHT → PUBLISHED` on success;
  `IN_FLIGHT → FAILED` on publish error, then retried after
  exponential backoff (`available_at = now() + delay`).
- `payload_codec` defaults to `arrow-feather`. The enqueue path serializes
  the envelope with `rows_to_arrow_feather([payload])` and stores the
  bytes in `payload_bytes`; `payload` (JSONB) is kept for inspection and
  fallback publish paths that need JSON.

## Publish flow

`claim_outbox_batch(limit=N)` (in `noetl.core.outbox`) takes the next `N`
ready rows with `FOR UPDATE SKIP LOCKED` and flips them to `IN_FLIGHT`,
incrementing `attempts`. The publisher then iterates:

1. If `subject` and `payload_bytes` are set, publish the raw Feather bytes
   on `subject` via `NATSEventPublisher._publish_event_payload`.
2. Otherwise, fall back to `event_publisher.publish_event(payload)` which
   derives the subject from the JSON envelope.
3. On success, `mark_outbox_published(outbox_id)` sets status to
   `PUBLISHED` and stamps `published_at`.
4. On failure, `mark_outbox_failed(outbox_id, error, attempts)` sets
   status `FAILED`, records `last_error`, and schedules retry via
   `available_at = now() + (2^(attempts-1) seconds, capped at 300s)`.

`SKIP LOCKED` makes the publisher horizontally safe — multiple replicas
can drain the same outbox without stepping on each other.

## Running

```bash
# Loop forever, drain in batches of 100, sleep 1s when idle.
python -m noetl.outbox

# Knobs (CLI overrides env).
python -m noetl.outbox \
    --batch-size 250 \
    --idle-sleep 0.5 \
    --error-sleep 5

# One shot — useful in tests / cron.
python -m noetl.outbox --once
```

The worker initializes the database pool from `get_pgdb_connection()` and
calls `ensure_outbox_schema()` before its first batch.

## Configuration

| Env var | Default | Effect |
|---|---|---|
| `NOETL_OUTBOX_PUBLISHER_BATCH_SIZE` | `100` | Rows claimed per loop iteration. Lower bound 1. |
| `NOETL_OUTBOX_PUBLISHER_IDLE_SLEEP_SECONDS` | `1.0` | Sleep when a batch returned 0 rows. Lower bound 0.05. |
| `NOETL_OUTBOX_PUBLISHER_ERROR_SLEEP_SECONDS` | `5.0` | Sleep after an iteration raised. Lower bound 0.05. |
| `NOETL_OUTBOX_PUBLISHER_ONCE` | `false` | One-batch-then-exit mode. CLI `--once` overrides. |

Producers must additionally set `NOETL_EVENT_MIRROR_ENABLED=true` on the
event-store side (see [`event_store/README.md`](../core/event_store/README.md)),
otherwise nothing ever lands in `noetl.outbox`.

## Operations

### Inspect outbox state

```sql
-- Backlog by status.
SELECT status, count(*), min(created_at), max(updated_at)
FROM noetl.outbox
GROUP BY status;

-- Oldest pending row (publish lag).
SELECT outbox_id, event_id, subject, attempts,
       now() - created_at AS age
FROM noetl.outbox
WHERE status IN ('PENDING', 'FAILED')
ORDER BY outbox_id
LIMIT 10;

-- Recent failures.
SELECT outbox_id, event_id, attempts, last_error, available_at
FROM noetl.outbox
WHERE status = 'FAILED'
ORDER BY updated_at DESC
LIMIT 20;
```

### Force-redrive a stuck row

```sql
-- Reset a stuck IN_FLIGHT row that lost its publisher (e.g., pod OOMKill).
UPDATE noetl.outbox
SET status = 'PENDING', locked_at = NULL, updated_at = now()
WHERE outbox_id = $1 AND status = 'IN_FLIGHT';
```

There is no automatic stuck-IN_FLIGHT reaper today. If a publisher crashes
mid-batch, rows stay `IN_FLIGHT` until manually reset. Tracked as a
followup in the v2 spec.

### Scale out

Run multiple replicas of `python -m noetl.outbox` against the same
database. `FOR UPDATE SKIP LOCKED` divides the work; no coordination
needed. There is no per-shard partitioning — each replica claims any
ready row.

## Related

- [`noetl.core.outbox`](../core/outbox.py) — DDL, `enqueue_outbox`,
  `publish_outbox_batch`, retry/backoff helpers
- [`noetl.core.event_store`](../core/event_store/README.md) — caller that
  enqueues outbox rows inside the append transaction
- [`noetl.projector`](../projector/README.md) — the typical NATS
  consumer that reads what the outbox publishes
- Spec: [noetl_distributed_runtime_spec.md](https://github.com/noetl/docs/blob/main/docs/features/noetl_distributed_runtime_spec.md)
