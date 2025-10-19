"""
Context API request/response schemas.
"""

from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field


class RenderContextRequest(BaseModel):
    """Request to render a template against execution context."""
    
    execution_id: str = Field(..., description="Execution ID to fetch context for")
    template: Any = Field(..., description="Template to render (can be any JSON structure)")
    extra_context: Optional[Dict[str, Any]] = Field(None, description="Additional context to merge")
    strict: bool = Field(True, description="Whether to use strict undefined handling")


class RenderContextResponse(BaseModel):
    """Response from rendering a template."""
    
    status: str = Field(..., description="Status of rendering operation")
    rendered: Any = Field(..., description="Rendered result")
    context_keys: List[str] = Field(..., description="Available context keys during rendering")
