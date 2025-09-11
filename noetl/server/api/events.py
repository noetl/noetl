from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from noetl.server.services import (
    EventService,
    get_event_service_dependency,
)

router = APIRouter()


@router.get("/events/by-execution/{execution_id}", response_class=JSONResponse)
async def get_events_by_execution(request: Request, execution_id: str, event_service: EventService = Depends(get_event_service_dependency)):
    result = await event_service.get_events_by_execution_id(execution_id)
    return JSONResponse(content=result or {"error": "Not found"})


@router.get("/events/by-id/{event_id}", response_class=JSONResponse)
async def get_event_by_id(request: Request, event_id: str, event_service: EventService = Depends(get_event_service_dependency)):
    result = await event_service.get_event_by_id(event_id)
    return JSONResponse(content=result or {"error": "Not found"})


@router.get("/events/{event_id}", response_class=JSONResponse)
async def get_event(request: Request, event_id: str, event_service: EventService = Depends(get_event_service_dependency)):
    result = await event_service.get_event(event_id)
    return JSONResponse(content=result or {"error": "Not found"})


@router.get("/events/query", response_class=JSONResponse)
async def get_event_by_query(request: Request, event_id: Optional[str] = None, event_service: EventService = Depends(get_event_service_dependency)):
    if not event_id:
        return JSONResponse(content={"error": "event_id is required"}, status_code=400)
    result = await event_service.get_event(event_id)
    return JSONResponse(content=result or {"error": "Not found"})


@router.get("/events/poll", response_class=JSONResponse)
async def poll_events(request: Request, event_type: Optional[str] = None, status: Optional[str] = None, limit: int = 10, event_service: EventService = Depends(get_event_service_dependency)):
    result = await event_service.poll_events(event_type=event_type, status=status, limit=limit)
    return JSONResponse(content={"items": result})


@router.get("/events", response_class=JSONResponse)
async def poll_events_root(request: Request, event_type: Optional[str] = None, status: Optional[str] = None, limit: int = 10, event_service: EventService = Depends(get_event_service_dependency)):
    result = await event_service.poll_events(event_type=event_type, status=status, limit=limit)
    return JSONResponse(content={"items": result})
