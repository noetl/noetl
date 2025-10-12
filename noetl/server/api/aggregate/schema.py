"""
NoETL Aggregate API Schema - Pydantic models for aggregate operations.

Defines request/response schemas for:
- Loop iteration result aggregation
- Event-sourced data aggregation
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class LoopIterationResultsResponse(BaseModel):
    """Response schema for loop iteration results."""
    
    status: str = Field(
        default="ok",
        description="Response status"
    )
    results: List[Any] = Field(
        default_factory=list,
        description="List of iteration results"
    )
    count: int = Field(
        default=0,
        description="Number of results"
    )
    method: str = Field(
        default="loop_metadata",
        description="Method used to retrieve results (loop_metadata or legacy_content_filter)"
    )
    debug: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Debug information (only present for legacy method)"
    )
