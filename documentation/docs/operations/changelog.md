---
id: runtime-backpressure-throttling-changelog-2026-02
title: Runtime Changelog - NATS Backpressure, Throttling, and PgBouncer Pooling
sidebar_label: Runtime Changelog (2026-02)
sidebar_position: 3
description: Detailed implementation changelog for distributed loop safety, queue backpressure, worker throttling, logging sanitization, and PgBouncer connection pooling.
---

# Runtime Changelog - NATS Backpressure, Throttling, and PgBouncer Pooling

## Scope

This changelog documents the runtime hardening work for distributed batch execution, with focus on:

- `task_sequence` loop completion correctness across multiple server instances.
- NATS-driven backpressure and bounded worker concurrency.
- Worker-side throttling based on PostgreSQL pool pressure.
- Reduced payload/context logging and tighter log severity behavior.
- PgBouncer deployment and configuration path for Cloud SQL / in-cluster PostgreSQL traffic.

## Why this change was needed

### 1) Premature `loop.done` in distributed `task_sequence`

In multi-server deployments, a `call.done` event can be processed by a different server instance than the one that initialized the loop state in memory. When local `loop_state.collection` was empty, completion checks could incorrectly pass too early.

### 2) Unbounded queue pressure and burst behavior

The worker could accept large numbers of pending NATS messages (`max_ack_pending` too high in existing durable consumer), causing bursty load against HTTP and Postgres during high-volume loops.

### 3) Database pressure amplification

Large loop pipelines (especially `http -> postgres` patterns) could overrun DB pools when fanout increased, causing retries, longer execution time, and unstable latency.

### 4) Excessive log payload visibility/noise

Request/response and context payloads were too verbose for normal operation and risked exposing sensitive values in non-debug logs.

## Implementation summary

### A) Distributed-safe loop completion for `task_sequence`

**Area:** `noetl/core/dsl/v2/engine.py`

`call.done` handling for `:task_sequence` loop steps now resolves collection size with distributed fallback order:

1. Local loop cache (`loop_state.collection`) when available.
2. NATS KV loop state (`collection_size`) keyed by execution/loop event.
3. Re-render loop collection from template when both caches are unavailable.
4. Persist re-rendered size back to NATS KV for subsequent distributed checks.

This prevents false-positive `loop.done` when local server memory misses loop collection.

### B) NATS consumer backpressure and reconciliation

**Area:** `noetl/core/messaging/nats_client.py`

#### New controls

- `max_inflight` (process-local in-flight semaphore on worker subscriber).
- `max_ack_pending` (JetStream durable consumer cap).
- `fetch_timeout` and `fetch_heartbeat` (pull-consumer fetch behavior).

#### Durable consumer config reconciliation

Worker startup now enforces configured `max_ack_pending` against existing durable consumers:

- If consumer is missing: create with configured `max_ack_pending`.
- If consumer exists with mismatched `max_ack_pending`: delete + recreate durable.
- If concurrent worker startup races consumer creation: validate existing config and continue if matched.

This closes the gap where runtime logs warned about mismatch (`1000` vs `64`) but effective queue cap remained unchanged.

### C) Worker throttling and DB-aware gating

**Area:** `noetl/worker/v2_worker_nats.py`

Worker now applies two layers of throttling:

1. **Global in-flight cap** for all commands (`NOETL_WORKER_MAX_INFLIGHT_COMMANDS`).
2. **DB-heavy in-flight cap** for tools likely to hit DB (`postgres`, `transfer`, `snowflake`, `snowflake_transfer`).

For DB-heavy commands, worker checks plugin pool stats and waits when saturated:

- Polls `get_plugin_pool_stats()`.
- Uses threshold `NOETL_WORKER_POSTGRES_POOL_WAITING_THRESHOLD`.
- Delays execution with `NOETL_WORKER_THROTTLE_POLL_INTERVAL_SECONDS` until headroom is available.

This avoids thundering-herd behavior against Postgres/PgBouncer under loop bursts.

### D) HTTP and Postgres executor pressure controls

#### HTTP executor

**Area:** `noetl/tools/http/executor.py`

- Added shared keep-alive `httpx.Client` reuse per worker process.
- Added configurable connection limits and keepalive expiry.
- Logging now records request shape and sanitized metadata instead of full payload dumps.

#### Postgres executor + pool

**Areas:**
- `noetl/tools/postgres/executor.py`
- `noetl/tools/postgres/execution.py`
- `noetl/tools/postgres/pool.py`

