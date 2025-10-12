"""
NoETL System API Module - System monitoring and profiling.

Provides:
- System and process status monitoring
- Thread inspection and debugging
- Memory profiling with Memray
"""

from .endpoint import router
from .schema import (
    SystemStatus,
    ProcessStatus,
    ThreadInfo,
    StatusResponse,
    ReportResponse
)
from .service import SystemService

__all__ = [
    "router",
    "SystemStatus",
    "ProcessStatus",
    "ThreadInfo",
    "StatusResponse",
    "ReportResponse",
    "SystemService",
]
