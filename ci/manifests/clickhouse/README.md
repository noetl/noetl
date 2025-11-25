# ClickHouse Integration for NoETL

This directory contains Kubernetes manifests for deploying ClickHouse observability stack:

## Components

### 1. ClickHouse Operator
- **File**: `operator.yaml`
- **Description**: Altinity ClickHouse Kubernetes Operator for managing ClickHouse clusters
- **Reference**: https://github.com/Altinity/clickhouse-operator

### 2. Custom Resource Definitions (CRDs)
- **File**: `crds.yaml`
- **Description**: ClickHouseInstallation, ClickHouseInstallationTemplate, ClickHouseOperatorConfiguration CRDs

### 3. ClickHouse Cluster
- **File**: `clickhouse-cluster.yaml`
- **Description**: Single-node ClickHouse cluster for local development
- **Features**:
  - HTTP interface on NodePort 30123
  - Native protocol on NodePort 30900
  - Default user with no password
  - Admin user with password "admin"
  - 5GB data volume, 1GB log volume

### 4. MCP Server
- **File**: `mcp-server.yaml`
- **Description**: Model Context Protocol server for ClickHouse integration
- **Reference**: https://github.com/ClickHouse/mcp-clickhouse
- **Port**: 8124 (ClusterIP)

### 5. Observability Schema
- **File**: `observability-schema.yaml`
- **Description**: OpenTelemetry-compatible schema for logs, metrics, traces
- **Tables**:
  - `observability.logs` - Application logs (30-day TTL)
  - `observability.metrics` - Time-series metrics (90-day TTL)
  - `observability.traces` - Distributed traces (30-day TTL)
  - `observability.noetl_events` - NoETL-specific events (90-day TTL)
- **Materialized Views**:
  - `error_rate_by_service` - Error rates per service
  - `avg_duration_by_span` - Span duration statistics
  - `noetl_execution_stats` - Execution metrics

## Quick Start

Deploy complete stack:
```bash
task clickhouse:deploy
```

Check status:
```bash
task clickhouse:status
```

Connect to ClickHouse CLI:
```bash
task clickhouse:connect
```

Run test queries:
```bash
task clickhouse:test
```

## Access

### HTTP Interface (Web UI, REST API)
```bash
# Via NodePort
curl http://localhost:30123

# Via port-forward
task clickhouse:port-forward
# Then access: http://localhost:8123
```

### Native Protocol (CLI, Drivers)
```bash
# Via NodePort
clickhouse-client --host localhost --port 30900

# Via port-forward
task clickhouse:port-forward
# Then: clickhouse-client --host localhost --port 9000
```

### MCP Server
```bash
task clickhouse:port-forward-mcp
# Then access: http://localhost:8124
```

## Common Tasks

View logs:
```bash
task clickhouse:logs              # ClickHouse server logs
task clickhouse:logs-operator     # Operator logs
task clickhouse:logs-mcp          # MCP server logs
```

Execute queries:
```bash
task clickhouse:query -- "SELECT version()"
task clickhouse:query -- "SHOW DATABASES"
task clickhouse:query -- "SELECT COUNT(*) FROM observability.logs"
```

Health check:
```bash
task clickhouse:health
```

Clean data (keeps schema):
```bash
task clickhouse:clean-data
```

Remove stack:
```bash
task clickhouse:undeploy
```

## Schema Details

### Logs Table
- OpenTelemetry format with TraceId/SpanId correlation
- Severity levels with bloom filter index
- 30-day TTL, partitioned by date

### Metrics Table
- Gauge, Sum, Histogram, Summary types
- Attributes and resource attributes for metadata
- 90-day TTL, partitioned by date

### Traces Table
- Full OpenTelemetry trace model
- Parent-child span relationships
- Events and links nested structures
- Duration index for performance queries
- 30-day TTL, partitioned by date

### NoETL Events Table
- Execution lifecycle events
- Step-level status tracking
- Error message capture
- Metadata for context
- 90-day TTL, partitioned by date

## Development

The MCP server deployment references a placeholder image. To build from source:

```bash
git clone https://github.com/ClickHouse/mcp-clickhouse.git
cd mcp-clickhouse
docker build -t clickhouse/mcp-server:latest .
kind load docker-image clickhouse/mcp-server:latest --name noetl-cluster
```

## References

- [ClickHouse Kubernetes Operator](https://github.com/Altinity/clickhouse-operator)
- [ClickHouse MCP Server](https://github.com/ClickHouse/mcp-clickhouse)
- [ClickHouse Observability](https://clickhouse.com/use-cases/observability)
- [OpenTelemetry](https://opentelemetry.io/)