- Pooled mode is preferred by default (`NOETL_POSTGRES_USE_POOL_DEFAULT=true`).
- Pool parameters are bounded via env (`min/max size`, `max_waiting`, `timeout`, lifetime/idle).
- Direct connection mode has bounded concurrency and retry with backoff.
- SQL logs use operation/length summaries instead of raw SQL statements.

### E) Logging safety and severity tightening

**Areas:**
- `noetl/core/logger.py`
- `noetl/server/middleware.py`
- `noetl/core/runtime/events.py`

#### Logger behavior

- Default effective level now follows `NOETL_LOG_LEVEL` (fallback: `LOG_LEVEL`, default `INFO`).
- Log message and `extra` fields are sanitized via `sanitize_sensitive_data` / `sanitize_for_logging`.
- String and complex objects are truncated with `NOETL_LOG_VALUE_MAX_CHARS` (default `400`).

#### API middleware behavior

- Normal path logs only metadata at debug level (`request_meta`, `response_meta`).
- Request payload previews on errors are opt-in only:
  - `NOETL_LOG_INCLUDE_PAYLOAD_ON_ERROR=true`
- Timeout and exception logs include payload size/type metadata, not full raw bodies by default.

#### Event reporting behavior

- On `422` event API failures, logs now include metadata summary only (`keys + length`), not raw payload dump.

### F) Large result handling preview hygiene

**Area:** `noetl/core/storage/result_store.py`

- Preview generation moved to byte-capped extractor (`create_preview`) to avoid oversized previews in event/UI paths.

## New/updated runtime configuration

### Worker NATS/backpressure and throttling

Defined in:

- `noetl/core/config.py` (`WorkerSettings`)
- `automation/helm/noetl/values.yaml` (`config.worker.*`)

| Env var | Default | Purpose |
| --- | --- | --- |
| `NOETL_WORKER_NATS_FETCH_TIMEOUT_SECONDS` | `30` | Pull fetch timeout for JetStream consumer |
| `NOETL_WORKER_NATS_FETCH_HEARTBEAT_SECONDS` | `5` | Fetch heartbeat to keep long-poll alive |
| `NOETL_WORKER_NATS_MAX_ACK_PENDING` | `64` | Broker-side cap of unacked messages per consumer |
| `NOETL_WORKER_MAX_INFLIGHT_COMMANDS` | `8` | Process-local cap of concurrently executing commands |
| `NOETL_WORKER_MAX_INFLIGHT_DB_COMMANDS` | `4` | Extra cap for DB-heavy command kinds |
| `NOETL_WORKER_THROTTLE_POLL_INTERVAL_SECONDS` | `0.2` | Sleep interval while waiting for DB pool headroom |
| `NOETL_WORKER_POSTGRES_POOL_WAITING_THRESHOLD` | `2` | Max tolerated waiting requests before throttling |

### Postgres plugin pool settings

Defined in Helm worker/server config map defaults (`automation/helm/noetl/values.yaml`) and consumed by postgres executors:

| Env var | Default |
| --- | --- |
| `NOETL_POSTGRES_POOL_MIN_SIZE` | `1` |
| `NOETL_POSTGRES_POOL_MAX_SIZE` | `12` |
| `NOETL_POSTGRES_POOL_MAX_WAITING` | `200` |
| `NOETL_POSTGRES_POOL_TIMEOUT_SECONDS` | `60` |

## PgBouncer: where config is stored and how NoETL connects

## 1) Source of truth for PgBouncer deployment settings

**File:** `automation/gcp_gke/noetl_gke_fresh_stack.yaml`

`workload` defaults define PgBouncer runtime knobs, including:

- `pgbouncer_enabled`
- `pgbouncer_namespace`
- `pgbouncer_service_name`
- `pgbouncer_max_client_conn`
- `pgbouncer_default_pool_size`
- `pgbouncer_min_pool_size`
- `pgbouncer_reserve_pool_size`
- `pgbouncer_reserve_pool_timeout`
- `pgbouncer_max_db_connections`
- `pgbouncer_server_lifetime`
- `pgbouncer_server_idle_timeout`

Deployment step `deploy_pgbouncer` renders a Kubernetes `Deployment` + `Service`, and passes these values as PgBouncer container environment variables (`MAX_CLIENT_CONN`, `DEFAULT_POOL_SIZE`, etc.).

