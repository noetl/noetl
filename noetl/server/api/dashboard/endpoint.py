"""
NoETL Dashboard API Endpoints - FastAPI routes for dashboard operations.

Provides REST endpoints for:
- Dashboard statistics and metrics
- Dashboard widget configuration
- Execution summaries and details
- System health checks
"""

from fastapi import APIRouter, HTTPException
from noetl.core.logger import setup_logger
from .schema import (
    DashboardStatsResponse,
    DashboardWidgetsResponse,
    HealthCheckResponse
)
from .service import DashboardService

logger = setup_logger(__name__, include_location=True)
router = APIRouter()


# ============================================================================
# Dashboard Statistics Endpoints
# ============================================================================

@router.get("/dashboard/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats() -> DashboardStatsResponse:
    """
    Get dashboard statistics.
    
    Returns aggregate statistics for the dashboard including:
    - Total executions
    - Successful/failed execution counts
    - Total registered playbooks
    - Currently active workflows
    
    **Response**:
    ```json
    {
        "status": "ok",
        "stats": {
            "total_executions": 150,
            "successful_executions": 135,
            "failed_executions": 15,
            "total_playbooks": 25,
            "active_workflows": 3
        },
        "total_executions": 150,
        "successful_executions": 135,
        "failed_executions": 15,
        "total_playbooks": 25,
        "active_workflows": 3
    }
    ```
    
    **Note**: This is currently a placeholder implementation that returns
    zero counts. Production implementation should query the event log
    and catalog for actual statistics.
    """
    try:
        return await DashboardService.get_dashboard_stats()
    except Exception as e:
        logger.exception(f"Error in get_dashboard_stats endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dashboard/widgets", response_model=DashboardWidgetsResponse)
async def get_dashboard_widgets() -> DashboardWidgetsResponse:
    """
    Get dashboard widgets configuration.
    
    Returns a list of configured dashboard widgets with their
    configuration and data. Widgets can include:
    - Execution trend charts
    - Recent executions tables
    - Success rate metrics
    - Resource utilization graphs
    
    **Response**:
    ```json
    {
        "widgets": [
            {
                "id": "execution-trend",
                "type": "chart",
                "title": "Execution Trend",
                "config": {
                    "chart_type": "line",
                    "time_range": "7d"
                },
                "data": [...]
            }
        ]
    }
    ```
    
    **Note**: This is currently a placeholder implementation that returns
    an empty list. Production implementation should return configured
    widgets with actual data.
    """
    try:
        return await DashboardService.get_dashboard_widgets()
    except Exception as e:
        logger.exception(f"Error in get_dashboard_widgets endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Health Check Endpoint
# ============================================================================

@router.get("/health", response_model=HealthCheckResponse)
async def api_health() -> HealthCheckResponse:
    """
    Health check endpoint.
    
    Returns the health status of the dashboard API.
    Useful for monitoring and load balancer health checks.
    
    **Response**:
    ```json
    {
        "status": "ok"
    }
    ```
    """
    try:
        return await DashboardService.health_check()
    except Exception as e:
        logger.exception(f"Error in health check endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


