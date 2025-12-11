"""
NoETL V2 API Endpoints

Clean V2 API for event-driven playbook execution.
No backward compatibility.
"""

import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Any, Optional
from datetime import datetime, timezone
from psycopg.types.json import Json

from noetl.core.dsl.v2.models import Event, Command
from noetl.core.dsl.v2.engine import ControlFlowEngine, PlaybookRepo, StateStore
from noetl.core.db.pool import get_pool_connection, get_snowflake_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v2", tags=["v2"])

# Global engine components
_playbook_repo: Optional[PlaybookRepo] = None
_state_store: Optional[StateStore] = None
_engine: Optional[ControlFlowEngine] = None


def get_engine():
    """Get or initialize engine."""
    global _playbook_repo, _state_store, _engine
    
    if _engine is None:
        _playbook_repo = PlaybookRepo()
        _state_store = StateStore()
        _engine = ControlFlowEngine(_playbook_repo, _state_store)
    
    return _engine


# ============================================================================
# Request/Response Models
# ============================================================================

class StartExecutionRequest(BaseModel):
    """Request to start playbook execution."""
    path: str = Field(..., description="Playbook catalog path")
    payload: dict[str, Any] = Field(default_factory=dict, description="Input payload")


class StartExecutionResponse(BaseModel):
    """Response for starting execution."""
    execution_id: str = Field(..., description="Generated execution ID")
    status: str = Field(..., description="Status (started)")
    commands_generated: int = Field(..., description="Number of initial commands")


class EventRequest(BaseModel):
    """Worker event."""
    execution_id: str = Field(..., description="Execution ID")
    step: str = Field(..., description="Step name")
    name: str = Field(..., description="Event name (step.enter, call.done, step.exit)")
    payload: dict[str, Any] = Field(default_factory=dict, description="Event data")
    worker_id: Optional[str] = Field(None, description="Worker ID")


class EventResponse(BaseModel):
    """Response for event."""
    status: str = Field(..., description="Status (ok)")
    commands_generated: int = Field(..., description="Commands generated")


# ============================================================================
# API Endpoints
# ============================================================================

@router.post("/execute", response_model=StartExecutionResponse)
async def start_execution(req: StartExecutionRequest) -> StartExecutionResponse:
    """
    Start a new playbook execution.
    
    This is the entry point for triggering playbooks in v2.
    """
    try:
        engine = get_engine()
        
        # Get catalog_id first
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT catalog_id FROM noetl.catalog 
                    WHERE path = %s 
                    ORDER BY version DESC 
                    LIMIT 1
                """, (req.path,))
                result = await cur.fetchone()
                
                if not result:
                    raise HTTPException(status_code=404, detail=f"Playbook not found: {req.path}")
                
                catalog_id = result['catalog_id']
        
        # Start execution (creates state, returns initial commands)
        execution_id, commands = await engine.start_execution(
            req.path,
            req.payload,
            catalog_id
        )
        
        # Enqueue commands to database
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                for command in commands:
                    # Insert into queue
                    queue_id = await get_snowflake_id()
                    await cur.execute("""
                        INSERT INTO noetl.queue (
                            queue_id, execution_id, catalog_id, node_id,
                            action, context, status, priority, attempts,
                            max_attempts, created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        queue_id,
                        int(execution_id),
                        catalog_id,
                        command.step,
                        command.tool.kind,
                        Json({"tool_config": command.tool.config, "args": command.args}),
                        "queued",
                        command.priority,
                        0,
                        command.max_attempts or 3,
                        datetime.now(timezone.utc),
                        datetime.now(timezone.utc)
                    ))
                await conn.commit()
        
        return StartExecutionResponse(
            execution_id=execution_id,
            status="started",
            commands_generated=len(commands)
        )
    
    except Exception as e:
        logger.error(f"Failed to start execution: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/events", response_model=EventResponse)
async def handle_event(req: EventRequest) -> EventResponse:
    """
    Handle event from worker.
    
    Workers send events here after completing actions.
    Engine evaluates case/when/then rules and generates next commands.
    """
    try:
        engine = get_engine()
        
        # Create Event
        event = Event(
            execution_id=req.execution_id,
            step=req.step,
            name=req.name,
            payload=req.payload,
            timestamp=datetime.now(timezone.utc),
            worker_id=req.worker_id,
            attempt=1
        )
        
        # Process event through engine
        commands = await engine.handle_event(event)
        
        # Enqueue generated commands
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                for command in commands:
                    # Get catalog_id from execution
                    await cur.execute("""
                        SELECT catalog_id FROM noetl.event 
                        WHERE execution_id = %s 
                        LIMIT 1
                    """, (int(req.execution_id),))
                    result = await cur.fetchone()
                    
                    catalog_id = result['catalog_id'] if result else 1
                    if not result:
                        logger.warning(f"No catalog_id found for execution {req.execution_id}")
                    
                    # Insert command into queue
                    queue_id = await get_snowflake_id()
                    await cur.execute("""
                        INSERT INTO noetl.queue (
                            queue_id, execution_id, catalog_id, node_id,
                            action, context, status, priority, attempts,
                            max_attempts, created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        queue_id,
                        int(command.execution_id),
                        catalog_id,
                        command.step,
                        command.tool.kind,
                        Json({"tool_config": command.tool.config, "args": command.args}),
                        "queued",
                        command.priority,
                        0,
                        command.max_attempts or 3,
                        datetime.now(timezone.utc),
                        datetime.now(timezone.utc)
                    ))
                await conn.commit()
        
        return EventResponse(
            status="ok",
            commands_generated=len(commands)
        )
    
    except Exception as e:
        logger.error(f"Failed to handle event: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/executions/{execution_id}")
async def get_execution_status(execution_id: str):
    """Get execution status."""
    try:
        engine = get_engine()
        state = engine.state_store.get_state(execution_id)
        
        if not state:
            raise HTTPException(status_code=404, detail="Execution not found")
        
        return {
            "execution_id": execution_id,
            "current_step": state.current_step,
            "completed_steps": list(state.completed_steps),
            "failed": state.failed,
            "completed": state.completed,
            "variables": state.variables,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get execution status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
