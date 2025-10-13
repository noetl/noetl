"""
NoETL Aggregate API Module - Event-sourced result aggregation.

Provides:
- Loop iteration result aggregation
- Event log data retrieval
- Result filtering and deduplication
"""

from .endpoint import router
from .schema import LoopIterationResultsResponse
from .service import AggregateService

__all__ = [
    "router",
    "LoopIterationResultsResponse",
    "AggregateService",
]
