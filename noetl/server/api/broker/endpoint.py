"""
NoETL Broker API Endpoints - Event handling and workflow orchestration.

Event sourcing architecture:
1. Worker executes task and reports result via POST /events
2. Event is persisted to event table
3. Orchestrator is triggered to analyze events
4. Orchestrator publishes next tasks to queue
5. Workers pick up next tasks and repeat
"""

from fastapi import APIRouter, HTTPException, Path, Query as FastAPIQuery
from typing import Optional
from noetl.core.logger import setup_logger
from .schema import (
    EventEmitRequest,
    EventEmitResponse,
    EventQuery,
    EventResponse,
    EventListResponse,
    EventType,
    EventStatus
)
from .service import EventService
from ..run import evaluate_execution


logger = setup_logger(__name__, include_location=True)
router = APIRouter()


@router.post("/events", response_model=EventEmitResponse)
async def emit_event_legacy(payload: EventEmitRequest):
    """Worker compatibility endpoint - POST /api/events."""
    return await emit_event(payload)


@router.post("/event/emit", response_model=EventEmitResponse)
async def emit_event(payload: EventEmitRequest):
    """Emit event and trigger orchestration."""
    try:
        logger.debug(f"EMIT EVENT: execution_id={payload.execution_id}, type={payload.event_type}")
        result = await EventService.emit_event(payload)
        await evaluate_execution(
            execution_id=payload.execution_id,
            trigger_event_type=payload.event_type,
            trigger_event_id=result.event_id
        )
        return result
    except ValueError as e:
        logger.error(f"Validation error emitting event: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error emitting event: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/event/{event_id}", response_model=EventResponse)
async def get_event(event_id: str = Path(..., description="Event ID to retrieve")):
    """Retrieve a specific event by ID."""
    try:
        return await EventService.get_event(int(event_id))
    except ValueError as e:
        logger.error(f"Event not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error retrieving event: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/event/", response_model=EventListResponse)
async def list_events(
    execution_id: Optional[str] = FastAPIQuery(None, description="Filter by execution ID"),
    event_type: Optional[EventType] = FastAPIQuery(None, description="Filter by event type"),
    status: Optional[EventStatus] = FastAPIQuery(None, description="Filter by status"),
    limit: int = FastAPIQuery(100, description="Maximum number of events to return"),
    offset: int = FastAPIQuery(0, description="Number of events to skip")
):
    """List events with optional filters."""
    try:
        query = EventQuery(
            execution_id=execution_id,
            event_type=event_type,
            status=status,
            limit=limit,
            offset=offset
        )
        return await EventService.list_events(query)
    except Exception as e:
        logger.error(f"Error listing events: {e}")
        raise HTTPException(status_code=500, detail=str(e))
