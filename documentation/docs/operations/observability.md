---
id: observability
title: Observability Services
sidebar_label: Observability
sidebar_position: 2
---

# Observability Services

NoETL includes three observability and data services for logs, metrics, traces, vector search, and event streaming.

## Overview

### Services

1. **ClickHouse** - OLAP database for logs, metrics, and traces
2. **Qdrant** - Vector database for embeddings and semantic search
3. **NATS JetStream** - Messaging and key-value store

### Quick Start

```bash
# Activate all services
noetl run automation/infrastructure/observability.yaml --set action=activate-all

# Check status
noetl run automation/infrastructure/observability.yaml --set action=status-all

# Health check
noetl run automation/infrastructure/observability.yaml --set action=health-all

# Deactivate all
noetl run automation/infrastructure/observability.yaml --set action=deactivate-all
```

## ClickHouse

### Overview

ClickHouse is a column-oriented database optimized for real-time analytics on logs, metrics, and traces.

### Access Points

| Interface | Port | Purpose |
|-----------|------|---------|
| HTTP | 30123 (NodePort) | Query interface, REST API |
| Native | 30900 (NodePort) | Native protocol (faster) |
| MCP Server | 8124 | Model Context Protocol for AI agents |

### Schema

Four main tables following OpenTelemetry format:

#### `observability.logs`
- **Purpose**: Application logs with trace correlation
- **TTL**: 30 days
- **Indexes**: TraceId (bloom filter), Severity, Service
- **Columns**: Timestamp, TraceId, SpanId, SeverityText, ServiceName, Body, Attributes

#### `observability.metrics`
- **Purpose**: Time-series metrics (Gauge, Sum, Histogram, Summary)
- **TTL**: 90 days
- **Indexes**: MetricName, Service
- **Columns**: Timestamp, MetricName, MetricType, ServiceName, Value, Attributes

#### `observability.traces`
- **Purpose**: Distributed traces with span relationships
- **TTL**: 30 days
- **Indexes**: TraceId (bloom filter), SpanName, Service, Duration
- **Columns**: Timestamp, TraceId, SpanId, ParentSpanId, SpanName, Duration, StatusCode, Events, Links

#### `observability.noetl_events`
- **Purpose**: NoETL-specific execution events
- **TTL**: 90 days
- **Indexes**: EventId, ExecutionId, EventType, Status
- **Columns**: Timestamp, EventId, ExecutionId, EventType, Status, StepName, Duration, ErrorMessage

### Materialized Views

Pre-aggregated analytics:

- **`error_rate_by_service`** - Hourly error counts per service
- **`avg_duration_by_span`** - Span performance statistics
- **`noetl_execution_stats`** - Execution metrics by type/status

### Common Queries

#### Recent Errors
```sql
SELECT 
  Timestamp,
  ServiceName,
  SeverityText,
  Body,
  TraceId
FROM observability.logs
WHERE SeverityNumber >= 17  -- ERROR level
  AND Timestamp >= now() - INTERVAL 1 HOUR
ORDER BY Timestamp DESC
LIMIT 100
```

#### Slow Traces
```sql
SELECT 
  Timestamp,
  ServiceName,
  SpanName,
  Duration / 1000000 AS DurationMs,
  TraceId
FROM observability.traces
WHERE Duration > 1000000000  -- > 1 second
  AND Timestamp >= now() - INTERVAL 1 HOUR
ORDER BY Duration DESC
LIMIT 50
```

#### NoETL Execution Failures
```sql
SELECT 
  Timestamp,
  ExecutionId,
  EventType,
  StepName,
  ErrorMessage
FROM observability.noetl_events
WHERE Status = 'FAILED'
  AND Timestamp >= now() - INTERVAL 1 DAY
ORDER BY Timestamp DESC
```

### Tasks

