"""Pydantic models for resource execution endpoint."""

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class ResourceRunRequest(BaseModel):
    """Request payload for `/resource/run`."""

    path: str = Field(..., description="Catalog path to execute")
    version: Optional[str] = Field(
        default=None,
        description="Specific catalog version. Uses latest when omitted.",
    )
    payload: Optional[Union[Dict[str, Any], str]] = Field(
        default=None,
        description="Optional payload merged with playbook workload before kickoff.",
    )
    merge: bool = Field(
        default=False,
        description="Merge payload into workload when true; otherwise payload replaces workload.",
    )


class DispatchedStep(BaseModel):
    """Metadata about each step dispatched by the service."""

    name: str = Field(..., description="Workflow step name")
    node_type: str = Field(..., description="Task type resolved from workflow definition")
    actionable: bool = Field(..., description="Indicates whether the step was enqueued")
    queue_id: Optional[str] = Field(
        default=None,
        description="Queue identifier when the step was enqueued",
    )


class ResourceRunResponse(BaseModel):
    """Response returned after resource execution kickoff."""

    execution_id: str = Field(..., description="Execution identifier for tracking")
    catalog_id: str = Field(..., description="Catalog identifier used for the run")
    path: str = Field(..., description="Executed catalog path")
    version: str = Field(..., description="Catalog version resolved for execution")
    workload: Dict[str, Any] = Field(..., description="Final workload persisted for execution")
    steps: List[DispatchedStep] = Field(
        default_factory=list,
        description="Actionable steps evaluated from the start transition",
    )
