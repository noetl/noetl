"""
NoETL Metrics API Endpoints - FastAPI routes for metrics operations.

Provides REST endpoints for:
- Metrics collection and reporting
- Metrics queries
- Prometheus format export
- Component listing
- Partition management
- TTL management
"""

from typing import Optional
from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from noetl.core.logger import setup_logger
from .schema import MetricsPayload
from .service import MetricsService

logger = setup_logger(__name__, include_location=True)
router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.post("/report", response_class=JSONResponse)
async def report_metrics(payload: MetricsPayload, request: Request):
    """
    Report metrics from workers or servers.
    
    **Request Body**:
    ```json
    {
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
    ```
    
    **Response**:
    ```json
    {
        "status": "ok",
        "runtime_id": 123,
        "metrics_inserted": 1
    }
    ```
    """
    try:
        result = await MetricsService.report_metrics(payload)
        return result.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
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
    
    **Examples**:
    - `GET /api/metrics/query?component_name=worker-cpu-01&metric_name=jobs_processed`
    - `GET /api/metrics/query?runtime_id=123&start_time=2025-01-01T00:00:00Z`
    
    **Response**:
    ```json
    {
        "metrics": [
            {
                "metric_id": "123456789",
                "runtime_id": 123,
                "component_name": "worker-cpu-01",
                "component_type": "worker",
                "metric_name": "jobs_processed",
                "metric_type": "counter",
                "metric_value": 45,
                "labels": {"status": "completed"},
                "help_text": "Jobs processed",
                "unit": "jobs",
                "timestamp": "2025-10-12T10:00:00Z",
                "created_at": "2025-10-12T10:00:00Z"
            }
        ],
        "count": 1,
        "limit": 1000
    }
    ```
    """
    try:
        result = await MetricsService.query_metrics(
            runtime_id=runtime_id,
            component_name=component_name,
            metric_name=metric_name,
            metric_type=metric_type,
            start_time=start_time,
            end_time=end_time,
            limit=limit
        )
        return result.model_dump()
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
    
    **Examples**:
    - `GET /api/metrics/prometheus` (all metrics)
    - `GET /api/metrics/prometheus?component_name=worker-cpu-01`
    
    **Response**:
    ```
    # HELP noetl_jobs_processed_total Total jobs processed
    # TYPE noetl_jobs_processed_total counter
    noetl_jobs_processed_total{component="worker-cpu-01",component_type="worker",status="completed"} 45
    ```
    """
    try:
        body = await MetricsService.generate_prometheus_format(
            runtime_id=runtime_id,
            component_name=component_name
        )
        return Response(
            content=body,
            media_type="text/plain; version=0.0.4; charset=utf-8"
        )
    except Exception as e:
        logger.exception(f"Error generating Prometheus metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/components", response_class=JSONResponse)
async def list_components():
    """
    List all components registered in runtime table.
    
    **Response**:
    ```json
    {
        "components": [
            {
                "runtime_id": 123,
                "name": "worker-cpu-01",
                "component_type": "worker",
                "status": "active",
                "last_heartbeat": "2025-10-12T10:00:00Z"
            }
        ]
    }
    ```
    """
    try:
        result = await MetricsService.list_components()
        return result.model_dump()
    except Exception as e:
        logger.exception(f"Error listing components: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/self-report", response_class=JSONResponse)
async def self_report_metrics(component_name: Optional[str] = None):
    """
    Allow server or worker to report its own system metrics.
    
    Used for self-monitoring without external tools. Automatically collects
    CPU, memory, and uptime metrics.
    
    **Query Parameters**:
    - `component_name`: Component name (auto-detected from environment if not provided)
    
    **Response**:
    ```json
    {
        "status": "ok",
        "component_name": "worker-cpu-01",
        "runtime_id": 123,
        "metrics_reported": 6
    }
    ```
    """
    try:
        result = await MetricsService.self_report_metrics(component_name)
        return result.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception(f"Error in self-report metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cleanup", summary="Clean up expired metrics (TTL via partition dropping)")
async def cleanup_expired_metrics():
    """
    Manually trigger cleanup of expired metrics by dropping old partitions.
    
    Returns the list of dropped partition names.
    
    **Response**:
    ```json
    {
        "status": "ok",
        "dropped_partitions": ["metric_2025_10_01", "metric_2025_10_02"],
        "dropped_count": 2,
        "message": "Dropped 2 expired metric partitions"
    }
    ```
    """
    try:
        result = await MetricsService.cleanup_expired_metrics()
        return result.model_dump()
    except Exception as e:
        logger.exception(f"Error cleaning up expired metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/partitions/create", summary="Create metric partitions for upcoming days")
async def create_metric_partitions(days_ahead: int = 7):
    """
    Create metric partitions for the next N days to ensure data can be inserted.
    
    **Query Parameters**:
    - `days_ahead`: Number of days ahead to create partitions for (default: 7)
    
    **Response**:
    ```json
    {
        "status": "ok",
        "created_partitions": ["metric_2025_10_13", "metric_2025_10_14"],
        "created_count": 2,
        "days_ahead": 7,
        "message": "Created 2 metric partitions"
    }
    ```
    """
    try:
        result = await MetricsService.create_metric_partitions(days_ahead)
        return result.model_dump()
    except Exception as e:
        logger.exception(f"Error creating metric partitions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ttl/set", summary="Set custom TTL for specific metrics")
async def set_metric_ttl(metric_name: str, ttl_days: int = 1):
    """
    Set custom TTL for all instances of a specific metric name.
    
    Note: With partitioning, this updates the expires_at field but 
    partition dropping still occurs based on partition date.
    
    **Query Parameters**:
    - `metric_name`: Name of the metric to update
    - `ttl_days`: Number of days from now until expiration (default: 1)
    
    **Response**:
    ```json
    {
        "status": "ok",
        "metric_name": "jobs_processed",
        "updated_metrics": 45,
        "new_ttl_days": 1,
        "message": "Updated TTL for 45 metrics named 'jobs_processed'"
    }
    ```
    """
    try:
        result = await MetricsService.set_metric_ttl(metric_name, ttl_days)
        return result.model_dump()
    except Exception as e:
        logger.exception(f"Error setting metric TTL: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ttl/extend-component", summary="Extend TTL for all metrics of a component")
async def extend_component_metrics_ttl(component_name: str, ttl_days: int = 1):
    """
    Extend TTL for all metrics belonging to a specific component.
    
    Note: With partitioning, this updates the expires_at field but 
    partition dropping still occurs based on partition date.
    
    **Query Parameters**:
    - `component_name`: Name of the component (runtime name)
    - `ttl_days`: Number of days from now until expiration (default: 1)
    
    **Response**:
    ```json
    {
        "status": "ok",
        "component_name": "worker-cpu-01",
        "updated_metrics": 120,
        "new_ttl_days": 1,
        "message": "Extended TTL for 120 metrics from component 'worker-cpu-01'"
    }
    ```
    """
    try:
        result = await MetricsService.extend_component_metrics_ttl(component_name, ttl_days)
        return result.model_dump()
    except Exception as e:
        logger.exception(f"Error extending component metrics TTL: {e}")
        raise HTTPException(status_code=500, detail=str(e))