```bash
# Deployment
noetl run automation/infrastructure/clickhouse.yaml --set action=deploy
noetl run automation/infrastructure/clickhouse.yaml --set action=undeploy
noetl run automation/infrastructure/clickhouse.yaml --set action=restart

# Monitoring
noetl run automation/infrastructure/clickhouse.yaml --set action=status
noetl run automation/infrastructure/clickhouse.yaml --set action=logs
noetl run automation/infrastructure/clickhouse.yaml --set action=health

# Connection
noetl run automation/infrastructure/clickhouse.yaml --set action=connect
noetl run automation/infrastructure/clickhouse.yaml --set action=query --set query="SELECT 1"
noetl run automation/infrastructure/clickhouse.yaml --set action=port-forward

# Maintenance
noetl run automation/infrastructure/clickhouse.yaml --set action=optimize
noetl run automation/infrastructure/clickhouse.yaml --set action=clean-data
noetl run automation/infrastructure/clickhouse.yaml --set action=test
```

### Performance Features

- **ZSTD Compression**: 10:1 typical compression ratio
- **Bloom Filters**: High-cardinality field indexes (TraceId, EventId)
- **Set Indexes**: Low-cardinality field indexes (Service, EventType)
- **MinMax Indexes**: Numeric range queries (Duration)
- **Date Partitioning**: Efficient TTL management and query pruning

### Resources

- **Memory**: 512Mi-2Gi
- **CPU**: 500m-2000m
- **Storage**: 6Gi (5Gi data + 1Gi logs)

## Qdrant

### Overview

Qdrant is a vector similarity search engine for embeddings, semantic search, and RAG applications.

### Access Points

| Interface | Port | Purpose |
|-----------|------|---------|
| HTTP API | 30633 (NodePort) | REST API for collections, vectors |
| gRPC API | 30634 (NodePort) | High-performance gRPC interface |

### Features

- **Vector Similarity Search**: Cosine, Euclidean, Dot product
- **Extended Filtering**: Attribute-based filtering with vector search
- **On-Disk Payload**: Efficient storage for large payloads
- **Collections**: Isolated vector spaces with custom schemas
- **Snapshots**: Point-in-time backups

### API Examples

#### Create Collection
```bash
curl -X PUT "http://localhost:30633/collections/embeddings" \
  -H "Content-Type: application/json" \
  -d '{
    "vectors": {
      "size": 384,
      "distance": "Cosine"
    }
  }'
```

#### Insert Vectors
```bash
curl -X PUT "http://localhost:30633/collections/embeddings/points" \
  -H "Content-Type: application/json" \
  -d '{
    "points": [
      {
        "id": 1,
        "vector": [0.1, 0.2, 0.3, ...],
        "payload": {"text": "example document"}
      }
    ]
  }'
```

#### Search Similar Vectors
```bash
curl -X POST "http://localhost:30633/collections/embeddings/points/search" \
  -H "Content-Type: application/json" \
  -d '{
    "vector": [0.1, 0.2, 0.3, ...],
    "limit": 10,
    "with_payload": true
  }'
```

#### Filter + Search
```bash
curl -X POST "http://localhost:30633/collections/embeddings/points/search" \
  -H "Content-Type: application/json" \
  -d '{
    "vector": [0.1, 0.2, 0.3, ...],
    "limit": 10,
    "filter": {
      "must": [
        {"key": "category", "match": {"value": "documentation"}}
      ]
    }
  }'
```

### Tasks

```bash
# Deployment
noetl run automation/infrastructure/qdrant.yaml --set action=deploy
noetl run automation/infrastructure/qdrant.yaml --set action=undeploy
noetl run automation/infrastructure/qdrant.yaml --set action=restart

# Monitoring
noetl run automation/infrastructure/qdrant.yaml --set action=status
noetl run automation/infrastructure/qdrant.yaml --set action=logs
noetl run automation/infrastructure/qdrant.yaml --set action=health

# Operations
noetl run automation/infrastructure/qdrant.yaml --set action=collections
noetl run automation/infrastructure/qdrant.yaml --set action=connect
noetl run automation/infrastructure/qdrant.yaml --set action=port-forward
noetl run automation/infrastructure/qdrant.yaml --set action=test
```

