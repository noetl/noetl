"""
NoETL System API Schema - Pydantic models for system monitoring operations.

Defines request/response schemas for:
- System status (CPU, memory, network)
- Process status (CPU, memory, I/O, threads)
- Thread information
- Memory profiling
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class SystemStatus(BaseModel):
    """System-wide resource utilization."""
    
    cpu_percent: float = Field(
        ...,
        description="System-wide CPU utilization percentage"
    )
    memory_percent: float = Field(
        ...,
        description="System-wide memory utilization percentage"
    )
    net_io_sent_mb: float = Field(
        ...,
        description="Total bytes sent over the network (MB)"
    )
    net_io_recv_mb: float = Field(
        ...,
        description="Total bytes received over the network (MB)"
    )


class ProcessStatus(BaseModel):
    """Current process resource utilization."""
    
    pid: int = Field(
        ...,
        description="Process ID"
    )
    cpu_percent: float = Field(
        ...,
        description="Process CPU utilization percentage"
    )
    user_cpu_time: float = Field(
        ...,
        description="User mode CPU time in seconds"
    )
    system_cpu_time: float = Field(
        ...,
        description="System mode CPU time in seconds"
    )
    memory_rss_mb: float = Field(
        ...,
        description="Resident Set Size (RSS) memory in MB"
    )
    memory_vms_mb: float = Field(
        ...,
        description="Virtual Memory Size (VMS) in MB"
    )
    memory_shared_mb: float = Field(
        ...,
        description="Shared memory in MB"
    )
    num_threads: int = Field(
        ...,
        description="Number of threads"
    )
    io_read_mb: float = Field(
        ...,
        description="Total I/O read in MB"
    )
    io_write_mb: float = Field(
        ...,
        description="Total I/O write in MB"
    )


class ThreadInfo(BaseModel):
    """Information about a running thread."""
    
    thread_id: int = Field(
        ...,
        description="Thread ID"
    )
    name: str = Field(
        ...,
        description="Thread name"
    )
    is_alive: bool = Field(
        ...,
        description="Whether thread is alive"
    )
    stack_trace: List[str] = Field(
        default_factory=list,
        description="Stack trace of the thread"
    )


class StatusResponse(BaseModel):
    """Response schema for system status."""
    
    system: SystemStatus = Field(
        ...,
        description="System-wide status"
    )
    process: ProcessStatus = Field(
        ...,
        description="Process status"
    )


class ReportResponse(BaseModel):
    """Response schema for profiler operations."""
    
    status: str = Field(
        ...,
        description="Operation status"
    )
    message: str = Field(
        ...,
        description="Operation message"
    )
    file_path: Optional[str] = Field(
        default=None,
        description="Path to generated file (if applicable)"
    )
