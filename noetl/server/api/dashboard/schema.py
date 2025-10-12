"""
NoETL Dashboard API Schemas - Request/Response models for dashboard operations.

Supports:
- Dashboard statistics
- Widget configurations
- Execution summaries
- Health checks
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class DashboardStatsResponse(BaseModel):
    """Response schema for dashboard statistics."""
    
    status: str = Field(
        default="ok",
        description="Response status"
    )
    stats: Dict[str, int] = Field(
        default_factory=dict,
        description="Dashboard statistics"
    )
    total_executions: int = Field(
        default=0,
        description="Total number of executions"
    )
    successful_executions: int = Field(
        default=0,
        description="Number of successful executions"
    )
    failed_executions: int = Field(
        default=0,
        description="Number of failed executions"
    )
    total_playbooks: int = Field(
        default=0,
        description="Total number of registered playbooks"
    )
    active_workflows: int = Field(
        default=0,
        description="Number of currently active workflows"
    )


class DashboardWidget(BaseModel):
    """Schema for a dashboard widget configuration."""
    
    id: str = Field(
        ...,
        description="Widget ID"
    )
    type: str = Field(
        ...,
        description="Widget type (chart, table, metric, etc.)"
    )
    title: str = Field(
        ...,
        description="Widget title"
    )
    config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Widget configuration"
    )
    data: Optional[Any] = Field(
        default=None,
        description="Widget data"
    )


class DashboardWidgetsResponse(BaseModel):
    """Response schema for dashboard widgets."""
    
    widgets: List[DashboardWidget] = Field(
        default_factory=list,
        description="List of dashboard widgets"
    )


class HealthCheckResponse(BaseModel):
    """Response schema for health check."""
    
    status: str = Field(
        default="ok",
        description="Health status"
    )
