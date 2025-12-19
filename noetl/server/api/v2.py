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
        _state_store = StateStore(_playbook_repo)  # Pass playbook_repo for event sourcing
        _engine = ControlFlowEngine(_playbook_repo, _state_store)
    
    return _engine


async def get_nats_publisher():
    """Get or initialize NATS publisher."""
    global _nats_publisher
    
    if _nats_publisher is None:
        from noetl.core.config import settings
        _nats_publisher = NATSCommandPublisher(
            nats_url=settings.nats_url,
            subject=settings.nats_subject
        )
        await _nats_publisher.connect()
        logger.info(f"NATS publisher initialized: {settings.nats_url}")
    
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
        # Note: Keychain processing happens inside engine.start_execution
        execution_id, commands = await engine.start_execution(
            path,
            req.payload,
            catalog_id,
            req.parent_execution_id
        )
        
        # Get playbook.initialized event_id for tracing (root event)
        playbook_init_event_id = None
        root_event_id = None
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT event_id FROM noetl.event
                    WHERE execution_id = %s AND event_type = 'playbook.initialized'
                    ORDER BY event_id ASC LIMIT 1
                """, (int(execution_id),))
                result = await cur.fetchone()
                if result:
                    playbook_init_event_id = result['event_id']
                    root_event_id = result['event_id']  # First event is the root
        
        # Get NATS publisher
        nats_pub = await get_nats_publisher()
        
        # Server URL for worker API calls
        server_url = os.getenv("SERVER_API_URL", "http://noetl.noetl.svc.cluster.local:8082")
        
        # Emit command.issued events instead of queue table insertion
        command_events = []  # Store (event_id, command) for NATS publishing after commit
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                for command in commands:
                    # Generate unique command ID
                    command_id = f"{execution_id}:{command.step}:{await get_snowflake_id()}"
                    event_id = await get_snowflake_id()
                    
                    # Build traceability metadata
                    meta = {
                        "command_id": command_id,
                        "step": command.step,
                        "tool_kind": command.tool.kind,
                        "priority": command.priority,
                        "max_attempts": command.max_attempts or 3,
                        "attempt": 1,
                        "playbook_path": path,
                        "catalog_id": catalog_id,
                        "metadata": command.metadata,
                        # Traceability fields
                        "execution_id": str(execution_id),
                        "root_event_id": root_event_id,
                        "event_chain": [root_event_id, playbook_init_event_id, event_id] if root_event_id else [event_id]
                    }
                    
                    # Ensure context has traceability fields
                    context_data = {
                        "tool_config": command.tool.config,
                        "args": command.args or {},
                        "render_context": command.render_context,
                        # Add traceability to context for easy access
                        "execution_id": str(execution_id),
                        "catalog_id": catalog_id,
                        "root_event_id": root_event_id
                    }
                    
                    # Insert command.issued event
                    await cur.execute("""
                        INSERT INTO noetl.event (
                            event_id, execution_id, catalog_id, event_type,
                            node_id, node_name, node_type, status,
                            context, meta, parent_event_id, parent_execution_id,
                            created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        event_id,
                        int(execution_id),
                        catalog_id,
                        "command.issued",
                        command.step,
                        command.step,
                        command.tool.kind,
                        "PENDING",
                        Json(context_data),
                        Json(meta),
                        playbook_init_event_id,
                        req.parent_execution_id,
                        datetime.now(timezone.utc)
                    ))
                    
                    # Store for NATS publishing after commit
                    command_events.append((event_id, command_id, command))
                    logger.info(f"[EVENT] Emitted command.issued event_id={event_id} command_id={command_id} step={command.step} exec={execution_id}")
                    
                await conn.commit()
                logger.info(f"[EVENT] Committed {len(command_events)} command.issued events for exec={execution_id}")
        
        # Publish NATS notifications immediately after commit
        # Workers will claim commands by emitting command.claimed events
        for event_id, command_id, command in command_events:
            logger.info(f"[NATS] Publishing notification for event_id={event_id} command_id={command_id} step={command.step}")
            await nats_pub.publish_command(
                execution_id=int(execution_id),
                event_id=event_id,
                command_id=command_id,
                step=command.step,
                server_url=server_url
            )
        
        return StartExecutionResponse(
            execution_id=execution_id,
            status="started",
            commands_generated=len(commands)
        )
    
    except Exception as e:
        logger.error(f"Failed to start execution: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/commands/{event_id}")
