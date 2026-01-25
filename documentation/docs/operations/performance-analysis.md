---
id: performance-analysis
title: Performance Analysis
sidebar_label: Performance Analysis
sidebar_position: 3
---

# Performance Analysis

Guide for diagnosing and resolving playbook execution performance issues.

## Quick Start

### Immediate Diagnosis (PostgreSQL Only)

No ClickHouse required - analyze directly against PostgreSQL:

```bash
# Find bottlenecks (time gaps between events)
noetl run automation/observability/event-sync.yaml --set action=analyze-gaps --set since_hours=1

# Find slowest executions
noetl run automation/observability/event-sync.yaml --set action=analyze-slow --set since_hours=1
```

### Full Analysis (With ClickHouse)

```bash
# 1. Deploy ClickHouse (if not running)
noetl run automation/infrastructure/clickhouse.yaml --set action=deploy

# 2. Sync events to ClickHouse
noetl run automation/observability/event-sync.yaml --set action=sync --set since_hours=24

# 3. Run analysis queries
kubectl exec -n clickhouse <pod> -- clickhouse-client < ci/manifests/clickhouse/performance-queries.sql
```

## Event Sync Playbook

The event sync playbook (`automation/observability/event-sync.yaml`) provides tools for performance analysis.

### Available Actions

| Action | Description | Requires ClickHouse |
|--------|-------------|---------------------|
| `help` | Show usage information | No |
| `sync` | Sync events to ClickHouse | Yes |
| `sync-recent` | Alias for sync | Yes |
| `count` | Count events in both databases | Yes |
| `verify` | Verify sync status | Yes |
| `analyze-gaps` | Find time gaps (bottlenecks) | No |
| `analyze-slow` | Find slowest executions | No |

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `since_hours` | 24 | Time range to analyze |
| `batch_size` | 1000 | Max events per sync batch |
| `pg_auth` | pg_local | PostgreSQL auth profile |

### Examples

```bash
# Analyze last hour
noetl run automation/observability/event-sync.yaml \
  --set action=analyze-gaps \
  --set since_hours=1

# Sync with larger batch
noetl run automation/observability/event-sync.yaml \
  --set action=sync \
  --set since_hours=48 \
  --set batch_size=5000

# Use k8s postgres credentials
noetl run automation/observability/event-sync.yaml \
  --set action=analyze-slow \
  --set pg_auth=pg_k8s
```

## Performance Logs

The orchestrator emits structured `[PERF]` logs for real-time monitoring.

### Viewing Logs

```bash
# View all performance logs
kubectl logs -n noetl deployment/noetl-server | grep '\[PERF\]'

# Watch live
kubectl logs -n noetl deployment/noetl-server -f | grep '\[PERF\]'

# Filter by phase
kubectl logs -n noetl deployment/noetl-server | grep 'evaluate_execution'
```

### Metrics Logged

| Metric | Description | Target |
|--------|-------------|--------|
| `get_execution_state_batch` | State query time | <5ms |
| `get_transition_context_batch` | Transition query time | <10ms |
| `catalog_fetch` | Playbook fetch (cache miss) | <100ms |
| `evaluate_execution` | Total orchestration time | <50ms |

### Example Output

```
[PERF] get_execution_state_batch: 2.3ms
[PERF] get_transition_context_batch: 3.1ms
[PERF] catalog_fetch: 1.2ms (catalog_id=12345)
[PERF] evaluate_execution total: 8.5ms
```

### Warning Thresholds

Logs emit warnings when thresholds are exceeded:
- `evaluate_execution` > 500ms
- `catalog_fetch` > 100ms
- State reconstruction with >50 events

## Direct SQL Analysis

### PostgreSQL Queries

Connect to PostgreSQL:
```bash
kubectl exec -n postgres <pod> -- psql -U noetl -d noetl
```

#### Slowest Executions
```sql
SELECT
    e.execution_id,
    c.path as playbook_path,
    COUNT(*) as event_count,
    MIN(e.created_at) as started_at,
    ROUND(EXTRACT(EPOCH FROM (MAX(e.created_at) - MIN(e.created_at)))::numeric, 2) as duration_seconds,
    COUNT(DISTINCT e.node_name) as unique_steps
FROM noetl.event e
LEFT JOIN noetl.catalog c ON e.catalog_id = c.catalog_id
WHERE e.created_at > NOW() - INTERVAL '1 hour'
GROUP BY e.execution_id, c.path
ORDER BY duration_seconds DESC
LIMIT 20;
```

#### Event Transition Delays
```sql
WITH transitions AS (
    SELECT
        execution_id,
        event_type,
        created_at,
        LAG(event_type) OVER (PARTITION BY execution_id ORDER BY created_at) as prev_event,
        LAG(created_at) OVER (PARTITION BY execution_id ORDER BY created_at) as prev_time
    FROM noetl.event
    WHERE created_at > NOW() - INTERVAL '1 hour'
)
SELECT
    prev_event || ' -> ' || event_type as transition,
    COUNT(*) as occurrences,
    ROUND(AVG(EXTRACT(EPOCH FROM (created_at - prev_time)))::numeric, 3) as avg_sec,
    ROUND(percentile_cont(0.50) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (created_at - prev_time)))::numeric, 3) as p50_sec,
    ROUND(percentile_cont(0.95) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (created_at - prev_time)))::numeric, 3) as p95_sec
FROM transitions
WHERE prev_event IS NOT NULL
GROUP BY prev_event, event_type
HAVING COUNT(*) > 5
ORDER BY avg_sec DESC
LIMIT 15;
```

