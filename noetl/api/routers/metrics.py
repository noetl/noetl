"""
NoETL Metrics API Router
Handles metrics collection, storage, and exposure for observability.
"""

import os
import time
import json
import socket
import psutil
from typing import List, Dict, Any, Optional, Union
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from noetl.core.logger import setup_logger
from noetl.core.common import get_async_db_connection, get_snowflake_id

logger = setup_logger(__name__)
router = APIRouter(prefix="/metrics", tags=["metrics"])


class MetricData(BaseModel):
    """Single metric data point."""
    metric_name: str = Field(..., description="Name of the metric")
    metric_type: str = Field(..., description="Type: counter, gauge, histogram, summary")
    metric_value: float = Field(..., description="Numeric value")
    labels: Optional[Dict[str, str]] = Field(default=None, description="Metric labels/dimensions")
    help_text: Optional[str] = Field(default=None, description="Metric description")
    unit: Optional[str] = Field(default=None, description="Metric unit")
    timestamp: Optional[datetime] = Field(default=None, description="Metric timestamp")


class MetricsPayload(BaseModel):
    """Bulk metrics reporting payload."""
    runtime_id: Optional[int] = Field(default=None, description="Runtime ID (resolved from name if not provided)")
    component_name: Optional[str] = Field(default=None, description="Component name for runtime lookup")
    metrics: List[MetricData] = Field(..., description="List of metrics to report")


class MetricQuery(BaseModel):
    """Metric query parameters."""
    runtime_id: Optional[int] = None
    component_name: Optional[str] = None
    metric_name: Optional[str] = None
    metric_type: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    labels: Optional[Dict[str, str]] = None
    limit: int = Field(default=1000, le=10000)


