"""
NoETL Runtime API Schemas - Request/Response models for runtime component registration.

Supports registration and management of:
- Worker pools
- Brokers
- Server API components
- Other runtime components
"""

from typing import Optional, Dict, Any, Literal
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, model_serializer


# Component types
RuntimeKind = Literal["worker_pool", "broker", "server_api", "scheduler", "monitor"]


class RuntimeRegistrationRequest(BaseModel):
    """
    Request schema for registering runtime components.
    
    Used for servers, brokers, worker pools, and other runtime components.
    """
    
    # Required fields
    name: str = Field(
        ...,
        description="Unique name for the runtime component",
        example="worker-pool-01"
    )
    kind: RuntimeKind = Field(
        default="worker_pool",
        description="Type of runtime component",
        alias="component_type"
    )
    
    # Optional identification fields
    runtime: Optional[str] = Field(
        default=None,
        description="Runtime type (python, nodejs, etc.)",
        example="python"
    )
    uri: Optional[str] = Field(
        default=None,
        description="Base URL/endpoint for the component (required for server_api and broker)",
        example="http://localhost:8082",
        alias="base_url"
    )
    
    # Status and capacity
    status: str = Field(
        default="ready",
        description="Component status: ready, offline, busy, etc."
    )
    capacity: Optional[int] = Field(
        default=None,
        description="Maximum capacity (for worker pools)",
        ge=0
    )
    
    # Metadata
    labels: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Arbitrary labels for filtering and organization"
    )
    pid: Optional[int] = Field(
        default=None,
        description="Process ID of the component"
    )
    hostname: Optional[str] = Field(
        default=None,
        description="Hostname where component is running"
    )
    meta: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional metadata"
    )
    
    @field_validator('name', 'runtime', 'uri', 'status', 'hostname', mode='before')
    @classmethod
    def coerce_to_string(cls, v):
        """Coerce to string and strip whitespace."""
        if v is None:
            return v
        return str(v).strip()
    
    @field_validator('status', mode='after')
    @classmethod
    def lowercase_status(cls, v):
        """Ensure status is lowercase."""
        if v:
            return v.lower()
        return v
    
    model_config = {
        "populate_by_name": True,  # Allow both field name and alias
    }


class WorkerPoolRegistrationRequest(RuntimeRegistrationRequest):
    """
    Specialized request for worker pool registration.
    
    Worker pools only require name and runtime, URI is optional.
    """
    kind: Literal["worker_pool"] = Field(
        default="worker_pool",
        description="Component type (fixed to worker_pool)"
    )


class RuntimeRegistrationResponse(BaseModel):
    """Response after registering a runtime component."""
    
    status: str = Field(
        ...,
        description="Registration status: ok, recreated, error"
    )
    name: str = Field(
        ...,
        description="Name of the registered component"
    )
    runtime_id: Optional[str] = Field(
        default=None,
        description="Unique runtime ID assigned to the component"
    )
    kind: Optional[str] = Field(
        default=None,
        description="Component type",
        alias="component_type"
    )
    runtime: Optional[str] = Field(
        default=None,
        description="Runtime type"
    )
    
    @field_validator('runtime_id', mode='before')
    @classmethod
    def coerce_to_string(cls, v):
        """Coerce runtime_id to string on input."""
        if v is None:
            return v
        return str(v)
    
    @model_serializer(mode='wrap')
    def serialize_model(self, serializer):
        """Ensure runtime_id is serialized as string and use field names (not aliases) for output."""
        data = serializer(self)
        if 'runtime_id' in data and data['runtime_id'] is not None:
            data['runtime_id'] = str(data['runtime_id'])
        # Ensure 'kind' is used instead of alias 'component_type' in output
        if 'component_type' in data:
            data['kind'] = data.pop('component_type')
        return data
    
    model_config = {
        "populate_by_name": True,  # Accept both field name and alias on input
    }


class RuntimeDeregistrationRequest(BaseModel):
    """Request to deregister a runtime component."""
    
    name: str = Field(
        ...,
        description="Name of the component to deregister"
    )
    kind: Optional[RuntimeKind] = Field(
        default="worker_pool",
        description="Component type",
        alias="component_type"
    )
    
    @field_validator('name', mode='before')
    @classmethod
    def strip_name(cls, v):
        if v:
            return str(v).strip()
        return v
    
    model_config = {
        "populate_by_name": True,
    }


class RuntimeHeartbeatRequest(BaseModel):
    """Heartbeat request to keep runtime component alive."""
    
    name: Optional[str] = Field(
        None,
        description="Name of the component sending heartbeat"
    )
    registration: Optional[Dict[str, Any]] = Field(
        None,
        description="Optional registration data for auto-recreation"
    )
    
    @field_validator('name', mode='before')
    @classmethod
    def strip_name(cls, v):
        if v:
            return str(v).strip()
        return v


class RuntimeHeartbeatResponse(BaseModel):
    """Response to heartbeat request."""
    
    status: str = Field(
        ...,
        description="Heartbeat status: ok, unknown, recreated"
    )
    name: Optional[str] = Field(
        None,
        description="Name of the component"
    )
    runtime_id: Optional[str] = Field(
        None,
        description="Runtime ID if known"
    )
    runtime: Optional[str] = Field(
        None,
        description="Runtime type (only for recreated components)"
    )
    
    @field_validator('runtime_id', mode='before')
    @classmethod
    def coerce_to_string(cls, v):
        if v is None:
            return v
        return str(v)
    
    @model_serializer(mode='wrap')
    def serialize_model(self, serializer):
        """Ensure runtime_id is serialized as string."""
        data = serializer(self)
        if 'runtime_id' in data and data['runtime_id'] is not None:
            data['runtime_id'] = str(data['runtime_id'])
        return data


class RuntimeComponentInfo(BaseModel):
    """Information about a registered runtime component."""
    
    name: str = Field(..., description="Component name")
    runtime: Optional[Dict[str, Any]] = Field(default=None, description="Runtime metadata")
    status: str = Field(..., description="Current status")
    capacity: Optional[int] = Field(default=None, description="Maximum capacity")
    labels: Optional[Dict[str, Any]] = Field(default=None, description="Component labels")
    heartbeat: Optional[str] = Field(default=None, description="Last heartbeat timestamp")
    created_at: Optional[str] = Field(default=None, description="Creation timestamp")
    updated_at: Optional[str] = Field(default=None, description="Last update timestamp")


class RuntimeListResponse(BaseModel):
    """Response for listing runtime components."""
    
    items: list[RuntimeComponentInfo] = Field(
        default_factory=list,
        description="List of runtime components"
    )
    count: int = Field(
        ...,
        description="Total number of components"
    )
    runtime: Optional[str] = Field(
        None,
        description="Filter: runtime type"
    )
    status: Optional[str] = Field(
        None,
        description="Filter: status"
    )
    error: Optional[str] = Field(
        None,
        description="Error message if query failed"
    )
