"""
NoETL DSL v2 Models - Clean event-driven execution model.

NO BACKWARD COMPATIBILITY with v1.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator


# ============================================================================
# EVENT AND COMMAND MODELS (Runtime)
# ============================================================================


class EventName(str, Enum):
    """Standard event names emitted during execution."""
    
    STEP_ENTER = "step.enter"
    CALL_DONE = "call.done"
    STEP_EXIT = "step.exit"
    WORKER_DONE = "worker.done"
    WORKFLOW_START = "workflow.start"
    WORKFLOW_END = "workflow.end"


class Event(BaseModel):
    """Event emitted during execution flow."""
    
    execution_id: str = Field(..., description="Execution identifier")
    step: Optional[str] = Field(None, description="Step name that emitted this event")
    name: str = Field(..., description="Event name (e.g., 'step.enter', 'call.done')")
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Event payload: response, error, timing, metadata"
    )
    created_at: Optional[datetime] = Field(None, description="Event timestamp")
    worker_id: Optional[str] = Field(None, description="Worker that emitted the event")
    attempt: int = Field(default=1, description="Attempt number for retries")
    
    model_config = {"extra": "allow"}


class ToolCall(BaseModel):
    """Tool invocation specification."""
    
    kind: str = Field(..., description="Tool type: http, postgres, python, workbook, etc.")
    config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Tool-specific configuration (method, endpoint, command, code, etc.)"
    )
    
    model_config = {"extra": "allow"}


class Command(BaseModel):
    """Command to be executed by a worker."""
    
    execution_id: str = Field(..., description="Execution identifier")
    step: str = Field(..., description="Step name to execute")
    tool: ToolCall = Field(..., description="Tool configuration")
    args: Optional[Dict[str, Any]] = Field(None, description="Input arguments for this step/tool")
    context: Optional[Dict[str, Any]] = Field(None, description="Execution context (loop state, etc.)")
    attempt: int = Field(default=1, description="Attempt number for retries")
    priority: int = Field(default=0, description="Execution priority")
    
    model_config = {"extra": "allow"}


# ============================================================================
# DSL MODELS (Playbook Structure)
# ============================================================================


class Loop(BaseModel):
    """Step-level loop configuration."""
    
    in_: Union[str, List[Any]] = Field(..., alias="in", description="Collection expression or list")
    iterator: str = Field(..., description="Variable name for current item")
    mode: str = Field(default="sequential", description="Execution mode: sequential, async")
    
    model_config = {"populate_by_name": True, "extra": "allow"}
    
    @field_validator("iterator")
    @classmethod
    def validate_iterator(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Iterator name cannot be empty")
        return v.strip()


class ActionCall(BaseModel):
    """Re-invoke the step's tool with optional overrides."""
    
    params: Optional[Dict[str, Any]] = Field(None, description="Override parameters for HTTP")
    endpoint: Optional[str] = Field(None, description="Override endpoint for HTTP")
    command: Optional[str] = Field(None, description="Override command for SQL tools")
    data: Optional[Dict[str, Any]] = Field(None, description="Override data/payload")
    
    model_config = {"extra": "allow"}