async def get_command_details(event_id: int):
    """
    Get command details from command.issued event.
    
    Workers call this endpoint to fetch the full command configuration
    after claiming a command via command.claimed event.
    
    Returns:
        Command details including tool config, args, and render context
    """
    try:
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT 
                        execution_id,
                        node_name as step,
                        node_type as tool_kind,
                        context,
                        meta
                    FROM noetl.event
                    WHERE event_id = %s AND event_type = 'command.issued'
                """, (event_id,))
                
                row = await cur.fetchone()
                if not row:
                    logger.error(f"Command.issued event not found for event_id={event_id}")
                    raise HTTPException(
                        status_code=404,
                        detail=f"Command.issued event not found for event_id={event_id}"
                    )
                
                # Row is a DictRow: {execution_id, step, tool_kind, context, meta}
                logger.info(f"Fetched command for event_id={event_id}: step={row['step']}, tool={row['tool_kind']}")
                
                # Return command structure expected by worker
                return {
                    "execution_id": row['execution_id'],
                    "node_id": row['step'],
                    "node_name": row['step'],
                    "action": row['tool_kind'],
                    "context": row['context'],
                    "meta": row['meta']
                }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch command details: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/events", response_model=EventResponse)
async def handle_event(req: EventRequest) -> EventResponse:
    """
    Handle event from worker.
    
    Workers send events here after completing actions.
    Engine evaluates case/when/then rules and generates next commands.
    
    Pure event-driven - no queue table operations needed.
    """
    try:
        engine = get_engine()
        
        # Build event metadata
        event_meta = req.meta or {}
        attempt = event_meta.get("attempt", 1)
        
        # Create Event
        event = Event(
            execution_id=req.execution_id,
            step=req.step,
            name=req.name,
            payload=req.payload,
            meta=event_meta,
            timestamp=datetime.now(timezone.utc),
            worker_id=req.worker_id,
            attempt=attempt
        )
        
        # Process event through engine to generate next commands
        commands = await engine.handle_event(event)
        
        # Get NATS publisher
        nats_pub = await get_nats_publisher()
        
        # Server URL for worker API calls
        server_url = os.getenv("SERVER_API_URL", "http://noetl.noetl.svc.cluster.local:8082")
        
        # Emit command.issued events instead of queue table insertion
        command_events = []  # Store (event_id, command_id, command) for NATS publishing after commit
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
                    
                    # Generate unique command ID
                    command_id = f"{command.execution_id}:{command.step}:{await get_snowflake_id()}"
                    event_id = await get_snowflake_id()
                    
                    # Insert command.issued event
                    await cur.execute("""
                        INSERT INTO noetl.event (
                            event_id, execution_id, catalog_id, event_type,
                            node_id, node_name, node_type, status,
                            context, meta, parent_event_id, parent_execution_id,
                            created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        event_id,
                        int(command.execution_id),
                        catalog_id,
                        "command.issued",
                        command.step,
                        command.step,
                        command.tool.kind,
                        "PENDING",
                        Json({
                            "tool_config": command.tool.config,
                            "args": command.args or {},
                            "render_context": command.render_context
                        }),
                        Json({
                            "command_id": command_id,
                            "step": command.step,
                            "tool_kind": command.tool.kind,
                            "priority": command.priority,
                            "max_attempts": command.max_attempts or 3,
                            "attempt": 1,
                            "catalog_id": catalog_id,
                            "triggered_by": "event_handler",
                            "triggering_event_id": triggering_event_id,
                            "metadata": command.metadata,
                            "event_type": event.name,
                            "event_step": event.step
                        }),
                        triggering_event_id,
                        parent_execution_id,
                        datetime.now(timezone.utc)
                    ))
                    
                    # Store for NATS publishing after commit
                    command_events.append((event_id, command_id, command))
                    logger.info(f"[EVENT] Emitted command.issued event_id={event_id} command_id={command_id} step={command.step} exec={command.execution_id}")
                    
                await conn.commit()
                logger.info(f"[EVENT] Committed {len(command_events)} command.issued events for exec={event.execution_id}")
        
        # Publish NATS notifications immediately after commit
        # Workers will claim commands by emitting command.claimed events
        for event_id, command_id, command in command_events:
            logger.info(f"[NATS] Publishing notification for event_id={event_id} command_id={command_id} step={command.step}")
            await nats_pub.publish_command(
                execution_id=int(command.execution_id),
                event_id=event_id,
                command_id=command_id,
                step=command.step,
                server_url=server_url
            )
        
        # Trigger orchestrator for transition processing if this is a completion event
        # This allows step_completed events to be emitted and workflow to progress/complete
        # Exception: Don't trigger for "end" step to avoid race conditions with workflow completion
        if event.name == "command.completed" and req.step.lower() != "end":
            from .run import evaluate_execution
            try:
                logger.info(f"[ORCHESTRATOR] Triggering orchestrator for command.completed event in execution {event.execution_id}")
                await evaluate_execution(
                    execution_id=str(event.execution_id),
                    trigger_event_type="command.completed",
                    trigger_event_id=None  # We don't have the persisted event_id yet in v2 flow
                )
            except Exception as e:
                logger.exception(f"Error triggering orchestrator for execution {event.execution_id}: {e}")
        
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
