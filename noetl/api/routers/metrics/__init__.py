"""
NoETL Metrics API Module - Metrics collection and observability.

Provides:
- Metrics reporting and storage
- Prometheus format export
- System metrics collection
- Partition and TTL management
"""

from .endpoint import router
from .schema import (
    MetricData,
    MetricsPayload,
    MetricQuery,
    MetricReportResponse,
    ComponentInfo,
    ComponentListResponse,
    MetricQueryResponse,
    SelfReportResponse,
    CleanupResponse,
    PartitionCreateResponse,
    TTLUpdateResponse
)
from .service import MetricsService

__all__ = [
    "router",
    "MetricData",
    "MetricsPayload",
    "MetricQuery",
    "MetricReportResponse",
    "ComponentInfo",
    "ComponentListResponse",
    "MetricQueryResponse",
    "SelfReportResponse",
    "CleanupResponse",
    "PartitionCreateResponse",
    "TTLUpdateResponse",
    "MetricsService",
]
