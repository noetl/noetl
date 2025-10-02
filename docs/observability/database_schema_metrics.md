# NoETL Metrics Table Schema

## Overview

The `noetl.metric` table has been added to the NoETL PostgreSQL schema to centralize metrics collection from both workers and servers. The live implementation uses a partitioned parent table (daily partitions by created_at) with a 1‑day default TTL and a fast cleanup routine that drops expired partitions. This provides a unified storage location for all NoETL component metrics with efficient retention management before potential migration to dedicated time-series storage.

## Table Structure (legacy non-partitioned example)

```sql
CREATE TABLE IF NOT EXISTS noetl.metric (
    metric_id BIGSERIAL PRIMARY KEY,
    runtime_id BIGINT NOT NULL REFERENCES noetl.runtime(runtime_id) ON DELETE CASCADE,
    metric_name TEXT NOT NULL,
    metric_type TEXT NOT NULL CHECK (metric_type IN ('counter', 'gauge', 'histogram', 'summary')),
    metric_value DOUBLE PRECISION NOT NULL,
    labels JSONB,
    help_text TEXT,
    unit TEXT,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## Schema Design

### Key Fields

- **metric_id**: Auto-incrementing primary key
- **runtime_id**: Foreign key to `noetl.runtime` table (links metrics to registered components)
- **metric_name**: Name of the metric (e.g., `noetl_jobs_processed_total`, `cpu_usage_percent`)
- **metric_type**: Prometheus-compatible metric types:
  - `counter`: Monotonically increasing values
  - `gauge`: Values that can go up or down
  - `histogram`: Distribution of values
  - `summary`: Similar to histogram with quantiles
- **metric_value**: Numeric value of the metric
- **labels**: JSONB field for metric labels/dimensions (e.g., `{"worker_pool": "cpu-01", "job_type": "http"}`)
- **help_text**: Description of what the metric measures
- **unit**: Metric unit (e.g., `bytes`, `seconds`, `requests`)
- **timestamp**: When the metric was recorded
- **created_at**: When the record was inserted

### Indexes

- **Primary**: `metric_id`
- **Runtime lookup**: `idx_metrics_runtime_id`
- **Metric name queries**: `idx_metrics_name`
- **Time-series queries**: `idx_metrics_timestamp`
- **Combined queries**: `idx_metrics_runtime_name` (runtime_id + metric_name)
- **Label searches**: `idx_metrics_labels` (GIN index on JSONB)

## Integration with Runtime Table

The metrics table leverages the existing `noetl.runtime` table as a service catalog:

### Runtime Table Structure
```sql
-- Runtime table serves as component registry
CREATE TABLE noetl.runtime (
    runtime_id BIGINT PRIMARY KEY,
    name TEXT NOT NULL,                    -- Component name
    component_type TEXT NOT NULL,          -- 'worker_pool', 'server_api', 'broker'
    base_url TEXT,                         -- API endpoint
    status TEXT NOT NULL,                  -- 'ready', 'busy', 'offline'
    labels JSONB,                          -- Component labels
    capabilities JSONB,                    -- What the component can do
    capacity INTEGER,                      -- Max concurrent jobs
    runtime JSONB,                         -- Runtime info (type, version, etc.)
    last_heartbeat TIMESTAMPTZ,            -- Last activity
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
);
```

### Relationship
- Each metric record references a component in the runtime table
- Workers and servers register in runtime table, then report metrics
- Cascade delete ensures metrics are cleaned up when components are removed

## Usage Patterns

### Workers Reporting Metrics
1. Worker registers in `runtime` table during startup
2. Worker periodically reports metrics to server API
3. Server inserts metrics into `metric` table with worker's `runtime_id`

### Server Self-Reporting
1. Server has its own entry in `runtime` table
2. Server reports its own metrics (API requests, system resources)
3. Server inserts its metrics with its own `runtime_id`

### API Endpoints (To Implement)
- `POST /api/metrics` - Bulk insert metrics from workers/servers
- `GET /api/metrics` - Query metrics with filtering
- `GET /api/runtime/{runtime_id}/metrics` - Get metrics for specific component

## Example Metrics

### Worker Metrics
```json
{
  "runtime_id": 123,
  "metric_name": "noetl_jobs_processed_total",
  "metric_type": "counter", 
  "metric_value": 45,
  "labels": {"worker_pool": "cpu-01", "status": "completed"},
  "help_text": "Total number of jobs processed by worker",
  "unit": "jobs"
}
```

### Server Metrics
```json
{
  "runtime_id": 124,
  "metric_name": "noetl_api_requests_per_second",
  "metric_type": "gauge",
  "metric_value": 12.5,
  "labels": {"endpoint": "/api/queue/lease", "method": "POST"},
  "help_text": "Current API request rate",
  "unit": "req/sec"
}
```

### System Metrics
```json
{
  "runtime_id": 123,
  "metric_name": "system_cpu_usage_percent", 
  "metric_type": "gauge",
  "metric_value": 65.2,
  "labels": {"core": "all"},
  "help_text": "CPU utilization percentage",
  "unit": "percent"
}
```

## Migration Path

### Current State: PostgreSQL Storage
- All metrics stored in `noetl.metric` parent table with daily partitions
- Good for development and small/medium deployments
- Leverages existing PostgreSQL infrastructure

### Future State: Time-Series Database
- Export metrics to VictoriaMetrics/Prometheus
- Keep PostgreSQL for short-term retention
- Use dedicated TSDB for long-term storage and advanced queries

### Migration Strategy
1. **Phase 1**: Implement metrics collection in PostgreSQL
2. **Phase 2**: Add metrics export to VictoriaMetrics
3. **Phase 3**: Implement retention policies (keep recent in PG, historical in TSDB)
4. **Phase 4**: Optional migration to pure TSDB setup

## Benefits

### Centralized Collection
- Single point for all NoETL component metrics
- Consistent schema across workers and servers
- Simplified monitoring setup

### Flexible Storage
- JSONB labels support arbitrary dimensions
- Easy to query with SQL
- Compatible with existing PostgreSQL tooling

### Integration Ready
- Links to existing runtime registry
- Supports current heartbeat/registration flow
- Easy to extend with new metric types

### Migration Friendly
- Can export to Prometheus format
- Structured for time-series analysis
- Retention policies can be implemented

## Implementation Notes

1. **Bulk Inserts**: Use batch inserts for performance
2. **Retention**: Implement cleanup jobs for old metrics
3. **Partitioning**: Consider table partitioning by timestamp for large datasets
4. **Monitoring**: Monitor the metrics table size and performance
5. **Export**: Implement Prometheus export endpoint for existing monitoring tools

## Partitioning and TTL Cleanup (current implementation)

- Parent table: `noetl.metric` partitioned by RANGE on `created_at` with 1-day intervals
- Default TTL: records expire after 1 day via `expires_at` default; retention is enforced by dropping whole partitions older than 1 day
- Benefits: fast cleanup via DROP TABLE, immediate disk space reclaim, better query performance via partition pruning

### Database functions
- `noetl.initialize_metric_partitions()`
  - Creates initial set of partitions (yesterday, today, next 7 days)
- `noetl.create_metric_partition(partition_date date)`
  - Creates a single daily partition for the supplied date
- `noetl.create_metric_partitions_ahead(days_ahead int)`
  - Creates daily partitions from tomorrow up to N days ahead
- `noetl.cleanup_expired_metrics()` returns text[]
  - Drops partitions older than 1 day; returns a list of dropped partition table names

Example (Python async call):

```bash
dcd /Users/kadyapam/projects/noetl/noetl && .venv/bin/python -c "
import asyncio
from noetl.core.common import get_async_db_connection

async def test_cleanup():
    async with get_async_db_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute('SELECT noetl.cleanup_expired_metrics()')
            result = await cur.fetchone()
            print('Dropped partitions:', (result or [None])[0])

asyncio.run(test_cleanup())
"
```

### API endpoints

- POST `/api/metrics/cleanup`
  - Triggers cleanup (partition drops) and returns the list of dropped partitions
  - Example:
    ```bash
    curl -s -X POST http://localhost:30082/api/metrics/cleanup | jq
    ```

- POST `/api/metrics/partitions/create?days_ahead=3`
  - Creates partitions from tomorrow up to 3 days ahead
  - Example:
    ```bash
    curl -s -X POST "http://localhost:30082/api/metrics/partitions/create?days_ahead=3" | jq
    ```

### Notes
- Cleanup typically drops nothing until at least one full day has elapsed since initial partitions were created/populated.
- You can safely call partition creation multiple times; it will create missing partitions idempotently.
- The legacy content above shows a non-partitioned example schema; the live implementation is partitioned with 1-day TTL.
