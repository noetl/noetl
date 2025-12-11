"""
NoETL Server Event API (v2)

POST /api/v2/events endpoint that:
- Receives events from workers
- Calls ControlFlowEngine.handle_event()
- Inserts generated commands into queue table
- Server is the ONLY component that writes to queue table
"""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Any, Optional
from datetime import datetime

from noetl.core.dsl.v2.models import Event, Command
from noetl.core.dsl.v2.engine import ControlFlowEngine, PlaybookRepo, StateStore
from noetl.core.config import get_db_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2", tags=["events-v2"])

# Global engine components (initialized on startup)
_playbook_repo: Optional[PlaybookRepo] = None
_state_store: Optional[StateStore] = None
_engine: Optional[ControlFlowEngine] = None


def initialize_engine():
    """Initialize engine components."""
    global _playbook_repo, _state_store, _engine
    
    if _playbook_repo is None:
        _playbook_repo = PlaybookRepo()
    
    if _state_store is None:
        _state_store = StateStore()
    
    if _engine is None:
        _engine = ControlFlowEngine(_playbook_repo, _state_store)
    
    return _engine, _playbook_repo


# ============================================================================
# Request/Response Models
# ============================================================================

class EventRequest(BaseModel):
    """Request body for POST /api/v2/events."""
    execution_id: str = Field(..., description="Execution identifier")
    step: Optional[str] = Field(None, description="Step name")
    name: str = Field(..., description="Event name (step.enter, call.done, etc.)")
    payload: dict[str, Any] = Field(default_factory=dict, description="Event payload")
    worker_id: Optional[str] = Field(None, description="Worker ID")
    attempt: int = Field(default=1, description="Attempt number")


class EventResponse(BaseModel):
    """Response for POST /api/v2/events."""
    status: str = Field(..., description="Status (ok, error)")
    commands_generated: int = Field(..., description="Number of commands generated")
    message: Optional[str] = Field(None, description="Optional message")


# ============================================================================
# API Endpoints
# ============================================================================

@router.post("/events", response_model=EventResponse)
async def receive_event(event_req: EventRequest) -> EventResponse:
    """
    Receive event from worker or internal component.
    
    Flow:
    1. Deserialize to Event model
    2. Call ControlFlowEngine.handle_event()
    3. Insert generated commands into queue table
    4. Return ACK
    
    This is the ONLY way commands enter the queue table.
    Workers NEVER write to queue directly.
    """
    try:
        # Initialize engine if needed
        engine, _ = initialize_engine()
        
        # Create Event object
        event = Event(
            execution_id=event_req.execution_id,
            step=event_req.step,
            name=event_req.name,
            payload=event_req.payload,
            timestamp=datetime.utcnow(),
            worker_id=event_req.worker_id,
            attempt=event_req.attempt
        )
        
        logger.info(f"Received event: {event.execution_id} / {event.name} / {event.step}")
        
        # Process event through engine
        commands = engine.handle_event(event)
        
        logger.info(f"Generated {len(commands)} commands")
        
        # Insert commands into queue table
        if commands:
            await _insert_commands_to_queue(commands)
        
        return EventResponse(
            status="ok",
            commands_generated=len(commands),
            message=f"Processed event {event.name}"
        )
    
    except Exception as e:
        logger.error(f"Error processing event: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing event: {str(e)}")


@router.post("/playbooks/register")
async def register_playbook(
    playbook_yaml: str = Field(..., description="Playbook YAML content"),
    execution_id: str = Field(..., description="Execution ID")
) -> dict[str, str]:
    """
    Register playbook for an execution.
    
    This should be called before starting workflow execution
    to associate a playbook with an execution_id.
    """
    try:
        engine, playbook_repo = initialize_engine()
        
        from noetl.core.dsl.v2.parser import DSLParser
        parser = DSLParser()
        
        # Parse playbook
        playbook = parser.parse(playbook_yaml)
        
        # Register
        playbook_repo.register(playbook, execution_id)
        
        logger.info(f"Registered playbook {playbook.metadata['name']} for execution {execution_id}")
        
        return {
            "status": "ok",
            "playbook": playbook.metadata["name"],
            "execution_id": execution_id
        }
    
    except Exception as e:
        logger.error(f"Error registering playbook: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error registering playbook: {str(e)}")


# ============================================================================
# Queue Table Operations
# ============================================================================

async def _insert_commands_to_queue(commands: list[Command]):
    """
    Insert commands into queue table.
    
    This is the ONLY place where queue table is written to.
    Uses async psycopg connection pool.
    """
    try:
        # Get connection pool
        pool = get_db_pool()
        
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                for command in commands:
                    # Convert command to queue record
                    record = command.to_queue_record()
                    
                    # Build INSERT statement
                    columns = list(record.keys())
                    placeholders = ", ".join([f"${i+1}" for i in range(len(columns))])
                    column_names = ", ".join(columns)
                    
                    sql = f"""
                        INSERT INTO noetl.queue ({column_names})
                        VALUES ({placeholders})
                    """
                    
                    values = [record[col] for col in columns]
                    
                    await cur.execute(sql, values)
                
                await conn.commit()
        
        logger.info(f"Inserted {len(commands)} commands into queue table")
    
    except Exception as e:
        logger.error(f"Error inserting commands to queue: {e}", exc_info=True)
        raise


# ============================================================================
# Health Check
# ============================================================================

@router.get("/health")
async def health_check() -> dict[str, str]:
    """Health check for v2 event API."""
    try:
        engine, _ = initialize_engine()
        return {"status": "ok", "component": "events-v2"}
    except Exception as e:
        return {"status": "error", "error": str(e)}
