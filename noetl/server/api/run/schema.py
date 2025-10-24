"""
NoETL Execution API Schemas - Request/Response models for execution endpoints.

Supports MCP-compatible execution patterns for playbooks, tools, and models.
Unified schema design supporting multiple lookup strategies:
- catalog_id: Direct catalog entry lookup
- path + version: Version-controlled path-based lookup
"""

from typing import Optional, Dict, Any, Literal
from datetime import datetime
from pydantic import BaseModel, Field, model_validator, field_validator


# Execution Types (extensible for future MCP tool/model support)
ExecutionType = Literal["playbook", "tool", "model", "workflow"]


class ExecutionContext(BaseModel):
    """Context for nested/child executions."""
    parent_execution_id: Optional[str] = Field(
        default=None,
        description="Parent execution ID for nested executions"
    )
    parent_event_id: Optional[str] = Field(
        default=None,
        description="Parent event ID that triggered this execution"
    )
    parent_step: Optional[str] = Field(
        default=None,
        description="Parent step name that triggered this execution"
    )


class ExecutionRequest(BaseModel):
    """
    Unified execution request schema supporting multiple lookup strategies.
    
    **Lookup Strategies** (priority order):
    1. `catalog_id`: Direct catalog entry lookup (highest priority)
    2. `path` + `version`: Version-controlled path-based lookup
    
    **MCP Compatibility**:
    - Set `type` to specify execution type: playbook, tool, model, workflow
    - Use `parameters` for input data
    - Supports nested execution contexts
    
    At least one identifier (catalog_id or path) must be provided.
    """
    
    # Target identification - multiple strategies supported
    catalog_id: Optional[str] = Field(
        default=None,
        description="Direct catalog entry ID (primary key lookup)",
        example="478775660589088776"
    )
    path: Optional[str] = Field(
        default=None,
        description="Catalog path for version-controlled lookup",
        example="examples/weather/forecast"
    )
    version: Optional[str] = Field(
        default="latest",
        description="Version identifier (semantic version or 'latest'). Used with path lookup",
        example="v1.0.0"
    )
    
    # Execution type and configuration
    args: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Input args for execution",
        alias="args"
    )
    
    # Execution options
    merge: bool = Field(
        default=False,
        description="Merge args with existing workload data"
    )
    
    # Context (supports both nested and flattened formats)
    context: Optional[ExecutionContext] = Field(
        default=None,
        description="Execution context for nested/child executions"
    )
    parent_execution_id: Optional[str] = Field(
        default=None,
        description="Parent execution ID (flattened, merged into context)"
    )
    parent_event_id: Optional[str] = Field(
        default=None,
        description="Parent event ID (flattened, merged into context)"
    )
    parent_step: Optional[str] = Field(
        default=None,
        description="Parent step name (flattened, merged into context)"
    )
    
    # Additional metadata
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional metadata for execution tracking"
    )
    
    @field_validator('catalog_id', 'path', 'version', 'parent_execution_id', 'parent_event_id', mode='before')
    @classmethod
    def coerce_ids_to_string(cls, v):
        """Coerce integers or other types to strings for all ID fields."""
        if v is None:
            return v
        return str(v)
    
    @model_validator(mode='after')
    def validate_and_normalize(self):
        """
        Validate that at least one identifier is provided and normalize the request.
        """
        # Validate at least one identifier is present
        if not self.catalog_id and not self.path:
            raise ValueError(
                "At least one identifier must be provided: catalog_id or path"
            )
        
        # Default version to 'latest' if using path-based lookup
        if self.path and not self.catalog_id:
            if self.version is None:
                self.version = "latest"
        
        # Merge flattened context fields into context object
        if self.parent_execution_id or self.parent_event_id or self.parent_step:
            if not self.context:
                self.context = ExecutionContext()
            if self.parent_execution_id:
                self.context.parent_execution_id = self.parent_execution_id
            if self.parent_event_id:
                self.context.parent_event_id = self.parent_event_id
            if self.parent_step:
                self.context.parent_step = self.parent_step
        
        return self
    
    model_config = {
        "populate_by_name": True,  # Allow both field name and alias
    }


