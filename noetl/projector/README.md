# `noetl.projector` — Out-of-Process Projection Worker

Standalone NATS JetStream consumer that decodes event envelopes, folds
them into replay-state projections, and writes the result to the
[projection store](../core/projection_store/README.md). Runs as a
StatefulSet of horizontally-shardable workers — one worker per shard,
shard ownership keyed off `execution_id`.

## Status

- **Worker primitives:** [`noetl/core/projector/nats_worker.py`](../core/projector/nats_worker.py)
- **Replay-state folding service:** [`noetl/core/projector/service.py`](../core/projector/service.py)
  (reuses `noetl.server.api.replay.service.fold_replay_state` so in-process
  and out-of-process projection produce identical state)
- **Metrics surface:** [`noetl/core/projector/metrics.py`](../core/projector/metrics.py)
- **Entry point:** `python -m noetl.projector` →
  [`noetl/projector/__main__.py`](__main__.py)
- **Phase:** v2 distributed-runtime spec phase 2 (projector StatefulSet
  behind NATS durable consumers).

## Architecture

```
                    NATS JetStream stream NOETL_EVENTS
                          subject "noetl.events.>"
                                  │
                ┌─────────────────┼─────────────────┐
                │ pull, durable   │ pull, durable   │ pull, durable
                │ consumer        │ consumer        │ consumer
                ▼                 ▼                 ▼
        ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
        │ projector-0 │   │ projector-1 │   │ projector-N │   StatefulSet
        │ shard 0/N   │   │ shard 1/N   │   │ shard N/N   │
        └──────┬──────┘   └──────┬──────┘   └──────┬──────┘
               │ owns events where execution_id %  │
               │ shard_count == shard_index        │
               ▼                                   ▼
          ReplayStateProjector.project()  ──►  noetl.projection
                                                noetl.projection_snapshot
```

Per notification:

1. `NATSCommandSubscriber` pulls a batch; payload is decoded via
   `decode_projector_notification()`. Accepted formats: JSON, or Arrow
   Feather (used by the outbox publisher path). Decode failures bump
   `decode_errors_total` and NAK.
2. `_extract_events()` normalizes the notification to a list of event
   dicts. The notification may carry one event, an `events: [...]` batch,
   or be a single event-shaped envelope at the top level.
3. Each event is classified by `_shard_decision`: `owned` if
   `int(execution_id) % shard_count == shard_index`, `unowned` if assigned
   to another shard, `unshardable` if `execution_id` is missing or
   non-integer. Unshardable events are counted but ACKed (dropping them
   on the floor would block the consumer; reprocessing them is harmless
   given idempotent writes).
