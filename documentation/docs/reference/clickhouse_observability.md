# ClickHouse Observability Integration

## Overview

NoETL now includes ClickHouse as an observability backend for storing and analyzing logs, metrics, and traces. This integration follows the OpenTelemetry standard and provides high-performance analytics for operational data.

## Architecture

### Components

1. **ClickHouse Operator**: Manages ClickHouse cluster lifecycle using Kubernetes CRDs
2. **ClickHouse Cluster**: Single-node cluster optimized for local development
3. **MCP Server**: Model Context Protocol server for AI agent integration
4. **Observability Schema**: OpenTelemetry-compatible tables and materialized views

### Data Flow

```
NoETL Events → OpenTelemetry Collector → ClickHouse → Grafana Dashboards
                                      ↓
                                  MCP Server → AI Agents
```

## Quick Start

### Deploy ClickHouse Stack

```bash
# Deploy all components
task clickhouse:deploy

# Verify deployment
task clickhouse:status
task clickhouse:test
```

### Connect to ClickHouse

```bash
# CLI access
task clickhouse:connect

# Execute query
task clickhouse:query -- "SELECT COUNT(*) FROM observability.logs"

# Port forward for local access
task clickhouse:port-forward  # HTTP:8123, Native:9000
```

## Schema

### Tables

#### `observability.logs`
OpenTelemetry logs with trace correlation:
- **Partition**: By date
- **TTL**: 30 days
- **Indexes**: TraceId (bloom filter), Severity, Service
- **Columns**: Timestamp, TraceId, SpanId, SeverityText, ServiceName, Body, Attributes

#### `observability.metrics`
Time-series metrics:
- **Partition**: By date
- **TTL**: 90 days
- **Indexes**: MetricName, Service
- **Columns**: Timestamp, MetricName, MetricType, ServiceName, Value, Attributes

#### `observability.traces`
Distributed traces:
- **Partition**: By date
- **TTL**: 30 days
- **Indexes**: TraceId (bloom filter), SpanName, Service, Duration
- **Columns**: Timestamp, TraceId, SpanId, ParentSpanId, SpanName, Duration, StatusCode, Events, Links

#### `observability.noetl_events`
NoETL-specific execution events:
- **Partition**: By date
- **TTL**: 90 days
- **Indexes**: EventId, ExecutionId, EventType, Status
- **Columns**: Timestamp, EventId, ExecutionId, EventType, Status, StepName, Duration, ErrorMessage

### Materialized Views

#### `error_rate_by_service`
Hourly error counts per service:
```sql
SELECT 
  toStartOfHour(Timestamp) AS Timestamp,
  ServiceName,
  ErrorCount,
  TotalCount,
  (ErrorCount / TotalCount) * 100 AS ErrorRate
FROM observability.error_rate_by_service
WHERE Timestamp >= now() - INTERVAL 1 DAY
ORDER BY Timestamp DESC, ErrorRate DESC
```

#### `avg_duration_by_span`
Span performance statistics:
```sql
SELECT 
  ServiceName,
  SpanName,
  avgMerge(AvgDuration) AS AvgDuration,
  maxMerge(MaxDuration) AS MaxDuration,
  minMerge(MinDuration) AS MinDuration
FROM observability.avg_duration_by_span
WHERE Timestamp >= now() - INTERVAL 1 HOUR
GROUP BY ServiceName, SpanName
ORDER BY AvgDuration DESC
```

#### `noetl_execution_stats`
Execution metrics:
```sql
SELECT 
  EventType,
  Status,
  EventCount,
  AvgDuration,
  MaxDuration
FROM observability.noetl_execution_stats
WHERE Timestamp >= now() - INTERVAL 1 DAY
ORDER BY EventCount DESC
```

## Common Queries

### Recent Errors
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

### Slow Traces
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

### NoETL Execution Failures
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

## Maintenance

### Optimize Tables
```bash
task clickhouse:optimize
```

### Clean Data (Keep Schema)
```bash
task clickhouse:clean-data
```

### Check Health
```bash
task clickhouse:health
```

### View Logs
```bash
task clickhouse:logs              # ClickHouse server
task clickhouse:logs-operator     # Operator
task clickhouse:logs-mcp          # MCP server
```

## MCP Server Integration

The ClickHouse MCP (Model Context Protocol) server provides AI agents with direct access to observability data:

### Access MCP Server
```bash
# Port forward
task clickhouse:port-forward-mcp

# Test endpoint
curl http://localhost:8124/health
```

### Configuration
MCP server configuration in `ci/manifests/clickhouse/mcp-server.yaml`:
```json
{
  "clickhouse": {
    "host": "clickhouse.clickhouse.svc.cluster.local",
    "port": 8123,
    "username": "default",
    "password": "",
    "database": "default"
  },
  "server": {
    "host": "0.0.0.0",
    "port": 8124
  }
}
```

## Performance Tuning

### Compression
Tables use ZSTD compression with Delta encoding for timestamps. Typical compression ratio: 10:1 for logs.

### Indexing
- Bloom filters on high-cardinality fields (TraceId, EventId)
- Set indexes on low-cardinality fields (Service, EventType)
- MinMax indexes on numeric ranges (Duration)

### Partitioning
All tables partitioned by date for efficient TTL management and query pruning.

### TTL Policies
- Logs: 30 days
- Metrics: 90 days
- Traces: 30 days
- NoETL Events: 90 days

Adjust in manifests as needed for your retention requirements.

## Troubleshooting

### Operator Not Starting
```bash
task clickhouse:logs-operator
kubectl describe deployment clickhouse-operator -n clickhouse
```

### Cluster Not Ready
```bash
kubectl get chi -n clickhouse
kubectl describe chi noetl-clickhouse -n clickhouse
task clickhouse:logs
```

### Schema Not Initialized
```bash
task clickhouse:connect
# Then run: SHOW DATABASES;
# If observability missing, re-apply schema:
task clickhouse:deploy-schema
```

### Connection Issues
```bash
# Check service endpoints
kubectl get svc -n clickhouse

# Test from within cluster
kubectl run -it --rm clickhouse-test --image=clickhouse/clickhouse-client:latest --restart=Never -- \
  clickhouse-client --host clickhouse.clickhouse.svc.cluster.local --query="SELECT 1"
```

## References

- [ClickHouse Documentation](https://clickhouse.com/docs)
- [ClickHouse Operator](https://github.com/Altinity/clickhouse-operator)
- [ClickHouse MCP Server](https://github.com/ClickHouse/mcp-clickhouse)
- [OpenTelemetry](https://opentelemetry.io/)
- [ClickHouse Observability Use Case](https://clickhouse.com/use-cases/observability)
