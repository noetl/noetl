"""
NoETL V2 API Endpoints

Clean V2 API for event-driven playbook execution.
No backward compatibility.
"""

import logging
import os
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field, model_validator
from typing import Any, Optional
from datetime import datetime, timezone
from psycopg.types.json import Json

from noetl.core.dsl.v2.models import Event, Command
from noetl.core.dsl.v2.engine import ControlFlowEngine, PlaybookRepo, StateStore
from noetl.core.db.pool import get_pool_connection, get_snowflake_id
from noetl.core.messaging import NATSCommandPublisher

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v2", tags=["v2"])

# Global engine components
_playbook_repo: Optional[PlaybookRepo] = None
_state_store: Optional[StateStore] = None
_engine: Optional[ControlFlowEngine] = None
_nats_publisher: Optional[NATSCommandPublisher] = None


def get_engine():
    """Get or initialize engine."""
    global _playbook_repo, _state_store, _engine
    
    if _engine is None:
        _playbook_repo = PlaybookRepo()
        _state_store = StateStore()
        _engine = ControlFlowEngine(_playbook_repo, _state_store)
    
    return _engine


async def get_nats_publisher():
    """Get or initialize NATS publisher."""
    global _nats_publisher
    
    if _nats_publisher is None:
        nats_url = os.getenv("NATS_URL", "nats://noetl:noetl@nats.nats.svc.cluster.local:4222")
        _nats_publisher = NATSCommandPublisher(nats_url=nats_url)
        await _nats_publisher.connect()
        logger.info(f"NATS publisher initialized: {nats_url}")
    
    return _nats_publisher


# ============================================================================
# Request/Response Models
# ============================================================================