class ActionRetry(BaseModel):
    """Retry configuration for failed calls."""
    
    max_attempts: int = Field(default=3, description="Maximum retry attempts")
    backoff_multiplier: float = Field(default=2.0, description="Backoff multiplier between attempts")
    initial_delay: float = Field(default=0.5, description="Initial delay in seconds")
    
    @field_validator("max_attempts")
    @classmethod
    def validate_max_attempts(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_attempts must be at least 1")
        return v


class ActionCollect(BaseModel):
    """Aggregate data into step context."""
    
    from_: str = Field(..., alias="from", description="Source path expression (e.g., 'response.data')")
    into: str = Field(..., description="Target variable name")
    mode: str = Field(default="append", description="Collection mode: append, extend, replace")
    
    model_config = {"populate_by_name": True}


class ActionSink(BaseModel):
    """Write data to external sink."""
    
    tool: Dict[str, Any] = Field(..., description="Sink tool configuration with tool.kind")
    args: Optional[Dict[str, Any]] = Field(None, description="Arguments for sink operation")
    
    @field_validator("tool")
    @classmethod
    def validate_tool_has_kind(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if "kind" not in v:
            raise ValueError("Sink tool must have 'kind' field")
        return v


class ActionSet(BaseModel):
    """Set context variables."""
    
    ctx: Optional[Dict[str, Any]] = Field(None, description="Context variables to set")
    flags: Optional[Dict[str, Any]] = Field(None, description="Flags to set")
    
    model_config = {"extra": "allow"}


class ActionResult(BaseModel):
    """Set step result payload."""
    
    from_: str = Field(..., alias="from", description="Source expression for result")
    
    model_config = {"populate_by_name": True}


class ActionNext(BaseModel):
    """Conditional transition to next step(s)."""
    
    step: str = Field(..., description="Target step name")
    args: Optional[Dict[str, Any]] = Field(None, description="Arguments to pass to next step")


class ActionFail(BaseModel):
    """Mark step/workflow as failed."""
    
    message: str = Field(..., description="Failure message")
    fail_workflow: bool = Field(default=False, description="Whether to fail entire workflow")


class ActionSkip(BaseModel):
    """Mark step as skipped."""
    
    reason: Optional[str] = Field(None, description="Skip reason")


class ThenBlock(BaseModel):
    """Actions to execute when case condition is true."""
    
    call: Optional[ActionCall] = Field(None, description="Re-invoke tool")
    retry: Optional[ActionRetry] = Field(None, description="Retry configuration")
    collect: Optional[ActionCollect] = Field(None, description="Collect data")
    sink: Optional[ActionSink] = Field(None, description="Write to sink")
    set: Optional[ActionSet] = Field(None, description="Set context variables")
    result: Optional[ActionResult] = Field(None, description="Set step result")
    next: Optional[List[ActionNext]] = Field(None, description="Transition to next steps")
    fail: Optional[ActionFail] = Field(None, description="Fail step/workflow")
    skip: Optional[ActionSkip] = Field(None, description="Skip step")
    
    model_config = {"extra": "allow"}
    
    @model_validator(mode="after")
    def validate_at_least_one_action(self) -> ThenBlock:
        """Ensure at least one action is specified."""
        actions = [
            self.call, self.retry, self.collect, self.sink,
            self.set, self.result, self.next, self.fail, self.skip
        ]
        if not any(action is not None for action in actions):
            raise ValueError("ThenBlock must have at least one action")
        return self


class CaseEntry(BaseModel):
    """Conditional case with when/then structure."""
    
    when: str = Field(..., description="Jinja2 condition expression")
    then: ThenBlock = Field(..., description="Actions to execute when condition is true")
    
    @field_validator("when")
    @classmethod
    def validate_when(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("when condition cannot be empty")
        return v.strip()


class ToolSpec(BaseModel):
    """Tool configuration with kind-specific fields."""
    
    kind: str = Field(..., description="Tool type: http, postgres, python, workbook, etc.")
    
    # HTTP fields
    method: Optional[str] = Field(None, description="HTTP method")
    endpoint: Optional[str] = Field(None, description="HTTP endpoint")
    url: Optional[str] = Field(None, description="HTTP URL (alternative to endpoint)")
    headers: Optional[Dict[str, Any]] = Field(None, description="HTTP headers")
    params: Optional[Dict[str, Any]] = Field(None, description="HTTP query parameters")
    data: Optional[Any] = Field(None, description="HTTP request body")
    payload: Optional[Dict[str, Any]] = Field(None, description="HTTP payload (alternative to data)")
    
    # SQL fields (postgres, duckdb, etc.)
    auth: Optional[str] = Field(None, description="Authentication credential reference")
    command: Optional[str] = Field(None, description="SQL command")
    query: Optional[str] = Field(None, description="SQL query (alternative to command)")
    
    # Python fields
    code: Optional[str] = Field(None, description="Python code to execute")
    
    # Workbook fields
    task: Optional[str] = Field(None, description="Workbook task name")
    with_: Optional[Dict[str, Any]] = Field(None, alias="with", description="Task arguments")
    
    # Playbook fields
    path: Optional[str] = Field(None, description="Sub-playbook path")
    return_step: Optional[str] = Field(None, description="Return step name")
    
    model_config = {"populate_by_name": True, "extra": "allow"}
    
    @field_validator("kind")
    @classmethod
    def validate_kind(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Tool kind cannot be empty")
        return v.strip()


class Step(BaseModel):
    """Step definition in workflow."""
    
    step: str = Field(..., description="Step name")
    desc: Optional[str] = Field(None, description="Step description")
    args: Optional[Dict[str, Any]] = Field(None, description="Input arguments")
    loop: Optional[Loop] = Field(None, description="Step-level loop configuration")
    tool: ToolSpec = Field(..., description="Tool configuration")
    case: Optional[List[CaseEntry]] = Field(None, description="Conditional behavior rules")
    next: Optional[Union[str, List[str]]] = Field(None, description="Unconditional next step(s)")
    
    @field_validator("step")
    @classmethod
    def validate_step_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Step name cannot be empty")
        return v.strip()
    
    @model_validator(mode="after")
    def validate_next_format(self) -> Step:
        """Validate that next doesn't contain conditional structures."""
        if isinstance(self.next, dict):
            if any(k in self.next for k in ["when", "then", "else"]):
                raise ValueError(
                    "Step-level 'next' must be unconditional. "
                    "Use 'case' with 'then.next' for conditional transitions."
                )
        return self


class Metadata(BaseModel):
    """Playbook metadata."""
    
    name: str = Field(..., description="Playbook name")
    path: str = Field(..., description="Catalog path")
    version: Optional[str] = Field(None, description="Playbook version")
    
    model_config = {"extra": "allow"}


class Workbook(BaseModel):
    """Named reusable task definition."""
    
    name: str = Field(..., description="Task name")
    tool: ToolSpec = Field(..., description="Tool configuration")
    sink: Optional[ActionSink] = Field(None, description="Optional sink for task result")
    
    model_config = {"extra": "allow"}


class Playbook(BaseModel):
    """Complete playbook definition v2."""
    
    apiVersion: str = Field(default="noetl.io/v2", description="API version")
    kind: str = Field(default="Playbook", description="Resource kind")
    metadata: Metadata = Field(..., description="Playbook metadata")
    workload: Optional[Dict[str, Any]] = Field(None, description="Global variables")
    workbook: Optional[List[Workbook]] = Field(None, description="Named reusable tasks")
    workflow: List[Step] = Field(..., description="Workflow steps")
    
    @field_validator("apiVersion")
    @classmethod
    def validate_api_version(cls, v: str) -> str:
        if not v.startswith("noetl.io/"):
            raise ValueError("apiVersion must start with 'noetl.io/'")
        return v
    
    @model_validator(mode="after")
    def validate_workflow_has_start(self) -> Playbook:
        """Ensure workflow has a 'start' step."""
        step_names = [step.step for step in self.workflow]
        if "start" not in step_names:
            raise ValueError("Workflow must have a step named 'start'")
        return self
    
    @model_validator(mode="after")
    def validate_step_references(self) -> Playbook:
        """Validate that next step references exist."""
        step_names = set(step.step for step in self.workflow)
        
        for step in self.workflow:
            # Check unconditional next
            if step.next:
                next_steps = [step.next] if isinstance(step.next, str) else step.next
                for next_step in next_steps:
                    if next_step not in step_names and next_step != "end":
                        raise ValueError(
                            f"Step '{step.step}' references non-existent step '{next_step}'"
                        )
            
            # Check case-based next
            if step.case:
                for case_entry in step.case:
                    if case_entry.then.next:
                        for action_next in case_entry.then.next:
                            if action_next.step not in step_names and action_next.step != "end":
                                raise ValueError(
                                    f"Step '{step.step}' case references non-existent step '{action_next.step}'"
                                )
        
        return self
