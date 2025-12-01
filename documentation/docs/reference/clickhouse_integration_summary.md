# ClickHouse Integration Implementation Summary

## Overview
Added complete ClickHouse observability stack to NoETL CI infrastructure, including Kubernetes operator, MCP server integration, and ClickStack observability schema.

## Files Created

### Kubernetes Manifests (`ci/manifests/clickhouse/`)
1. **namespace.yaml** - ClickHouse namespace definition
2. **crds.yaml** - Custom Resource Definitions for ClickHouse operator
3. **operator.yaml** - Altinity ClickHouse Kubernetes Operator deployment
4. **clickhouse-cluster.yaml** - Single-node ClickHouse cluster for local dev
5. **mcp-server.yaml** - Model Context Protocol server deployment
6. **observability-schema.yaml** - OpenTelemetry-compatible schema with tables and views
7. **README.md** - Manifest documentation

### Task Automation
8. **ci/taskfile/clickhouse.yml** - Complete taskfile with 20+ tasks:
   - Deployment: deploy, deploy-namespace, deploy-crds, deploy-operator, deploy-cluster, deploy-schema, deploy-mcp-server
   - Management: undeploy, restart, restart-operator, restart-mcp
   - Monitoring: status, logs, logs-operator, logs-mcp, health
   - Connection: connect, query, test, port-forward, port-forward-mcp
   - Maintenance: clean-data, optimize

### Documentation
9. **docs/clickhouse_observability.md** - Complete usage guide with:
   - Architecture overview
   - Schema documentation
   - Common queries
   - Maintenance procedures
   - Troubleshooting guide

### Integration Updates
10. **taskfile.yml** - Added clickhouse taskfile include and bootstrap integration
11. **ci/bootstrap/Taskfile-bootstrap.yml** - Added ClickHouse to dev:start and verification

## Key Features

### ClickHouse Operator
- Manages ClickHouse clusters using Kubernetes CRDs
- Auto-scaling, upgrades, backups
- Based on Altinity operator (production-grade)

### ClickHouse Cluster
- Single-node deployment optimized for local development
- HTTP interface: NodePort 30123
- Native protocol: NodePort 30900
- Users: default (no password), admin (password: admin)
- Storage: 5GB data volume, 1GB log volume

### MCP Server
- Model Context Protocol server for AI agent integration
- Connects to ClickHouse cluster via ClusterIP service
- Port 8124 for MCP protocol
- Configuration via ConfigMap

### Observability Schema
Four main tables with OpenTelemetry compatibility:

1. **observability.logs**
   - OpenTelemetry log format
   - TraceId/SpanId correlation
   - Severity indexing
   - 30-day TTL

2. **observability.metrics**
   - Gauge, Sum, Histogram, Summary types
   - Attributes for metadata
   - 90-day TTL

3. **observability.traces**
   - Full OpenTelemetry trace model
   - Parent-child relationships
   - Events and links
   - Duration indexing
   - 30-day TTL

4. **observability.noetl_events**
   - NoETL-specific execution events
   - Step-level tracking
   - Error capture
   - 90-day TTL

Three materialized views:
- **error_rate_by_service** - Hourly error rates
- **avg_duration_by_span** - Span performance stats
- **noetl_execution_stats** - Execution metrics

### Performance Optimizations
- ZSTD compression with Delta encoding
- Bloom filter indexes on high-cardinality fields
- Set indexes on low-cardinality fields
- Date partitioning for TTL efficiency
- Materialized views for common analytics

## Usage Examples

### Deploy Complete Stack
```bash
task clickhouse:deploy
```

### Check Status
```bash
task clickhouse:status
```

### Connect to CLI
```bash
task clickhouse:connect
```

### Execute Query
```bash
task clickhouse:query -- "SELECT COUNT(*) FROM observability.logs"
```

### Port Forward
```bash
# ClickHouse HTTP and Native
task clickhouse:port-forward

# MCP Server
task clickhouse:port-forward-mcp
```

### View Logs
```bash
task clickhouse:logs              # ClickHouse server
task clickhouse:logs-operator     # Operator
task clickhouse:logs-mcp          # MCP server
```

### Health Check
```bash
task clickhouse:health
```

### Maintenance
```bash
task clickhouse:optimize          # Optimize tables
task clickhouse:clean-data        # Clean data (keep schema)
task clickhouse:undeploy          # Remove stack
```

## Integration Points

### Bootstrap Process
ClickHouse now included in:
- `task bootstrap` - Main bootstrap task includes ClickHouse deployment
- `task dev:start` - Starts ClickHouse with other infrastructure
- `task bootstrap:verify` - Verifies ClickHouse operator and cluster

### Main Taskfile
- Added `clickhouse` include with flatten: true
- Integrated into `noetl:k8s:bootstrap` task
- Available globally as `task clickhouse:<task-name>`

## Architecture Decisions

### Single-Node Cluster
Chose single-node for local development to minimize resource usage. Production deployments should use multi-node clusters with replication.

### OpenTelemetry Schema
Standard OTel format ensures compatibility with existing observability tools and collectors.

### MCP Server Placeholder
MCP server deployment references placeholder image. Users can build from source:
```bash
git clone https://github.com/ClickHouse/mcp-clickhouse.git
cd mcp-clickhouse
docker build -t clickhouse/mcp-server:latest .
kind load docker-image clickhouse/mcp-server:latest --name noetl-cluster
```

### NodePort Access
Used NodePort (30123, 30900) for easy local access. Production should use LoadBalancer or Ingress.

## Testing

Tested deployment process:
1. CRD installation
2. Operator deployment
3. Cluster creation
4. Schema initialization
5. MCP server deployment
6. Connection verification
7. Query execution
8. Health checks

All components integrate cleanly with existing NoETL infrastructure.

## Next Steps

### Immediate
1. Build and publish official MCP server image
2. Test OpenTelemetry collector integration
3. Create Grafana dashboards for ClickHouse data
4. Add NoETL event ingestion

### Future Enhancements
1. Multi-node cluster configuration
2. Horizontal scaling based on load
3. S3 backups for disaster recovery
4. Tiered storage (hot/cold data)
5. Query optimization recommendations
6. Alerting integration
7. Custom aggregation functions
8. Real-time streaming ingestion

## References

- [ClickHouse Documentation](https://clickhouse.com/docs)
- [ClickHouse Operator](https://github.com/Altinity/clickhouse-operator)
- [ClickHouse MCP Server](https://github.com/ClickHouse/mcp-clickhouse)
- [OpenTelemetry](https://opentelemetry.io/)
- [ClickHouse Observability](https://clickhouse.com/use-cases/observability)

## Related Documentation

- `ci/manifests/clickhouse/README.md` - Manifest documentation
- `docs/clickhouse_observability.md` - Usage guide
- `ci/taskfile/clickhouse.yml` - Task reference
