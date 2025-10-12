"""
NoETL Dashboard API Module - Dashboard statistics and monitoring.

Provides:
- Dashboard statistics (executions, playbooks, workflows)
- Dashboard widgets configuration
- Execution summaries
- Health check endpoints
"""

from .endpoint import router
from .schema import (
    DashboardStatsResponse,
    DashboardWidget,
    DashboardWidgetsResponse,
    HealthCheckResponse
)
from .service import DashboardService

__all__ = [
    "router",
    "DashboardStatsResponse",
    "DashboardWidget",
    "DashboardWidgetsResponse",
    "HealthCheckResponse",
    "DashboardService",
]
