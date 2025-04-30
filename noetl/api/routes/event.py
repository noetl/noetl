from noetl.appctx.app_context import get_app_context, AppContext
from fastapi.responses import HTMLResponse
from fastapi import APIRouter, Depends, HTTPException
from noetl.api.schemas.event import EmitEventRequest
from noetl.appctx.app_context import get_app_context
from noetl.api.services.event import EventService, get_event_service

router = APIRouter(prefix="/events")

@router.get("/", response_class=HTMLResponse)
async def events_page():
    return """
    <div>
        <h2>Events Page</h2>
        <p>Track events.</p>
    </div>
    """

@router.post("/event")
async def emit_event(
    event: EmitEventRequest,
    event_service: EventService = Depends(get_event_service),
    context: AppContext = Depends(get_app_context),
):
    async with context.postgres.get_session() as session:
        result = await event_service.log_event(session, event.dict())
        return result