### Configuration

Default settings (ConfigMap):
- HTTP port: 6333
- gRPC port: 6334
- Storage path: `/qdrant/storage`
- On-disk payload: enabled
- Telemetry: disabled

### Resources

- **Memory**: 512Mi-2Gi
- **CPU**: 250m-1000m
- **Storage**: 5Gi

## NATS JetStream

### Overview

NATS with JetStream provides messaging, streaming, and key-value store capabilities.

### Access Points

| Interface | Port | Purpose |
|-----------|------|---------|
| Client | 30422 (NodePort) | NATS messaging protocol |
| Monitoring | 30822 (NodePort) | HTTP monitoring dashboard |

### Features

#### JetStream
- **Stream Persistence**: Durable message storage (5GB)
- **Message Replay**: Replay from any point in stream
- **Consumer Groups**: Load balancing across consumers
- **Acknowledgments**: At-least-once delivery

#### Key-Value Store
- **Distributed KV**: Cluster-wide key-value operations
- **TTL Support**: Automatic expiration
- **Watch/Subscribe**: Real-time updates on changes
- **Buckets**: Isolated KV namespaces

### Credentials

- **Default Account**: `noetl/noetl`
- **System Account**: `sys/sys`

### CLI Examples

#### Basic Messaging

```bash
# Publish message
nats -s nats://noetl:noetl@localhost:30422 pub events.test "Hello World"

# Subscribe to subject
nats -s nats://noetl:noetl@localhost:30422 sub events.test
```

#### Stream Operations

```bash
# Create stream
nats -s nats://noetl:noetl@localhost:30422 stream add \
  --subjects="events.*" \
  --storage=file \
  --retention=limits \
  --max-age=24h \
  mystream

# List streams
nats -s nats://noetl:noetl@localhost:30422 stream list

# View stream info
nats -s nats://noetl:noetl@localhost:30422 stream info mystream
```

#### Key-Value Operations

```bash
# Create KV bucket
nats -s nats://noetl:noetl@localhost:30422 kv add config

# Put value
nats -s nats://noetl:noetl@localhost:30422 kv put config key "value"

# Get value
nats -s nats://noetl:noetl@localhost:30422 kv get config key

# List keys
nats -s nats://noetl:noetl@localhost:30422 kv ls config

# Watch for changes
nats -s nats://noetl:noetl@localhost:30422 kv watch config
```

### Tasks

```bash
# Deployment
noetl run automation/infrastructure/nats.yaml --set action=deploy
noetl run automation/infrastructure/nats.yaml --set action=undeploy
noetl run automation/infrastructure/nats.yaml --set action=restart

# Monitoring
noetl run automation/infrastructure/nats.yaml --set action=status
noetl run automation/infrastructure/nats.yaml --set action=logs
noetl run automation/infrastructure/nats.yaml --set action=health

# Operations
noetl run automation/infrastructure/nats.yaml --set action=streams
noetl run automation/infrastructure/nats.yaml --set action=monitoring
noetl run automation/infrastructure/nats.yaml --set action=connect
noetl run automation/infrastructure/nats.yaml --set action=port-forward
noetl run automation/infrastructure/nats.yaml --set action=test
```

### Configuration

Default settings (ConfigMap):
- Client port: 4222
- HTTP monitoring: 8222
- JetStream storage: `/data/jetstream`
- Max memory: 1GB
- Max file store: 5GB

### Resources

- **Memory**: 512Mi-2Gi
- **CPU**: 250m-1000m
- **Storage**: 5Gi

## Unified Operations

### Activate/Deactivate All

