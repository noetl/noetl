"""
NoETL Metrics API Schema - Pydantic models for metrics operations.

Defines request/response schemas for:
- Metric data points
- Bulk metrics reporting
- Metric queries
- Component listings
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class MetricData(BaseModel):
    """Single metric data point."""
    
    metric_name: str = Field(
        ...,
        description="Name of the metric"
    )
    metric_type: str = Field(
        ...,
        description="Type: counter, gauge, histogram, summary"
    )
    metric_value: float = Field(
        ...,
        description="Numeric value"
    )
    labels: Optional[Dict[str, str]] = Field(
        default=None,
        description="Metric labels/dimensions"
    )
    help_text: Optional[str] = Field(
        default=None,
        description="Metric description"
    )
    unit: Optional[str] = Field(
        default=None,
        description="Metric unit"
    )
    timestamp: Optional[datetime] = Field(
        default=None,
        description="Metric timestamp"
    )


class MetricsPayload(BaseModel):
    """Bulk metrics reporting payload."""
    
    runtime_id: Optional[int] = Field(
        default=None,
        description="Runtime ID (resolved from name if not provided)"
    )
    component_name: Optional[str] = Field(
        default=None,
        description="Component name for runtime lookup"
    )
    metrics: List[MetricData] = Field(
        ...,
        description="List of metrics to report"
    )


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


class MetricReportResponse(BaseModel):
    """Response schema for metric reporting."""
    
    status: str = Field(
        default="ok",
        description="Response status"
    )
    runtime_id: int = Field(
        ...,
        description="Runtime ID metrics were reported for"
    )
    metrics_inserted: int = Field(
        ...,
        description="Number of metrics inserted"
    )


class ComponentInfo(BaseModel):
    """Component information from runtime registry."""
    
    runtime_id: int = Field(
        ...,
        description="Runtime ID"
    )
    name: str = Field(
        ...,
        description="Component name"
    )
    component_type: str = Field(
        ...,
        description="Component type (worker, server, etc.)"
    )
    status: Optional[str] = Field(
        default=None,
        description="Component status"
    )
    last_heartbeat: Optional[str] = Field(
        default=None,
        description="Last heartbeat timestamp (ISO 8601)"
    )


class ComponentListResponse(BaseModel):
    """Response schema for component listing."""
    
    components: List[ComponentInfo] = Field(
        default_factory=list,
        description="List of registered components"
    )


class MetricQueryResponse(BaseModel):
    """Response schema for metric queries."""
    
    metrics: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of metrics matching query"
    )
    count: int = Field(
        default=0,
        description="Number of metrics returned"
    )
    limit: int = Field(
        default=1000,
        description="Query limit applied"
    )


class SelfReportResponse(BaseModel):
    """Response schema for self-reported metrics."""
    
    status: str = Field(
        default="ok",
        description="Response status"
    )
    component_name: str = Field(
        ...,
        description="Component name that reported"
    )
    runtime_id: int = Field(
        ...,
        description="Runtime ID"
    )
    metrics_reported: int = Field(
        ...,
        description="Number of metrics reported"
    )


class CleanupResponse(BaseModel):
    """Response schema for cleanup operations."""
    
    status: str = Field(
        default="ok",
        description="Response status"
    )
    dropped_partitions: List[str] = Field(
        default_factory=list,
        description="List of dropped partition names"
    )
    dropped_count: int = Field(
        default=0,
        description="Number of partitions dropped"
    )
    message: str = Field(
        ...,
        description="Cleanup message"
    )


class PartitionCreateResponse(BaseModel):
    """Response schema for partition creation."""
    
    status: str = Field(
        default="ok",
        description="Response status"
    )
    created_partitions: List[str] = Field(
        default_factory=list,
        description="List of created partition names"
    )
    created_count: int = Field(
        default=0,
        description="Number of partitions created"
    )
    days_ahead: int = Field(
        ...,
        description="Days ahead partitions were created for"
    )
    message: str = Field(
        ...,
        description="Creation message"
    )


class TTLUpdateResponse(BaseModel):
    """Response schema for TTL update operations."""
    
    status: str = Field(
        default="ok",
        description="Response status"
    )
    metric_name: Optional[str] = Field(
        default=None,
        description="Metric name (for metric-specific TTL)"
    )
    component_name: Optional[str] = Field(
        default=None,
        description="Component name (for component-specific TTL)"
    )
    updated_metrics: int = Field(
        default=0,
        description="Number of metrics updated"
    )
    new_ttl_days: int = Field(
        ...,
        description="New TTL in days"
    )
    message: str = Field(
        ...,
        description="Update message"
    )