## 2) How NoETL server/worker are pointed to PgBouncer

### Deploy-time wiring

**File:** `automation/gcp_gke/noetl_gke_fresh_stack.yaml` (`deploy_noetl` step)

- `DB_HOST` is set to `workload.postgres_host`.
- In Cloud SQL + PgBouncer mode, this host is typically:
  - `pgbouncer.postgres.svc.cluster.local`
- Helm applies this into NoETL server config:
  - `config.server.POSTGRES_HOST=$DB_HOST`
  - `config.server.POSTGRES_PORT=$DB_PORT`

### Helm config map storage

**Files:**

- `automation/helm/noetl/values.yaml`
- `automation/helm/noetl/templates/configmap-server.yaml`
- `automation/helm/noetl/templates/configmap-worker.yaml`

These generate env vars injected into server/worker pods via `envFrom`.

## 3) Connection path at runtime

### Server -> NoETL system database

1. Server reads `POSTGRES_HOST/POSTGRES_PORT` from config map env.
2. `noetl/core/config.py` builds NoETL connection string.
3. `noetl/core/db/pool.py` initializes server `AsyncConnectionPool`.
4. Host points to PgBouncer service when enabled.

### Worker -> user/playbook Postgres targets

1. Postgres tool resolves connection details from auth/task config.
2. Executor uses pooled mode by default.
3. Pool manager reuses connections by connection-string hash.
4. If credentials host points to PgBouncer service, worker traffic also goes through PgBouncer.

## 4) Why PgBouncer does not open a backend for every request

PgBouncer is configured with `POOL_MODE=transaction`, so client sessions are multiplexed over a reusable backend pool. Combined with NoETL-side connection pooling:

- NoETL avoids per-command connect/disconnect overhead.
- PgBouncer avoids backend churn to PostgreSQL.
- Queue-level throttling prevents sudden spikes from saturating backend capacity.

## NATS backpressure: `max_ack_pending=64` vs `1000`

Operationally:

- `64`: tighter broker-side pressure, smaller burst windows, faster recovery under degradation, less DB shock.
- `1000`: allows much larger queued unacked bursts and larger replay spikes after slowdown/restart.

In this runtime, primary throughput control is still worker in-flight semaphores. `max_ack_pending` acts as broker-side guardrail.

## Verification checklist

Use these commands after deploy:

```bash
# 1) Confirm worker config values in Kubernetes
kubectl get configmap noetl-worker-config -n noetl -o yaml | rg "NOETL_WORKER_NATS_MAX_ACK_PENDING|NOETL_WORKER_MAX_INFLIGHT_COMMANDS|NOETL_WORKER_MAX_INFLIGHT_DB_COMMANDS"

# 2) Confirm worker startup logs include effective throttling config
kubectl logs deployment/noetl-worker -n noetl --since=15m | rg "starting \(NATS:|THROTTLE|max_ack_pending"

# 3) Confirm PgBouncer is deployed and healthy
kubectl get deploy,svc -n postgres | rg pgbouncer
kubectl logs deployment/pgbouncer -n postgres --since=15m | tail -n 100

# 4) Run a heavy batch smoke execution
noetl --host localhost --port 8082 exec \
  catalog://tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_in_step \
  -r distributed
```

## Affected files (implementation)

- `noetl/core/dsl/v2/engine.py`
- `tests/unit/dsl/v2/test_task_sequence_loop_completion.py`
- `noetl/core/messaging/nats_client.py`
- `tests/core/test_nats_command_subscriber.py`
- `noetl/core/config.py`
- `noetl/worker/v2_worker_nats.py`
- `noetl/tools/http/executor.py`
- `noetl/tools/postgres/executor.py`
- `noetl/tools/postgres/execution.py`
- `noetl/tools/postgres/pool.py`
- `noetl/core/logger.py`
- `noetl/server/middleware.py`
- `noetl/core/runtime/events.py`
- `noetl/core/storage/result_store.py`
- `automation/helm/noetl/values.yaml`
- `automation/gcp_gke/noetl_gke_fresh_stack.yaml`

## Notes

- Recreating durable consumers to enforce `max_ack_pending` is intentional. During rollout, a brief rebalance can occur while workers reconnect.
- Keep `NOETL_WORKER_MAX_INFLIGHT_DB_COMMANDS` lower than global in-flight for predictable DB pressure.
- For production, keep payload logging disabled by default and enable only for short, scoped debugging windows.