```bash
# Activate all observability services
noetl run automation/infrastructure/observability.yaml --set action=activate-all

# Deactivate all observability services
noetl run automation/infrastructure/observability.yaml --set action=deactivate-all
```

### Individual Service Control

```bash
# Activate individual services
noetl run automation/infrastructure/clickhouse.yaml --set action=deploy
noetl run automation/infrastructure/qdrant.yaml --set action=deploy
noetl run automation/infrastructure/nats.yaml --set action=deploy

# Deactivate individual services
noetl run automation/infrastructure/clickhouse.yaml --set action=undeploy
noetl run automation/infrastructure/qdrant.yaml --set action=undeploy
noetl run automation/infrastructure/nats.yaml --set action=undeploy
```

### Status and Health

```bash
# Check all services status
noetl run automation/infrastructure/observability.yaml --set action=status-all

# Health check all services
noetl run automation/infrastructure/observability.yaml --set action=health-all

# Restart all services
noetl run automation/infrastructure/observability.yaml --set action=restart-all
```

### Port Forwarding

```bash
# ClickHouse
noetl run automation/infrastructure/clickhouse.yaml --set action=port-forward
noetl run automation/infrastructure/clickhouse.yaml --set action=port-forward-mcp

# Qdrant
noetl run automation/infrastructure/qdrant.yaml --set action=port-forward

# NATS
noetl run automation/infrastructure/nats.yaml --set action=port-forward
```

## Performance Analysis

NoETL includes built-in tools for analyzing playbook execution performance and identifying bottlenecks.

### Event Sync Playbook

The event sync playbook exports execution events from PostgreSQL to ClickHouse for analysis:

```bash
# Show available actions
noetl run automation/observability/event-sync.yaml --set action=help

# Sync events from last 24 hours to ClickHouse
noetl run automation/observability/event-sync.yaml --set action=sync

# Sync events from last 1 hour with larger batch
noetl run automation/observability/event-sync.yaml --set action=sync --set since_hours=1 --set batch_size=5000

# Count events in both databases
noetl run automation/observability/event-sync.yaml --set action=count

# Verify sync between databases
noetl run automation/observability/event-sync.yaml --set action=verify
```

### PostgreSQL-Based Analysis (No ClickHouse Required)

For immediate diagnosis without deploying ClickHouse:

```bash
# Find time gaps between events (bottleneck detection)
noetl run automation/observability/event-sync.yaml --set action=analyze-gaps --set since_hours=1

# Find slowest executions
noetl run automation/observability/event-sync.yaml --set action=analyze-slow --set since_hours=1
```

### Direct SQL Analysis

Run these queries against PostgreSQL for detailed analysis:

#### Find Slowest Executions
```sql
SELECT
    e.execution_id,
    c.path as playbook_path,
    COUNT(*) as event_count,
    ROUND(EXTRACT(EPOCH FROM (MAX(e.created_at) - MIN(e.created_at)))::numeric, 2) as duration_seconds
FROM noetl.event e
LEFT JOIN noetl.catalog c ON e.catalog_id = c.catalog_id
GROUP BY e.execution_id, c.path
ORDER BY duration_seconds DESC
LIMIT 20;
```

#### Analyze Event Transition Delays
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
    ROUND(percentile_cont(0.95) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (created_at - prev_time)))::numeric, 3) as p95_sec
FROM transitions
WHERE prev_event IS NOT NULL
GROUP BY prev_event, event_type
HAVING COUNT(*) > 5
ORDER BY avg_sec DESC;
```

#### Find Bottleneck Gaps (>2 seconds)
```sql
WITH event_gaps AS (
    SELECT
        execution_id,
        event_type,
        node_name,
        created_at,
        LAG(created_at) OVER (PARTITION BY execution_id ORDER BY created_at) as prev_time,
        LAG(event_type) OVER (PARTITION BY execution_id ORDER BY created_at) as prev_event_type
    FROM noetl.event
    WHERE created_at > NOW() - INTERVAL '1 hour'
)
SELECT
    execution_id,
    prev_event_type as from_event,
    event_type as to_event,
    node_name,
    ROUND(EXTRACT(EPOCH FROM (created_at - prev_time))::numeric, 2) as gap_seconds
