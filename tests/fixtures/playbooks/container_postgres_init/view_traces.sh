#!/bin/bash
set -euo pipefail

# view_traces.sh - Query and view traces for container_postgres_init playbook

EXECUTION_ID="${1:-}"
LIMIT="${2:-20}"

echo "=========================================="
echo "Container Test - Trace Viewer"
echo "=========================================="
echo ""

# Check if ClickHouse is deployed
if ! kubectl get deployment clickhouse -n observability >/dev/null 2>&1; then
    echo "ERROR: ClickHouse not deployed"
    echo "Deploy with: task clickhouse:deploy"
    exit 1
fi

if [ -z "$EXECUTION_ID" ]; then
    echo "Showing recent traces for container_postgres_init (last $LIMIT)..."
    echo ""
    
    kubectl exec -n observability deployment/clickhouse -- clickhouse-client -q "
        SELECT 
            formatDateTime(Timestamp, '%Y-%m-%d %H:%M:%S') as time,
            ServiceName,
            SpanName,
            Duration / 1000000 as duration_ms,
            StatusCode,
            SpanAttributes['execution_id'] as execution_id,
            SpanAttributes['step_name'] as step_name
        FROM observability.traces
        WHERE ServiceName = 'container_postgres_init'
        ORDER BY Timestamp DESC
        LIMIT $LIMIT
        FORMAT Pretty;
    "
    
    echo ""
    echo "To view traces for a specific execution:"
    echo "  ./view_traces.sh <execution_id>"
    
else
    echo "Showing traces for execution: $EXECUTION_ID"
    echo ""
    
    # Summary
    echo "=== Execution Summary ==="
    kubectl exec -n observability deployment/clickhouse -- clickhouse-client -q "
        SELECT 
            count() as span_count,
            sum(Duration) / 1000000 as total_duration_ms,
            countIf(StatusCode = 'ERROR') as error_count
        FROM observability.traces
        WHERE SpanAttributes['execution_id'] = '$EXECUTION_ID'
        FORMAT Pretty;
    "
    
    echo ""
    echo "=== Step Timeline ==="
    kubectl exec -n observability deployment/clickhouse -- clickhouse-client -q "
        SELECT 
            formatDateTime(Timestamp, '%H:%M:%S.%f') as time,
            SpanName,
            SpanAttributes['step_name'] as step,
            Duration / 1000000 as duration_ms,
            StatusCode,
            substring(SpanAttributes['error'] , 1, 100) as error_preview
        FROM observability.traces
        WHERE SpanAttributes['execution_id'] = '$EXECUTION_ID'
        ORDER BY Timestamp
        FORMAT Pretty;
    "
    
    echo ""
    echo "=== Performance Breakdown ==="
    kubectl exec -n observability deployment/clickhouse -- clickhouse-client -q "
        SELECT 
            SpanAttributes['step_name'] as step,
            count() as span_count,
            avg(Duration) / 1000000 as avg_duration_ms,
            max(Duration) / 1000000 as max_duration_ms
        FROM observability.traces
        WHERE SpanAttributes['execution_id'] = '$EXECUTION_ID'
          AND SpanAttributes['step_name'] != ''
        GROUP BY step
        ORDER BY avg_duration_ms DESC
        FORMAT Pretty;
    "
    
    echo ""
    echo "=== Container Job Details ==="
    kubectl exec -n observability deployment/clickhouse -- clickhouse-client -q "
        SELECT 
            SpanName,
            SpanAttributes['job_name'] as job_name,
            SpanAttributes['pod_name'] as pod_name,
            SpanAttributes['exit_code'] as exit_code,
            Duration / 1000000 as duration_ms
        FROM observability.traces
        WHERE SpanAttributes['execution_id'] = '$EXECUTION_ID'
          AND SpanName LIKE '%container%'
        FORMAT Pretty;
    "
fi

echo ""
echo "=========================================="
echo "Access Grafana for visualization:"
echo "  http://localhost:3000"
echo "  Username: admin / Password: admin"
echo "=========================================="