class StartExecutionRequest(BaseModel):
    """Request to start playbook execution."""
    path: Optional[str] = Field(None, description="Playbook catalog path")
    catalog_id: Optional[int] = Field(None, description="Catalog ID (alternative to path)")
    payload: dict[str, Any] = Field(default_factory=dict, description="Input payload")
    parent_execution_id: Optional[int] = Field(None, description="Parent execution ID for sub-playbooks")
    
    @model_validator(mode='after')
    def validate_path_or_catalog_id(self):
        if not self.path and not self.catalog_id:
            raise ValueError("Either 'path' or 'catalog_id' must be provided")
        return self


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
    meta: Optional[dict[str, Any]] = Field(None, description="Event metadata")
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
        
        # Get catalog_id and path
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                if req.catalog_id:
                    # Get path from catalog_id
                    await cur.execute("""
                        SELECT path, catalog_id FROM noetl.catalog 
                        WHERE catalog_id = %s
                    """, (req.catalog_id,))
                    result = await cur.fetchone()
                    if not result:
                        raise HTTPException(status_code=404, detail=f"Playbook not found with catalog_id: {req.catalog_id}")
                    path = result['path']
                    catalog_id = result['catalog_id']
                else:
                    # Get catalog_id from path
                    await cur.execute("""
                        SELECT catalog_id, path FROM noetl.catalog 
                        WHERE path = %s 
                        ORDER BY version DESC 
                        LIMIT 1
                    """, (req.path,))
                    result = await cur.fetchone()
                    if not result:
                        raise HTTPException(status_code=404, detail=f"Playbook not found: {req.path}")
                    catalog_id = result['catalog_id']
                    path = result['path']
        
        # Start execution (creates state, returns initial commands)
        execution_id, commands = await engine.start_execution(
            path,
            req.payload,
            catalog_id,
            req.parent_execution_id
        )
        
        # Get playbook_initialized event_id for tracing
        playbook_init_event_id = None
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT event_id FROM noetl.event
                    WHERE execution_id = %s AND event_type = 'playbook_initialized'
                    ORDER BY event_id DESC LIMIT 1
                """, (int(execution_id),))
                result = await cur.fetchone()
                if result:
                    playbook_init_event_id = result['event_id']
        
        # Get NATS publisher
        nats_pub = await get_nats_publisher()
        
        # Server URL for worker API calls
        server_url = os.getenv("SERVER_API_URL", "http://noetl.noetl.svc.cluster.local:8082")
        
        # Enqueue commands to database and publish to NATS
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                for command in commands:
                    # Insert into queue
                    queue_id = await get_snowflake_id()
                    await cur.execute("""
                        INSERT INTO noetl.queue (
                            queue_id, execution_id, catalog_id, node_id, node_name,
                            action, context, status, priority, attempts,
                            max_attempts, parent_execution_id, event_id,
                            node_type, meta, created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        queue_id,
                        int(execution_id),
                        catalog_id,
                        command.step,
                        command.step,  # node_name = node_id for V2 DSL
                        command.tool.kind,
                        Json({"tool_config": command.tool.config, "args": command.args}),
                        "queued",
                        command.priority,
                        0,
                        command.max_attempts or 3,
                        req.parent_execution_id,
                        playbook_init_event_id,
                        command.tool.kind,
                        Json({
                            "playbook_path": path,
                            "catalog_id": catalog_id,
                            "triggered_by": "start_execution",
                            "playbook_init_event_id": playbook_init_event_id,
                            "parent_execution_id": req.parent_execution_id,
                            "step": command.step,
                            "tool": command.tool.kind,
                            "priority": command.priority,
                            "metadata": command.metadata
                        }),
                        datetime.now(timezone.utc),
                        datetime.now(timezone.utc)
                    ))
                    
                    # Publish notification to NATS
                    await nats_pub.publish_command(
                        execution_id=int(execution_id),
                        queue_id=queue_id,
                        step=command.step,
                        server_url=server_url
                    )
                    
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
        
        # Get current attempt from queue table and store in meta
        attempt = 1
        try:
            async with get_pool_connection() as conn:
                result = await conn.fetchrow(
                    """
                    SELECT attempts 
                    FROM noetl.queue 
                    WHERE execution_id = $1 AND node_name = $2
                    ORDER BY queue_id DESC 
                    LIMIT 1
                    """,
                    int(req.execution_id),
                    req.step
                )
                if result and result["attempts"]:
                    attempt = result["attempts"]
        except Exception as e:
            logger.warning(f"Could not fetch attempt from queue: {e}, using default attempt=1")
        
        # Create Event with attempt in meta
        event_meta = req.meta or {}
        event_meta["attempt"] = attempt
        
        event = Event(
            execution_id=req.execution_id,
            step=req.step,
            name=req.name,
            payload=req.payload,
            meta=event_meta,
            timestamp=datetime.now(timezone.utc),
            worker_id=req.worker_id,
            attempt=attempt  # Keep for in-memory processing
        )
        
        # Process event through engine
        commands = await engine.handle_event(event)
        
        # Get NATS publisher
        nats_pub = await get_nats_publisher()
        
        # Server URL for worker API calls
        server_url = os.getenv("SERVER_API_URL", "http://noetl.noetl.svc.cluster.local:8082")
        
        # Enqueue generated commands and publish to NATS
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                for command in commands:
                    # Get catalog_id, parent_execution_id, and triggering event details
                    await cur.execute("""
                        SELECT catalog_id, parent_execution_id, event_id, parent_event_id
                        FROM noetl.event 
                        WHERE execution_id = %s 
                        ORDER BY event_id DESC
                        LIMIT 1
                    """, (int(req.execution_id),))
                    result = await cur.fetchone()
                    
                    if not result:
                        logger.warning(f"No events found for execution {req.execution_id}")
                        catalog_id = 1
                        parent_execution_id = None
                        triggering_event_id = None
                        triggering_parent_event_id = None
                    else:
                        catalog_id = result['catalog_id']
                        parent_execution_id = result['parent_execution_id']
                        triggering_event_id = result['event_id']
                        triggering_parent_event_id = result['parent_event_id']
                    
                    # Delete any existing queue entry for this execution+node (for loop iterations)
                    await cur.execute("""
                        DELETE FROM noetl.queue
                        WHERE execution_id = %s AND node_id = %s
                    """, (int(command.execution_id), command.step))
                    
                    # Insert command into queue
                    queue_id = await get_snowflake_id()
                    await cur.execute("""
                        INSERT INTO noetl.queue (
                            queue_id, execution_id, catalog_id, node_id, node_name,
                            action, context, status, priority, attempts,
                            max_attempts, parent_execution_id, parent_event_id, 
                            event_id, node_type, meta, created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        queue_id,
                        int(command.execution_id),
                        catalog_id,
                        command.step,
                        command.step,  # node_name = node_id for V2 DSL
                        command.tool.kind,
                        Json({"tool_config": command.tool.config, "args": command.args}),
                        "queued",
                        command.priority,
                        0,
                        command.max_attempts or 3,
                        parent_execution_id,
                        triggering_parent_event_id,
                        triggering_event_id,
                        command.tool.kind,
                        Json({
                            "catalog_id": catalog_id,
                            "triggered_by": "event_handler",
                            "triggering_event_id": triggering_event_id,
                            "parent_event_id": triggering_parent_event_id,
                            "parent_execution_id": parent_execution_id,
                            "step": command.step,
                            "tool": command.tool.kind,
                            "priority": command.priority,
                            "metadata": command.metadata,
                            "event_type": event.name,
                            "event_step": event.step
                        }),
                        datetime.now(timezone.utc),
                        datetime.now(timezone.utc)
                    ))
                    
                    # Publish notification to NATS
                    await nats_pub.publish_command(
                        execution_id=int(command.execution_id),
                        queue_id=queue_id,
                        step=command.step,
                        server_url=server_url
                    )
                    
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