FROM event_gaps
WHERE created_at - prev_time > INTERVAL '2 seconds'
ORDER BY gap_seconds DESC
LIMIT 30;
```

### ClickHouse Performance Queries

After syncing events to ClickHouse, use these queries for advanced analysis:

```bash
# Connect to ClickHouse
kubectl exec -n clickhouse <pod> -- clickhouse-client
```

#### Execution Duration Distribution
```sql
SELECT
    toStartOfHour(Timestamp) AS hour,
    EventType,
    count() AS event_count,
    round(avg(Duration), 2) AS avg_duration_ms,
    round(quantile(0.95)(Duration), 2) AS p95_ms
FROM observability.noetl_events
WHERE Timestamp >= now() - INTERVAL 24 HOUR
GROUP BY hour, EventType
ORDER BY hour DESC, avg_duration_ms DESC;
```

#### Bottleneck Detection (Gap Analysis)
```sql
SELECT
    ExecutionId,
    prev_event_type,
    EventType AS curr_event_type,
    gap_ms
FROM (
    SELECT
        ExecutionId,
        EventType,
        lagInFrame(EventType, 1, '') OVER (
            PARTITION BY ExecutionId ORDER BY Timestamp
        ) AS prev_event_type,
        dateDiff('millisecond',
            lagInFrame(Timestamp, 1, Timestamp) OVER (
                PARTITION BY ExecutionId ORDER BY Timestamp
            ),
            Timestamp
        ) AS gap_ms
    FROM observability.noetl_events
    WHERE Timestamp >= now() - INTERVAL 1 HOUR
)
WHERE gap_ms > 5000
ORDER BY gap_ms DESC
LIMIT 50;
```

Full query library available at: `ci/manifests/clickhouse/performance-queries.sql`

### Performance Logs

The orchestrator emits `[PERF]` logs for monitoring. View them with:

```bash
# View server performance logs
kubectl logs -n noetl deployment/noetl-server | grep '\[PERF\]'

# Watch live
kubectl logs -n noetl deployment/noetl-server -f | grep '\[PERF\]'
```

Key metrics logged:
- `get_execution_state_batch` - State query time
- `get_transition_context_batch` - Transition query time
- `catalog_fetch` - Catalog/playbook fetch time
- `evaluate_execution` - Total orchestration time

Example output:
```
[PERF] get_execution_state_batch: 2.3ms
[PERF] evaluate_execution total: 2.6ms
```

### Key Performance Indicators

| Metric | Healthy | Warning | Critical |
|--------|---------|---------|----------|
| `command.completed → command.claimed` | &lt;100ms | 100ms-1s | &gt;1s |
| `evaluate_execution` total | &lt;50ms | 50-500ms | &gt;500ms |
| `catalog_fetch` | &lt;10ms (cached) | 10-100ms | &gt;100ms |
| Event count per execution | &lt;100 | 100-500 | &gt;500 |

### Troubleshooting Slow Executions

1. **Check orchestrator delays:**
   ```bash
   kubectl logs -n noetl deployment/noetl-server | grep '\[PERF\]' | tail -50
   ```

2. **Analyze event gaps:**
   ```bash
   noetl run automation/observability/event-sync.yaml --set action=analyze-gaps
   ```

3. **Check catalog cache stats:**
   The catalog cache has 100 entries with 5-minute TTL. Cache misses cause DB lookups.

4. **Monitor state reconstruction:**
   High event counts per execution can slow down state reconstruction. Consider archiving completed executions.

## Integration with NoETL

### Bootstrap Integration

All services automatically deploy with:

```bash
noetl run automation/setup/bootstrap.yaml
# or
noetl run automation/main.yaml --set target=bootstrap
```

### Verification

```bash
# Verify all components
noetl run automation/infrastructure/observability.yaml --set action=status-all

