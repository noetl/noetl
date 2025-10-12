"""
NoETL Queue API Schema - Pydantic models for queue operations.

Defines request/response schemas for:
- Job enqueuing and leasing
- Job completion and failure
- Heartbeat and lease extension
- Queue listing and statistics
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class EnqueueRequest(BaseModel):
    """Request schema for enqueueing a job."""
    
    execution_id: str | int = Field(
        ...,
        description="Execution ID"
    )
    node_id: str = Field(
        ...,
        description="Node ID"
    )
    action: str = Field(
        ...,
        description="Action to execute"
    )
    context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Job context/input data"
    )
    input_context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Legacy field for context (backward compatibility)"
    )
    priority: Optional[int] = Field(
        default=0,
        description="Job priority (higher = more priority)"
    )
    max_attempts: Optional[int] = Field(
        default=5,
        description="Maximum retry attempts"
    )
    available_at: Optional[str] = Field(
        default=None,
        description="Timestamp when job becomes available"
    )


class LeaseRequest(BaseModel):
    """Request schema for leasing a job."""
    
    worker_id: str = Field(
        ...,
        description="Worker ID requesting the lease"
    )
    lease_seconds: Optional[int] = Field(
        default=60,
        description="Lease duration in seconds"
    )


class FailRequest(BaseModel):
    """Request schema for failing a job."""
    
    retry_delay_seconds: Optional[int] = Field(
        default=60,
        description="Delay before retry in seconds"
    )
    retry: Optional[bool] = Field(
        default=True,
        description="Whether to retry the job"
    )


class HeartbeatRequest(BaseModel):
    """Request schema for heartbeat."""
    
    worker_id: Optional[str] = Field(
        default=None,
        description="Worker ID"
    )
    extend_seconds: Optional[int] = Field(
        default=None,
        description="Extend lease by this many seconds"
    )


class ReserveRequest(BaseModel):
    """Request schema for reserving a job."""
    
    worker_id: str = Field(
        ...,
        description="Worker ID"
    )
    lease_seconds: Optional[int] = Field(
        default=60,
        description="Lease duration in seconds"
    )


class AckRequest(BaseModel):
    """Request schema for acknowledging job completion."""
    
    queue_id: int = Field(
        ...,
        description="Queue ID"
    )
    worker_id: str = Field(
        ...,
        description="Worker ID"
    )


class NackRequest(BaseModel):
    """Request schema for negative acknowledgment."""
    
    queue_id: int = Field(
        ...,
        description="Queue ID"
    )
    worker_id: str = Field(
        ...,
        description="Worker ID"
    )
    retry_delay_seconds: Optional[int] = Field(
        default=60,
        description="Delay before retry in seconds"
    )


class EnqueueResponse(BaseModel):
    """Response schema for enqueue operations."""
    
    status: str = Field(
        default="ok",
        description="Response status"
    )
    id: Optional[int] = Field(
        default=None,
        description="Queue ID of enqueued job"
    )


class LeaseResponse(BaseModel):
    """Response schema for lease operations."""
    
    status: str = Field(
        ...,
        description="Response status (ok or empty)"
    )
    job: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Leased job details"
    )


class CompleteResponse(BaseModel):
    """Response schema for job completion."""
    
    status: str = Field(
        default="ok",
        description="Response status"
    )
    id: Optional[int] = Field(
        default=None,
        description="Queue ID"
    )


class FailResponse(BaseModel):
    """Response schema for job failure."""
    
    status: str = Field(
        default="ok",
        description="Response status"
    )
    id: int = Field(
        ...,
        description="Queue ID"
    )


class HeartbeatResponse(BaseModel):
    """Response schema for heartbeat."""
    
    status: str = Field(
        default="ok",
        description="Response status"
    )
    id: int = Field(
        ...,
        description="Queue ID"
    )


class QueueListResponse(BaseModel):
    """Response schema for queue listing."""
    
    status: str = Field(
        default="ok",
        description="Response status"
    )
    items: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of queue items"
    )


class QueueSizeResponse(BaseModel):
    """Response schema for queue size."""
    
    status: str = Field(
        default="ok",
        description="Response status"
    )
    count: int = Field(
        default=0,
        description="Number of items in queue"
    )


class ReserveResponse(BaseModel):
    """Response schema for reserve operations."""
    
    job: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Reserved job details"
    )


class AckResponse(BaseModel):
    """Response schema for acknowledgment."""
    
    ok: bool = Field(
        default=True,
        description="Success indicator"
    )


class NackResponse(BaseModel):
    """Response schema for negative acknowledgment."""
    
    ok: bool = Field(
        default=True,
        description="Success indicator"
    )


class ReapResponse(BaseModel):
    """Response schema for reap operations."""
    
    reclaimed: int = Field(
        default=0,
        description="Number of jobs reclaimed"
    )