#### Bottleneck Detection (>2 second gaps)
```sql
WITH event_gaps AS (
    SELECT
        execution_id,
        event_type,
        node_name,
        created_at,
        LAG(created_at) OVER (PARTITION BY execution_id ORDER BY created_at) as prev_time,
        LAG(event_type) OVER (PARTITION BY execution_id ORDER BY created_at) as prev_event
    FROM noetl.event
    WHERE created_at > NOW() - INTERVAL '1 hour'
)
SELECT
    execution_id,
    prev_event as from_event,
    event_type as to_event,
    node_name,
    ROUND(EXTRACT(EPOCH FROM (created_at - prev_time))::numeric, 2) as gap_seconds
FROM event_gaps
WHERE created_at - prev_time > INTERVAL '2 seconds'
ORDER BY gap_seconds DESC
LIMIT 30;
```

#### Event Count per Execution
```sql
SELECT
    execution_id,
    COUNT(*) as total_events,
    MAX(created_at) - MIN(created_at) as duration
FROM noetl.event
WHERE created_at > NOW() - INTERVAL '1 hour'
GROUP BY execution_id
ORDER BY total_events DESC
LIMIT 20;
```

### ClickHouse Queries

Connect to ClickHouse:
```bash
kubectl exec -n clickhouse <pod> -- clickhouse-client
```

Full query library: `ci/manifests/clickhouse/performance-queries.sql`

#### Key Queries

**Execution Duration Distribution:**
```sql
SELECT
    EventType,
    count() AS event_count,
    round(avg(Duration), 2) AS avg_ms,
    round(quantile(0.50)(Duration), 2) AS p50_ms,
    round(quantile(0.95)(Duration), 2) AS p95_ms,
    max(Duration) AS max_ms
FROM observability.noetl_events
WHERE Timestamp >= now() - INTERVAL 1 HOUR
GROUP BY EventType
ORDER BY avg_ms DESC;
```

**Step Performance:**
```sql
SELECT
    StepName,
    count() AS occurrences,
    round(avg(Duration), 2) AS avg_ms,
    round(quantile(0.95)(Duration), 2) AS p95_ms
FROM observability.noetl_events
WHERE Timestamp >= now() - INTERVAL 24 HOUR
  AND StepName != ''
  AND Duration > 0
GROUP BY StepName
ORDER BY avg_ms DESC
LIMIT 20;
```

## Key Performance Indicators

### Healthy System

| Metric | Value |
|--------|-------|
| `command.completed → command.claimed` | <100ms |
| `evaluate_execution` total | <50ms |
| Playbook execution time | ~2-5 seconds for simple playbooks |
| Event count per execution | <100 for typical workflows |

### Warning Signs

| Symptom | Possible Cause | Solution |
|---------|----------------|----------|
| `command.completed → command.claimed` > 1s | Orchestrator overload | Check PERF logs, scale workers |
| High event count per execution | Complex workflows | Consider splitting playbooks |
| `catalog_fetch` > 100ms | Cache miss | Normal on first access |
| `evaluate_execution` > 500ms | State reconstruction | Archive old executions |

## Troubleshooting

### Slow Playbook Execution

1. **Check orchestrator performance:**
   ```bash
   kubectl logs -n noetl deployment/noetl-server | grep '\[PERF\]' | tail -50
   ```

2. **Identify slow transitions:**
   ```bash
   noetl run automation/observability/event-sync.yaml --set action=analyze-gaps
   ```

3. **Check for high event counts:**
   ```sql
   SELECT execution_id, COUNT(*) as events
   FROM noetl.event
   WHERE created_at > NOW() - INTERVAL '1 hour'
   GROUP BY execution_id
   HAVING COUNT(*) > 100;
   ```

### Worker Not Claiming Commands

1. **Check worker logs:**
   ```bash
   kubectl logs -n noetl deployment/noetl-worker | tail -100
   ```

2. **Verify NATS connection:**
   ```bash
   kubectl logs -n noetl deployment/noetl-worker | grep -i nats
   ```

3. **Check worker registration:**
   ```sql
   SELECT * FROM noetl.runtime WHERE component_type = 'worker_pool';
   ```

### High Memory Usage

1. **Check catalog cache stats** (in server logs)
2. **Monitor event table size:**
   ```sql
   SELECT pg_size_pretty(pg_total_relation_size('noetl.event'));
   ```

3. **Consider archiving old events:**
   ```sql
   DELETE FROM noetl.event WHERE created_at < NOW() - INTERVAL '7 days';
   ```

## Architecture Notes

### Performance Optimizations

1. **Batch Queries**: The orchestrator uses `get_transition_context_batch()` to fetch all transition data in a single query instead of 6+ sequential queries.

2. **Catalog Caching**: LRU cache (100 entries, 5-minute TTL) for playbook content avoids repeated database lookups.

3. **State Reconstruction**: Events are processed in order to reconstruct workflow state. High event counts impact performance.

### Critical Path

```
Worker completes command
    ↓
Event emitted to server (HTTP)
    ↓
Event persisted to PostgreSQL
    ↓
Orchestrator triggered
    ├── get_execution_state_batch() [~2ms]
    ├── get_transition_context_batch() [~3ms]
    ├── catalog_fetch() [~1ms cached, ~50ms uncached]
    └── Publish next command to NATS
    ↓
Worker claims command via NATS
    ↓
Worker executes...
```

Total orchestration overhead: ~10-50ms (optimized)

## References

- [Observability Services](./observability)
- [ClickHouse Queries](../../ci/manifests/clickhouse/performance-queries.sql)
- [Event Sync Playbook](../../automation/observability/event-sync.yaml)