# Shows:
# - ClickHouse namespace and deployment status
# - Qdrant namespace and pod status
# - NATS namespace and pod status
```

### Service Endpoints

After deployment, all endpoints are displayed:

```
NoETL started!
  UI: http://localhost:8083
  Grafana: kubectl port-forward -n vmstack svc/vmstack-grafana 3000:80
  ClickHouse HTTP: localhost:30123 (NodePort)
  ClickHouse Native: localhost:30900 (NodePort)
  Qdrant HTTP: localhost:30633 (NodePort)
  Qdrant gRPC: localhost:30634 (NodePort)
  NATS Client: localhost:30422 (NodePort)
  NATS Monitoring: localhost:30822 (NodePort)
```

## Resource Requirements

### Total Resources

- **Memory**: ~3.5-6Gi (combined)
- **CPU**: ~2-4 cores (combined)
- **Storage**: ~16Gi (combined)

### Per-Service Breakdown

| Service | Memory | CPU | Storage |
|---------|--------|-----|---------|
| ClickHouse | 512Mi-2Gi | 500m-2000m | 6Gi |
| Qdrant | 512Mi-2Gi | 250m-1000m | 5Gi |
| NATS | 512Mi-2Gi | 250m-1000m | 5Gi |

## Troubleshooting

### Service Not Starting

```bash
# Check pod status
kubectl get pods -n clickhouse
kubectl get pods -n qdrant
kubectl get pods -n nats

# Check events
kubectl get events -n clickhouse --sort-by='.lastTimestamp'

# Describe pod
kubectl describe pod <pod-name> -n <namespace>

# Check logs
kubectl logs -n clickhouse deployment/clickhouse -f
kubectl logs -n qdrant deployment/qdrant -f
kubectl logs -n nats deployment/nats -f
```

### Connection Issues

```bash
# Test from within cluster
kubectl run -it --rm test --image=busybox --restart=Never -- \
  wget -qO- http://clickhouse.clickhouse.svc.cluster.local:8123

kubectl run -it --rm test --image=busybox --restart=Never -- \
  wget -qO- http://qdrant.qdrant.svc.cluster.local:6333

kubectl run -it --rm test --image=busybox --restart=Never -- \
  nc -zv nats.nats.svc.cluster.local 4222
```

### Storage Issues

```bash
# Check PVCs
kubectl get pvc -n clickhouse
kubectl get pvc -n qdrant
kubectl get pvc -n nats

# Check storage usage
kubectl exec -n clickhouse <pod> -- df -h /qdrant/storage
kubectl exec -n qdrant <pod> -- df -h /qdrant/storage
kubectl exec -n nats <pod> -- df -h /data
```

### Health Checks

```bash
# ClickHouse
curl http://localhost:30123

# Qdrant
curl http://localhost:30633/healthz

# NATS
curl http://localhost:30822/healthz
```

## Production Considerations

### ClickHouse

- Use multi-node clusters for replication
- Configure S3 backups
- Tune partitioning and TTL policies
- Monitor query performance
- Set up proper security (users, roles, quotas)

### Qdrant

- Scale horizontally with sharding
- Configure snapshots for backups
- Optimize index parameters for your use case
- Monitor memory usage
- Enable authentication in production

### NATS

- Use clustering for high availability
- Configure stream replication
- Set appropriate retention policies
- Monitor JetStream usage
- Enable TLS for secure communication

## References

- [ClickHouse Documentation](https://clickhouse.com/docs)
- [Qdrant Documentation](https://qdrant.tech/documentation/)
- [NATS Documentation](https://docs.nats.io/)
- [OpenTelemetry](https://opentelemetry.io/)
- [CI Setup Guide](./ci-setup)
