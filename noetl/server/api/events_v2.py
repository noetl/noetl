"""
NoETL v2 Event API - Server-side event processing endpoint.

Server receives events from workers and internal components,
processes them through the control flow engine, and generates commands.
"""

from typing import List

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from noetl.core.logger import setup_logger
from noetl.core.dsl.v2.engine import ControlFlowEngine, PlaybookRepo, StateStore
from noetl.core.dsl.v2.models import Event as V2Event, Command as V2Command

logger = setup_logger(__name__, include_location=True)

# Initialize engine components (in production, these would be dependency-injected)
playbook_repo = PlaybookRepo()
state_store = StateStore()
engine = ControlFlowEngine(playbook_repo, state_store)

router = APIRouter(prefix="/api/v2", tags=["events-v2"])


# ============================================================================
# Request/Response Schemas
# ============================================================================


class EventSubmitRequest(BaseModel):
    """Request schema for event submission."""
    
    execution_id: str = Field(..., description="Execution identifier")
    step: str | None = Field(None, description="Step name")
    name: str = Field(..., description="Event name (e.g., 'step.enter', 'call.done')")
    payload: dict = Field(default_factory=dict, description="Event payload")
    worker_id: str | None = Field(None, description="Worker identifier")
    attempt: int = Field(default=1, description="Attempt number")


class CommandResponse(BaseModel):
    """Response schema for generated command."""
    
    execution_id: str
    step: str
    tool_kind: str
    args: dict | None = None
    attempt: int = 1


class EventProcessResponse(BaseModel):
    """Response schema for event processing."""
    
    status: str = Field(..., description="Processing status")
    commands_generated: int = Field(..., description="Number of commands generated")
    commands: List[CommandResponse] = Field(default_factory=list, description="Generated commands")
    message: str | None = Field(None, description="Optional message")


# ============================================================================
# Endpoints
# ============================================================================


@router.post("/events", response_model=EventProcessResponse)
async def submit_event(request: EventSubmitRequest) -> EventProcessResponse:
    """
    Submit an event for processing.
    
    Workers and internal components submit events here.
    The engine evaluates DSL rules and generates commands for the queue.
    
    Args:
        request: Event data
        
    Returns:
        EventProcessResponse with generated commands
    """
    try:
        logger.info(
            f"Received event: execution={request.execution_id}, "
            f"step={request.step}, name={request.name}"
        )
        
        # Convert to v2 Event model
        event = V2Event(
            execution_id=request.execution_id,
            step=request.step,
            name=request.name,
            payload=request.payload,
            worker_id=request.worker_id,
            attempt=request.attempt,
        )
        
        # Process through engine
        commands = engine.handle_event(event)
        
        # Convert commands to response format
        command_responses = [
            CommandResponse(
                execution_id=cmd.execution_id,
                step=cmd.step,
                tool_kind=cmd.tool.kind,
                args=cmd.args,
                attempt=cmd.attempt,
            )
            for cmd in commands
        ]
        
        # Insert commands into queue (placeholder - implement queue insertion)
        await _insert_commands_to_queue(commands)
        
        logger.info(
            f"Event processed: {len(commands)} command(s) generated "
            f"for execution {request.execution_id}"
        )
        
        return EventProcessResponse(
            status="processed",
            commands_generated=len(commands),
            commands=command_responses,
            message=f"Event processed successfully, {len(commands)} command(s) queued",
        )
        
    except Exception as e:
        logger.exception(f"Error processing event: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process event: {str(e)}",
        )


@router.get("/health")
async def health_check():
    """Health check endpoint for v2 event API."""
    return {
        "status": "healthy",
        "service": "noetl-v2-event-api",
        "engine": "ready",
    }


# ============================================================================
# Queue Operations (Server is ONLY writer)
# ============================================================================


async def _insert_commands_to_queue(commands: List[V2Command]) -> None:
    """
    Insert commands into queue table.
    
    This is the ONLY place where queue table is written.
    Workers NEVER write directly to queue.
    
    Args:
        commands: List of Command objects to insert
    """
    if not commands:
        return
    
    # TODO: Implement actual database insertion
    # For now, log the commands
    for cmd in commands:
        logger.info(
            f"QUEUE INSERT: execution={cmd.execution_id}, "
            f"step={cmd.step}, tool={cmd.tool.kind}, attempt={cmd.attempt}"
        )
        
        # In production, insert into noetl.queue table:
        # INSERT INTO noetl.queue (
        #   execution_id, step, tool_kind, tool_config, args, 
        #   context, attempt, status, created_at
        # ) VALUES (...)
    
    logger.debug(f"Inserted {len(commands)} command(s) into queue")


# ============================================================================
# Engine Management (for testing/admin)
# ============================================================================


@router.post("/engine/register-playbook")
async def register_playbook(playbook_yaml: str):
    """
    Register a playbook in the engine.
    
    Admin/testing endpoint to load playbooks into the engine.
    In production, this would sync from catalog.
    """
    try:
        from noetl.core.dsl.v2.parser import parse_playbook_yaml
        
        playbook = parse_playbook_yaml(playbook_yaml)
        playbook_repo.register(playbook)
        
        return {
            "status": "registered",
            "name": playbook.metadata.name,
            "path": playbook.metadata.path,
        }
    except Exception as e:
        logger.exception(f"Failed to register playbook: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid playbook: {str(e)}",
        )
