from typing import Optional
from fastapi import APIRouter, Depends, Request, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from noetl.connectors.hub import get_connector_hub, ConnectorHub
from noetl.api.schemas.event import EventSchema
from noetl.api.services.event import EventService
from noetl.api.services.dispatcher import dispatch_event
from noetl.config.settings import AppConfig
from fastapi import Query
from noetl.util import setup_logger
logger = setup_logger(__name__, include_location=True)
app_config = AppConfig()
templates = Jinja2Templates(directory=app_config.get_template_folder("event"))
router = APIRouter(prefix="/events")

def get_event_service(context: ConnectorHub = Depends(get_connector_hub)) -> EventService:
    return EventService(context)





@router.get("/", response_class=HTMLResponse)
async def events_page(
        request: Request,
        event_id: Optional[str] = Query(None),
        execution_id: Optional[str] = Query(None),
        context_id: Optional[str] = Query(None),
        registry_id: Optional[str] = Query(None),
        event_message: Optional[str] = Query(None),
        event_service: EventService = Depends(get_event_service)
):
    search_params = {
        "event_id": event_id,
        "execution_id": execution_id,
        "context_id": context_id,
        "registry_id": registry_id,
        "event_message": event_message
    }

    search_params = {k: v for k, v in search_params.items() if v is not None}

    events = await event_service.get_events(search=search_params)

    return templates.TemplateResponse("event_page.html", {
        "request": request,
        "events": events,
        "search": search_params,
    })

@router.post("/emit")
async def emit_event(
    request: Request,
    background_tasks: BackgroundTasks,
    event_service: EventService = Depends(get_event_service),
):
    event_data = await request.json()
    logger.debug(f"Received event data: {event_data}")
    new_event: EventSchema = await event_service.emit(event_data)
    background_tasks.add_task(dispatch_event, new_event, event_service)
    return {"event_id": new_event.event_id, "status": new_event.event_message}