class ExecutionResponse(BaseModel):
    """
    Unified execution response.
    
    Returns execution metadata and status for tracking.
    
    NOTE: For backward compatibility, both old and new field names are included:
    - execution_id and id (same value)
    - timestamp and start_time (same value)
    - type and execution_type (same value)
    """
    # Execution identification (backward compatible - both names)
    execution_id: str = Field(
        ...,
        description="Unique execution ID for tracking"
    )
    id: Optional[str] = Field(
        default=None,
        description="Alias for execution_id (backward compatibility)"
    )
    
    # Catalog metadata
    catalog_id: Optional[str] = Field(
        None,
        description="Catalog entry ID used for execution"
    )
    path: Optional[str] = Field(
        None,
        description="Catalog path executed"
    )
    playbook_name: Optional[str] = Field(
        None,
        description="Playbook name (derived from path)"
    )
    version: Optional[str] = Field(
        None,
        description="Version executed"
    )
    
    # Execution metadata (backward compatible - both names)
    type: ExecutionType = Field(
        default="playbook",
        description="Type of execution"
    )
    execution_type: Optional[ExecutionType] = Field(
        default=None,
        description="Alias for type (backward compatibility)"
    )
    status: str = Field(
        ...,
        description="Current status: running, completed, failed, pending, etc."
    )
    
    # Timestamps (backward compatible - both names)
    timestamp: Optional[str] = Field(
        None,
        description="Execution creation timestamp"
    )
    start_time: Optional[str] = Field(
        None,
        description="Alias for timestamp (backward compatibility)"
    )
    end_time: Optional[str] = Field(
        None,
        description="Execution completion timestamp"
    )
    
    # Progress and results
    progress: Optional[int] = Field(
        default=0,
        description="Execution progress percentage (0-100)",
        ge=0,
        le=100
    )
    result: Optional[Dict[str, Any]] = Field(
        None,
        description="Execution result data (None for async executions)"
    )
    error: Optional[str] = Field(
        None,
        description="Error message if execution failed"
    )
    
    @field_validator('execution_id', 'id', 'catalog_id', 'path', 'version', mode='before')
    @classmethod
    def coerce_to_string(cls, v):
        """Coerce integers or other types to strings for all ID and path fields."""
        if v is None:
            return v
        return str(v)
    
    def model_post_init(self, __context):
        """Ensure backward compatible field aliases are populated."""
        # Populate id from execution_id
        if self.execution_id and not self.id:
            self.id = self.execution_id
        
        # Populate execution_type from type
        if self.type and not self.execution_type:
            self.execution_type = self.type
        
        # Populate start_time from timestamp
        if self.timestamp and not self.start_time:
            self.start_time = self.timestamp
    
    model_config = {
        "populate_by_name": True,  # Allow both field name and alias
    }


class ExecutionListQuery(BaseModel):
    """Query parameters for listing executions."""
    
    # Filters
    catalog_id: Optional[str] = Field(
        None,
        description="Filter by catalog ID"
    )
    path: Optional[str] = Field(
        None,
        description="Filter by catalog path"
    )
    type: Optional[ExecutionType] = Field(
        None,
        description="Filter by execution type",
        alias="execution_type"
    )
    status: Optional[str] = Field(
        None,
        description="Filter by status"
    )
    parent_execution_id: Optional[str] = Field(
        None,
        description="Filter by parent execution ID"
    )
    
    # Time range
    start_time: Optional[datetime] = Field(
        None,
        description="Filter executions after this time"
    )
    end_time: Optional[datetime] = Field(
        None,
        description="Filter executions before this time"
    )
    
    # Pagination
    limit: int = Field(
        default=100,
        le=1000,
        description="Maximum number of results"
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Offset for pagination"
    )
    
    model_config = {
        "populate_by_name": True,
    }


class ExecutionListResponse(BaseModel):
    """Response for execution list queries."""
    items: list[ExecutionResponse] = Field(
        ...,
        description="List of execution responses"
    )
    total: int = Field(
        ...,
        description="Total count of matching executions"
    )
    limit: int = Field(
        ...,
        description="Query limit used"
    )
    offset: int = Field(
        ...,
        description="Query offset used"
    )
    has_more: bool = Field(
        ...,
        description="Whether more results exist"
    )


# MCP Tool/Model execution schemas (future extensibility)

class ToolExecutionRequest(ExecutionRequest):
    """
    Execute an MCP tool by reference.
    
    Extends ExecutionRequest with tool-specific fields.
    """
    tool_name: Optional[str] = Field(
        None,
        description="Tool identifier (alternative to path)"
    )
    tool_version: Optional[str] = Field(
        default="latest",
        description="Tool version"
    )
    arguments: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Tool-specific arguments (alias for parameters)"
    )
    
    @model_validator(mode='after')
    def set_tool_defaults(self):
        """Set tool-specific defaults."""
        self.type = "tool"
        if self.tool_name and not self.path:
            self.path = f"tools/{self.tool_name}"
        if self.tool_version:
            self.version = self.tool_version
        if self.arguments and not self.parameters:
            self.parameters = self.arguments
        return self


class ModelExecutionRequest(ExecutionRequest):
    """
    Execute an MCP model inference.
    
    Extends ExecutionRequest with model-specific fields.
    """
    model_name: Optional[str] = Field(
        None,
        description="Model identifier (alternative to path)"
    )
    model_version: Optional[str] = Field(
        default="latest",
        description="Model version"
    )
    inputs: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Model inputs (alias for parameters)"
    )
    inference_config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Inference configuration (temperature, max_tokens, etc.)"
    )
    
    @model_validator(mode='after')
    def set_model_defaults(self):
        """Set model-specific defaults."""
        self.type = "model"
        if self.model_name and not self.path:
            self.path = f"models/{self.model_name}"
        if self.model_version:
            self.version = self.model_version
        if self.inputs and not self.parameters:
            self.parameters = self.inputs
        if self.inference_config:
            if not self.metadata:
                self.metadata = {}
            self.metadata["inference_config"] = self.inference_config
        return self


__all__ = [
    "ExecutionType",
    "ExecutionContext",
    "ExecutionRequest",
    "ExecutionResponse",
    "ExecutionListQuery",
    "ExecutionListResponse",
    "ToolExecutionRequest",
    "ModelExecutionRequest",
]