4. `ReplayStateProjector.project()` groups events by
   `(tenant_id, organization_id, execution_id)`, sorts by
   `(stream_version, event_id)`, calls `fold_replay_state(...)`, builds
   a `ProjectionRecord(projection_id="execution/<id>/<projection>",
   projection_type="replay_state:<projection>", version=...)`, and calls
   `save_projection()`. Returns the list of records that actually changed
   (the projection store's version-monotonic upsert drops stale replays).
5. Successful batches are ACKed. Failures bump `errors_total` and bubble
   up to the subscriber, which NAKs with backoff per its own policy.

## Running

```bash
# Defaults: stream=NOETL_EVENTS, subject="noetl.events.>", shard 0 of 1.
python -m noetl.projector

# Local dev — single shard, metrics on :9100.
python -m noetl.projector \
    --nats-url nats://localhost:30422 \
    --shard-id noetl-projector-0 \
    --shard-count 1 \
    --metrics-port 9100

# Production — pick up shard_id from $HOSTNAME (StatefulSet convention).
HOSTNAME=noetl-projector-3 \
NOETL_PROJECTOR_SHARD_COUNT=8 \
NOETL_PROJECTOR_NATS_URL=nats://noetl:noetl@nats.nats.svc.cluster.local:4222 \
NOETL_PROJECTOR_METRICS_PORT=9100 \
    python -m noetl.projector
```

The worker calls `PostgresProjectionStore.ensure_schema()` at startup. If
the database role lacks DDL privilege the call is logged and skipped —
production deployments should pre-apply the
[projection schema](../core/projection_store/README.md#schema) via a
migration.

## Configuration

All settings can be supplied via env var, CLI flag, or both — CLI wins.

| Env var | CLI | Default | Effect |
|---|---|---|---|
| `NOETL_PROJECTOR_NATS_URL` / `NATS_URL` | `--nats-url` | `nats://noetl:noetl@nats.nats.svc.cluster.local:4222` | NATS endpoint. |
| `NOETL_PROJECTOR_NATS_STREAM` | `--stream` | `NOETL_EVENTS` | JetStream stream name. |
| `NOETL_PROJECTOR_NATS_SUBJECT` | `--subject` | `noetl.events.>` | Subject filter. |
| `NOETL_PROJECTOR_NATS_CONSUMER` | `--consumer` | = `shard_id` | Durable consumer name. Must be stable across restarts. |
| `NOETL_PROJECTOR_SHARD_ID` / `NOETL_SHARD_ID` / `HOSTNAME` | `--shard-id` | `noetl-projector-0` | Stable shard identity. The trailing integer in the id determines the shard index. |
| `NOETL_PROJECTOR_SHARD_COUNT` | `--shard-count` | `1` | Total shard count. Strict invariant: `shard_index < shard_count`. |
| `NOETL_PROJECTOR_MAX_INFLIGHT` | — | `8` | Max events being folded concurrently. |
| `NOETL_PROJECTOR_NATS_MAX_ACK_PENDING` | — | `64` | JetStream max-ack-pending on the consumer. |
| `NOETL_PROJECTOR_NATS_FETCH_TIMEOUT_SECONDS` | — | `30.0` | Pull fetch timeout. |
| `NOETL_PROJECTOR_NATS_FETCH_HEARTBEAT_SECONDS` | — | `5.0` | Pull heartbeat interval. |
| `NOETL_PROJECTOR_METRICS_HOST` | `--metrics-host` | `0.0.0.0` | Metrics HTTP bind host. |
| `NOETL_PROJECTOR_METRICS_PORT` | `--metrics-port` | unset | When set, exposes `/metrics`, `/summary`, `/health`. When unset, no HTTP server is started. |

`__post_init__` on `ProjectorWorkerSettings` enforces the invariants — bad
config fails fast at startup, not at first message.

## Sharding model

- `shard_id` is a free-form string but must end in a non-negative integer.
  `noetl-projector-3` → shard_index `3`. Anything without a trailing digit
  resolves to `0`.
- Every projector replica receives every event in its consumer's subject
  filter; the replica decides ownership locally by
  `execution_id % shard_count == shard_index`. This means rebalancing on
  `shard_count` change requires every replica to use the new count
  simultaneously — otherwise the same execution gets folded twice (still
  safe thanks to version-monotonic upserts) or zero times (projection
  goes stale).
- Events with no `execution_id` are tagged `unshardable`, counted in
  metrics, and ACKed without folding. They never produce projection rows.

## Metrics

When `--metrics-port` / `NOETL_PROJECTOR_METRICS_PORT` is set, an HTTP
server runs in a daemon thread exposing:

- `GET /metrics` — Prometheus text exposition, with labels
  `shard_id`, `shard_index`, `shard_count`, `consumer`, `stream`,
  `subject`.
- `GET /summary` — JSON snapshot with action/batch/error sub-summaries,
  useful for `curl | jq` debugging.
- `GET /health` — `200 ok\n` once the server is up.

### Key metrics

| Metric | Type | Meaning |
|---|---|---|
| `noetl_projector_notifications_total` | counter | NATS notifications handled. |
| `noetl_projector_events_owned_total` / `_unowned_total` / `_unshardable_total` | counter | Shard-routing breakdown. |
| `noetl_projector_projection_records_total` | counter | Projections actually written (stale replays excluded). |
| `noetl_projector_projection_stale_records_total` | counter | Projection groups whose write was dropped because a newer version exists. |
| `noetl_projector_errors_total` / `_decode_errors_total` / `_projection_errors_total` | counter | Failure classes. |
| `noetl_projector_acknowledged_notifications_total` / `_redelivery_requests_total` / `_terminated_notifications_total` | counter | Subscriber terminal actions. |
| `noetl_projector_last_projection_lag_milliseconds` | gauge | Latest fold's lag from event-time watermark to write time. |
| `noetl_projector_max_projection_lag_milliseconds` | gauge | Max observed lag since process start. |
| `noetl_projector_last_success_unixtime` / `_last_error_unixtime` | gauge | Liveness hints. |

The `/summary` payload aggregates these into `actions`, `batch`, and
`errors` sub-objects with derived ratios (e.g., `ack_ratio`,
`stale_projection_ratio`) suitable for one-shot operator checks.

## Operations

### "Is the projector keeping up?"

```bash
curl -s :9100/summary | jq '.summary | {
  notifications_total,
  lag_ms: .last_projection_lag_milliseconds,
  max_lag_ms: .max_projection_lag_milliseconds,
  stale_ratio: .batch.stale_projection_ratio,
  ack_ratio: .actions.ack_ratio,
  errors: .errors.errors_total
}'
```

Healthy: `lag_ms` under a few seconds, `ack_ratio ≈ 1.0`,
`stale_ratio ≈ 0`. Sustained nonzero `errors_total` warrants checking
logs.

### "I changed shard_count; what now?"

1. Update `NOETL_PROJECTOR_SHARD_COUNT` on every replica simultaneously
   (rolling restart of the StatefulSet).
2. Existing projections remain valid — the version-monotonic upsert means
   any double-fold during the rollout is a no-op for stale writes.
3. Watch `noetl_projector_max_projection_lag_milliseconds` to confirm
   each shard catches up.

### "A shard is stuck."

- Check `last_success_unixtime` vs `last_error_unixtime` on `/summary`.
- Check NATS for the consumer's `num_pending` — if it's flat at zero,
  the issue is upstream (outbox not publishing). If growing, the shard
  is the bottleneck.
- Restart the pod. JetStream durable consumers resume from their last
  acked position; nothing is lost.

### "Decode errors are climbing."

`decode_errors_total` only goes up when neither JSON nor Arrow Feather
decode succeeds. Inspect the recent NATS message bytes — usually a
producer is publishing a new payload codec the projector doesn't know.

## Related

- [`noetl.core.event_store`](../core/event_store/README.md) — durable log
  the projector ultimately sources from
- [`noetl.outbox`](../outbox/README.md) — typical publisher that puts
  events on the NATS subject the projector consumes
- [`noetl.core.projection_store`](../core/projection_store/README.md) —
  destination of folded state
- `noetl.server.api.replay.service.fold_replay_state` — folding kernel
  shared with the in-process replay API
- Spec: [noetl_distributed_runtime_spec.md](https://github.com/noetl/docs/blob/main/docs/features/noetl_distributed_runtime_spec.md)
