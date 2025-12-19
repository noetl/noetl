# NoETL Metrics Implementation Guide

## Overview

NoETL now includes comprehensive metrics collection and reporting functionality for both workers and servers. This implementation provides a centralized metrics system that integrates with the existing observability stack.

## Architecture

### Server-Centric Design
- Workers report metrics to the server via HTTP API
- Server collects its own metrics and worker metrics
- All metrics stored in PostgreSQL `noetl.metric` table
- Server exposes Prometheus-compatible metrics endpoint
- No separate worker APIs required

### Metrics Collection
- **System Metrics**: CPU, memory, process stats via `psutil`
- **Worker Metrics**: Active tasks, queue size, worker status
- **Server Metrics**: Connected workers, queue depth, API stats
- **Custom Metrics**: Extensible framework for application-specific metrics

## Configuration

### Environment Variables

#### Worker Configuration
```bash
# Worker metrics reporting interval (seconds)
NOETL_WORKER_METRICS_INTERVAL=60

# Worker heartbeat interval (includes metrics)
NOETL_WORKER_HEARTBEAT_INTERVAL=15

# Worker pool identification
NOETL_WORKER_POOL_NAME=worker-cpu
NOETL_WORKER_ID=unique-worker-id
```

#### Server Configuration
```bash
# Server metrics reporting interval (seconds)
NOETL_SERVER_METRICS_INTERVAL=60

# Server identification
NOETL_SERVER_NAME=noetl-server
NOETL_SERVER_URL=http://localhost:8082
```

## API Endpoints

### Metrics Reporting
```
POST /api/metrics/report
```
Workers and external systems can report metrics to this endpoint.

**Request Body:**
```json
{
    "component_name": "worker-cpu-01",
    "component_type": "worker_pool",
    "metrics": [
        {
            "metric_name": "noetl_system_cpu_usage_percent",
            "metric_type": "gauge",
            "metric_value": 45.2,
            "timestamp": "2024-01-01T12:00:00Z",
            "labels": {
                "component": "worker-cpu-01",
                "hostname": "node-1"
            },
            "help_text": "CPU usage percentage",
            "unit": "percent"
        }
    ]
}
```

### Metrics Query
```
GET /api/metrics/query?component_name=worker-cpu-01&metric_name=cpu_usage
```
Query stored metrics with filtering options.

### Self-Report
```
POST /api/metrics/self-report?component_name=server
```
Server or worker reports its own system metrics.

### Prometheus Export
```
GET /api/metrics/prometheus
```
Export all metrics in Prometheus format for scraping.

## Database Schema

The `noetl.metrics` table stores all collected metrics:

```sql
CREATE TABLE noetl.metrics (
    metric_id BIGINT PRIMARY KEY,
    runtime_id BIGINT REFERENCES noetl.runtime(runtime_id),
    metric_name VARCHAR(255) NOT NULL,
    metric_type VARCHAR(50) NOT NULL, -- gauge, counter, histogram, summary
    metric_value DOUBLE PRECISION NOT NULL,
    labels JSONB,
    help_text TEXT,
    unit VARCHAR(50),
    timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

## Worker Implementation

### Automatic Metrics Collection
Workers automatically collect and report metrics during heartbeat cycles:

```python
# ScalableQueueWorkerPool reports metrics every heartbeat
# QueueWorker reports metrics based on NOETL_WORKER_METRICS_INTERVAL

# Collected metrics include:
# - noetl_system_cpu_usage_percent
# - noetl_system_memory_usage_percent  
# - noetl_process_memory_rss_bytes
# - noetl_worker_active_tasks
# - noetl_worker_queue_size
```

### Custom Worker Metrics
Workers can report custom metrics via the server API:

```python
import httpx
import datetime

async def report_custom_metric():
    payload = {
        "component_name": "my-worker",
        "component_type": "worker_pool",
        "metrics": [{
            "metric_name": "custom_work_items_processed",
            "metric_type": "counter",
            "metric_value": 150,
            "timestamp": datetime.datetime.now().isoformat(),
            "labels": {"worker_type": "batch_processor"},
            "help_text": "Number of work items processed",
            "unit": "items"
        }]
    }
    
    async with httpx.AsyncClient() as client:
        await client.post("http://server:8082/api/metrics/report", json=payload)
```

## Server Implementation

### Automatic Server Metrics
The server automatically reports its own metrics during the runtime sweeper cycle:

```python
# Server metrics include:
# - System metrics (CPU, memory)
# - noetl_server_active_workers
# - noetl_server_queue_size
# - noetl_uptime_seconds
```

### Metrics Storage
All reported metrics are automatically:
1. Validated against component registration in `runtime` table
2. Stored in `metrics` table with proper foreign key relationships
3. Available via query API and Prometheus export

## Integration with Observability Stack

### VictoriaMetrics Integration
```yaml
# VMPodScrape or ServiceMonitor for Kubernetes
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMPodScrape
metadata:
  name: noetl-metrics
spec:
  selector:
    matchLabels:
      app: noetl-server
  podMetricsEndpoints:
  - port: "8082"
    path: /api/metrics/prometheus
```

### Grafana Dashboards
The metrics can be visualized in Grafana using VictoriaMetrics as data source:

- **System Metrics**: CPU, memory usage across all components
- **Worker Metrics**: Active workers, task distribution, queue depth
- **Server Metrics**: API performance, component health
- **Custom Metrics**: Application-specific measurements

## Testing

Run the integration test to verify metrics functionality:

```bash
cd .
python test_metrics_integration.py
```

This tests:
- Database schema creation
- API endpoint functionality  
- Worker metrics collection
- Prometheus export format

## Migration from Existing Systems

### From External Metrics Services
If migrating from Prometheus/VictoriaMetrics direct collection:

1. Update scrape configs to target NoETL server `/api/metrics/prometheus`
2. Workers automatically report via heartbeat - no config changes needed
3. Custom metrics can be sent via `/api/metrics/report` API

### From Application Metrics
If you have existing application metrics:

1. Use the `/api/metrics/report` API to send them to NoETL
2. Metrics will be stored centrally and exported to observability stack
3. Queries can combine NoETL system metrics with application metrics

## Troubleshooting

### Worker Not Reporting Metrics
1. Check `NOETL_WORKER_METRICS_INTERVAL` environment variable
2. Verify worker can reach server API endpoint
3. Check worker logs for metrics reporting errors
4. Ensure worker is registered in `runtime` table

### Server Metrics Missing
1. Check `NOETL_SERVER_METRICS_INTERVAL` environment variable  
2. Verify server runtime sweeper is running
3. Check server logs for metrics collection errors
4. Ensure PostgreSQL connection is healthy

### Prometheus Scraping Issues
1. Verify `/api/metrics/prometheus` endpoint is accessible
2. Check Prometheus scrape configuration
3. Ensure metrics exist in database via `/api/metrics/query`
4. Check VictoriaMetrics scrape config if using VM stack

### Database Performance
1. Monitor `noetl.metrics` table size growth
2. Consider partitioning by timestamp for large deployments
3. Set up automated cleanup for old metrics if needed
4. Index on commonly queried columns (component_name, timestamp)

## Future Enhancements

- **Time-Series Migration**: Framework for migrating to dedicated TSDB
- **Metrics Aggregation**: Pre-computed summaries for performance
- **Alert Integration**: Built-in alerting based on metric thresholds
- **Distributed Tracing**: Correlation between metrics and execution traces