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
task clickhouse:logs
task qdrant:logs
task nats:logs
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