@router.post("/report", response_class=JSONResponse)
async def report_metrics(payload: MetricsPayload, request: Request):
    """
    Report metrics from workers or servers.
    
    Body: {
        "runtime_id": 123,  // Optional - can be resolved from component_name
        "component_name": "worker-cpu-01",  // Optional - used if runtime_id not provided
        "metrics": [
            {
                "metric_name": "noetl_jobs_processed_total",
                "metric_type": "counter",
                "metric_value": 45,
                "labels": {"status": "completed"},
                "help_text": "Total jobs processed",
                "unit": "jobs"
            }
        ]
    }
    """
    try:
        runtime_id = payload.runtime_id
        
        # Resolve runtime_id from component_name if not provided
        if not runtime_id and payload.component_name:
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT runtime_id FROM noetl.runtime WHERE name = %s",
                        (payload.component_name,)
                    )
                    row = await cur.fetchone()
                    if row:
                        runtime_id = row[0]
                    else:
                        raise HTTPException(
                            status_code=404, 
                            detail=f"Component '{payload.component_name}' not found in runtime registry"
                        )
        
        if not runtime_id:
            raise HTTPException(
                status_code=400, 
                detail="Either runtime_id or component_name must be provided"
            )
        
        # Insert metrics
        inserted_count = 0
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                for metric in payload.metrics:
                    try:
                        metric_id = get_snowflake_id()
                    except Exception:
                        metric_id = int(time.time() * 1000000)  # Fallback
                    
                    timestamp = metric.timestamp or datetime.now(timezone.utc)
                    labels_json = json.dumps(metric.labels) if metric.labels else None
                    
                    await cur.execute(
                        """
                        INSERT INTO noetl.metric 
                        (metric_id, runtime_id, metric_name, metric_type, metric_value, 
                         labels, help_text, unit, timestamp, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                        """,
                        (
                            metric_id, runtime_id, metric.metric_name, 
                            metric.metric_type, metric.metric_value,
                            labels_json, metric.help_text, metric.unit, timestamp
                        )
                    )
                    inserted_count += 1
            
            await conn.commit()
        
        return JSONResponse(content={
            "status": "ok",
            "runtime_id": runtime_id,
            "metrics_inserted": inserted_count
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error reporting metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/query", response_class=JSONResponse)
async def query_metrics(
    runtime_id: Optional[int] = Query(None, description="Filter by runtime ID"),
    component_name: Optional[str] = Query(None, description="Filter by component name"),
    metric_name: Optional[str] = Query(None, description="Filter by metric name"),
    metric_type: Optional[str] = Query(None, description="Filter by metric type"),
    start_time: Optional[str] = Query(None, description="Start time (ISO format)"),
    end_time: Optional[str] = Query(None, description="End time (ISO format)"),
    limit: int = Query(1000, le=10000, description="Maximum results")
):
    """
    Query metrics with optional filtering.
    
    Examples:
    - GET /api/metrics/query?component_name=worker-cpu-01&metric_name=jobs_processed
    - GET /api/metrics/query?runtime_id=123&start_time=2025-01-01T00:00:00Z
    """
    try:
        # Build dynamic query
        where_clauses = []
        params = []
        
        if runtime_id:
            where_clauses.append("m.runtime_id = %s")
            params.append(runtime_id)
        elif component_name:
            where_clauses.append("r.name = %s")
            params.append(component_name)
        
        if metric_name:
            where_clauses.append("m.metric_name = %s")
            params.append(metric_name)
        
        if metric_type:
            where_clauses.append("m.metric_type = %s")
            params.append(metric_type)
        
        if start_time:
            where_clauses.append("m.timestamp >= %s")
            params.append(start_time)
        
        if end_time:
            where_clauses.append("m.timestamp <= %s")
            params.append(end_time)
        
        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        
        query = f"""
            SELECT 
                m.metric_id, m.runtime_id, r.name as component_name, r.component_type,
                m.metric_name, m.metric_type, m.metric_value, m.labels, 
                m.help_text, m.unit, m.timestamp, m.created_at
            FROM noetl.metric m
            JOIN noetl.runtime r ON m.runtime_id = r.runtime_id
            WHERE {where_sql}
            ORDER BY m.timestamp DESC
            LIMIT %s
        """
        params.append(limit)
        
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                rows = await cur.fetchall()
                
                metrics = []
                for row in rows:
                    labels_data = json.loads(row[7]) if row[7] else None
                    metrics.append({
                        "metric_id": row[0],
                        "runtime_id": row[1],
                        "component_name": row[2],
                        "component_type": row[3],
                        "metric_name": row[4],
                        "metric_type": row[5],
                        "metric_value": row[6],
                        "labels": labels_data,
                        "help_text": row[8],
                        "unit": row[9],
                        "timestamp": row[10].isoformat() if row[10] else None,
                        "created_at": row[11].isoformat() if row[11] else None
                    })
        
        return JSONResponse(content={
            "metrics": metrics,
            "count": len(metrics),
            "limit": limit
        })
        
    except Exception as e:
        logger.exception(f"Error querying metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prometheus", response_class=Response)
async def prometheus_metrics(
    runtime_id: Optional[int] = Query(None, description="Filter by runtime ID"),
    component_name: Optional[str] = Query(None, description="Filter by component name")
):
    """
    Export metrics in Prometheus format for scraping by VictoriaMetrics.
    
    Examples:
    - GET /api/metrics/prometheus  (all metrics)
    - GET /api/metrics/prometheus?component_name=worker-cpu-01
    """
    try:
        # Build query with optional filtering
        where_clauses = ["1=1"]
        params = []
        
        if runtime_id:
            where_clauses.append("m.runtime_id = %s")
            params.append(runtime_id)
        elif component_name:
            where_clauses.append("r.name = %s")
            params.append(component_name)
        
        where_sql = " AND ".join(where_clauses)
        
        # Get recent metrics (last 5 minutes for gauges, latest values for counters)
        query = f"""
            WITH recent_metrics AS (
                SELECT DISTINCT ON (m.runtime_id, m.metric_name, m.labels)
                    m.metric_name, m.metric_type, m.metric_value, m.labels,
                    m.help_text, r.name as component_name, r.component_type
                FROM noetl.metric m
                JOIN noetl.runtime r ON m.runtime_id = r.runtime_id
                WHERE {where_sql}
                  AND m.timestamp >= now() - interval '5 minutes'
                ORDER BY m.runtime_id, m.metric_name, m.labels, m.timestamp DESC
            )
            SELECT * FROM recent_metrics
            ORDER BY metric_name, component_name
        """
        
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                rows = await cur.fetchall()
        
        # Group metrics by name for Prometheus format
        metrics_by_name = {}
        for row in rows:
            metric_name, metric_type, metric_value, labels_json, help_text, component_name, component_type = row
            
            if metric_name not in metrics_by_name:
                metrics_by_name[metric_name] = {
                    "type": metric_type,
                    "help": help_text or f"NoETL metric: {metric_name}",
                    "values": []
                }
            
            # Parse labels and add component info
            labels = json.loads(labels_json) if labels_json else {}
            labels["component"] = component_name
            labels["component_type"] = component_type
            
            # Format labels for Prometheus
            label_str = ""
            if labels:
                label_pairs = [f'{k}="{v}"' for k, v in labels.items()]
                label_str = "{" + ",".join(label_pairs) + "}"
            
            metrics_by_name[metric_name]["values"].append({
                "labels": label_str,
                "value": metric_value
            })
        
        # Generate Prometheus format
        lines = []
        for metric_name, metric_data in metrics_by_name.items():
            # Add HELP and TYPE lines
            lines.append(f"# HELP {metric_name} {metric_data['help']}")
            lines.append(f"# TYPE {metric_name} {metric_data['type']}")
            
            # Add metric values
            for value_data in metric_data["values"]:
                lines.append(f"{metric_name}{value_data['labels']} {value_data['value']}")
        
        body = "\n".join(lines) + "\n"
        return Response(
            content=body,
            media_type="text/plain; version=0.0.4; charset=utf-8"
        )
        
    except Exception as e:
        logger.exception(f"Error generating Prometheus metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/components", response_class=JSONResponse)
async def list_components():
    """List all components registered in runtime table."""
    try:
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT runtime_id, name, component_type, status, last_heartbeat
                    FROM noetl.runtime
                    ORDER BY component_type, name
                    """
                )
                rows = await cur.fetchall()
                
                components = []
                for row in rows:
                    components.append({
                        "runtime_id": row[0],
                        "name": row[1],
                        "component_type": row[2],
                        "status": row[3],
                        "last_heartbeat": row[4].isoformat() if row[4] else None
                    })
        
        return JSONResponse(content={"components": components})
        
    except Exception as e:
        logger.exception(f"Error listing components: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def collect_system_metrics() -> List[MetricData]:
    """Collect basic system metrics for the current process."""
    metrics = []
    
    try:
        # CPU usage
        cpu_percent = psutil.cpu_percent(interval=0.1)
        metrics.append(MetricData(
            metric_name="noetl_system_cpu_usage_percent",
            metric_type="gauge",
            metric_value=cpu_percent,
            help_text="CPU usage percentage",
            unit="percent"
        ))
        
        # Memory usage
        memory = psutil.virtual_memory()
        metrics.append(MetricData(
            metric_name="noetl_system_memory_usage_bytes",
            metric_type="gauge",
            metric_value=memory.used,
            help_text="Memory usage in bytes",
            unit="bytes"
        ))
        
        metrics.append(MetricData(
            metric_name="noetl_system_memory_usage_percent",
            metric_type="gauge",
            metric_value=memory.percent,
            help_text="Memory usage percentage",
            unit="percent"
        ))
        
        # Process info
        process = psutil.Process()
        metrics.append(MetricData(
            metric_name="noetl_process_cpu_percent",
            metric_type="gauge",
            metric_value=process.cpu_percent(),
            help_text="Process CPU usage percentage",
            unit="percent"
        ))
        
        memory_info = process.memory_info()
        metrics.append(MetricData(
            metric_name="noetl_process_memory_rss_bytes",
            metric_type="gauge",
            metric_value=memory_info.rss,
            help_text="Process RSS memory in bytes",
            unit="bytes"
        ))
        
        # Process start time
        start_time = process.create_time()
        metrics.append(MetricData(
            metric_name="noetl_process_start_time_seconds",
            metric_type="gauge",
            metric_value=start_time,
            help_text="Process start time since unix epoch",
            unit="seconds"
        ))
        
    except Exception as e:
        logger.debug(f"Error collecting system metrics: {e}")
    
    return metrics


@router.post("/self-report", response_class=JSONResponse)
async def self_report_metrics(component_name: Optional[str] = None):
    """
    Allow server or worker to report its own system metrics.
    Used for self-monitoring without external tools.
    """
    try:
        # Determine component name
        if not component_name:
            component_name = os.environ.get("NOETL_WORKER_POOL_NAME") or os.environ.get("NOETL_SERVER_NAME", "noetl-server")
        
        # Collect system metrics
        system_metrics = collect_system_metrics()
        
        # Add uptime metric
        try:
            process = psutil.Process()
            uptime = time.time() - process.create_time()
            system_metrics.append(MetricData(
                metric_name="noetl_uptime_seconds",
                metric_type="gauge",
                metric_value=uptime,
                help_text="Component uptime in seconds",
                unit="seconds"
            ))
        except Exception:
            pass
        
        # Report metrics
        payload = MetricsPayload(
            component_name=component_name,
            metrics=system_metrics
        )
        
        # Use the same logic as report_metrics but inline to avoid recursion
        runtime_id = None
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT runtime_id FROM noetl.runtime WHERE name = %s",
                    (component_name,)
                )
                row = await cur.fetchone()
                if row:
                    runtime_id = row[0]
                else:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Component '{component_name}' not found in runtime registry"
                    )
        
        # Insert metrics
        inserted_count = 0
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                for metric in system_metrics:
                    try:
                        metric_id = get_snowflake_id()
                    except Exception:
                        metric_id = int(time.time() * 1000000)
                    
                    timestamp = datetime.now(timezone.utc)
                    labels_json = json.dumps(metric.labels) if metric.labels else None
                    
                    await cur.execute(
                        """
                        INSERT INTO noetl.metric 
                        (metric_id, runtime_id, metric_name, metric_type, metric_value, 
                         labels, help_text, unit, timestamp, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                        """,
                        (
                            metric_id, runtime_id, metric.metric_name,
                            metric.metric_type, metric.metric_value,
                            labels_json, metric.help_text, metric.unit, timestamp
                        )
                    )
                    inserted_count += 1
            
            await conn.commit()
        
        return JSONResponse(content={
            "status": "ok",
            "component_name": component_name,
            "runtime_id": runtime_id,
            "metrics_reported": inserted_count
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error in self-report metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cleanup", summary="Clean up expired metrics (TTL via partition dropping)")
async def cleanup_expired_metrics():
    """
    Manually trigger cleanup of expired metrics by dropping old partitions.
    Returns the list of dropped partition names.
    """
    try:
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                # Call the partition cleanup function
                await cur.execute("SELECT noetl.cleanup_expired_metrics()")
                result = await cur.fetchone()
                dropped_partitions = result[0] if result else []
                
            await conn.commit()
        
        return JSONResponse(content={
            "status": "ok",
            "dropped_partitions": dropped_partitions,
            "dropped_count": len(dropped_partitions),
            "message": f"Dropped {len(dropped_partitions)} expired metric partitions"
        })
        
    except Exception as e:
        logger.exception(f"Error cleaning up expired metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/partitions/create", summary="Create metric partitions for upcoming days")
async def create_metric_partitions(days_ahead: int = 7):
    """
    Create metric partitions for the next N days to ensure data can be inserted.
    
    Args:
        days_ahead: Number of days ahead to create partitions for (default: 7)
    """
    try:
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT noetl.create_metric_partitions_ahead(%s)",
                    (days_ahead,)
                )
                result = await cur.fetchone()
                partition_names = result[0] if result else []
                
            await conn.commit()
        
        return JSONResponse(content={
            "status": "ok",
            "created_partitions": partition_names,
            "created_count": len(partition_names),
            "days_ahead": days_ahead,
            "message": f"Created {len(partition_names)} metric partitions"
        })
        
    except Exception as e:
        logger.exception(f"Error creating metric partitions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ttl/set", summary="Set custom TTL for specific metrics")
async def set_metric_ttl(metric_name: str, ttl_days: int = 1):
    """
    Set custom TTL for all instances of a specific metric name.
    Note: With partitioning, this updates the expires_at field but 
    partition dropping still occurs based on partition date.
    
    Args:
        metric_name: Name of the metric to update
        ttl_days: Number of days from now until expiration (default: 1)
    """
    try:
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT noetl.set_metric_ttl(%s, %s::interval)",
                    (metric_name, f"{ttl_days} days")
                )
                result = await cur.fetchone()
                updated_count = result[0] if result else 0
                
            await conn.commit()
        
        return JSONResponse(content={
            "status": "ok",
            "metric_name": metric_name,
            "updated_metrics": updated_count,
            "new_ttl_days": ttl_days,
            "message": f"Updated TTL for {updated_count} metrics named '{metric_name}'"
        })
        
    except Exception as e:
        logger.exception(f"Error setting metric TTL: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ttl/extend-component", summary="Extend TTL for all metrics of a component")
async def extend_component_metrics_ttl(component_name: str, ttl_days: int = 1):
    """
    Extend TTL for all metrics belonging to a specific component.
    Note: With partitioning, this updates the expires_at field but 
    partition dropping still occurs based on partition date.
    
    Args:
        component_name: Name of the component (runtime name)
        ttl_days: Number of days from now until expiration (default: 1)
    """
    try:
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT noetl.extend_component_metrics_ttl(%s, %s::interval)",
                    (component_name, f"{ttl_days} days")
                )
                result = await cur.fetchone()
                updated_count = result[0] if result else 0
                
            await conn.commit()
        
        return JSONResponse(content={
            "status": "ok",
            "component_name": component_name,
            "updated_metrics": updated_count,
            "new_ttl_days": ttl_days,
            "message": f"Extended TTL for {updated_count} metrics from component '{component_name}'"
        })
        
    except Exception as e:
        logger.exception(f"Error extending component metrics TTL: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def auto_cleanup_expired_metrics():
    """
    Background function to automatically clean up expired metrics via partition dropping.
    Can be called periodically by the application.
    """
    try:
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT noetl.cleanup_expired_metrics()")
                result = await cur.fetchone()
                dropped_partitions = result[0] if result else []
                
            await conn.commit()
            
        if dropped_partitions:
            logger.info(f"Auto-cleanup: dropped {len(dropped_partitions)} expired metric partitions: {dropped_partitions}")
        
        return len(dropped_partitions)
        
    except Exception as e:
        logger.exception(f"Error in auto-cleanup of expired metrics: {e}")
        return 0


async def auto_create_metric_partitions():
    """
    Background function to automatically create metric partitions for upcoming days.
    Should be called daily to ensure partitions exist for new data.
    """
    try:
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                # Create partitions for the next 7 days
                await cur.execute("SELECT noetl.create_metric_partitions_ahead(7)")
                result = await cur.fetchone()
                partition_names = result[0] if result else []
                
            await conn.commit()
            
        if partition_names:
            logger.info(f"Auto-partition creation: created {len(partition_names)} metric partitions")
        
        return len(partition_names)
        
    except Exception as e:
        logger.exception(f"Error in auto-creation of metric partitions: {e}")
        return 0