from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from noetl.ctx.app_context import get_app_context, AppContext
from noetl.api.schemas.event import EmitEventRequest
from noetl.api.services.event import EventService
from noetl.api.services.dispatcher import dispatch_event
from noetl.config.settings import AppConfig

app_config = AppConfig()
templates = Jinja2Templates(directory=app_config.get_template_folder("event"))
router = APIRouter(prefix="/events")

def get_event_service(context: AppContext = Depends(get_app_context)) -> EventService:
    return EventService(context)


@router.get("/", response_class=HTMLResponse)
async def events_page(
    request: Request,
    search: Optional[str] = None,
    event_service: EventService = Depends(get_event_service)
):
    events = await event_service.get_events(search=search)
    return templates.TemplateResponse("event_page.html", {"request": request, "events": events, "search": search})


@router.get("/{id}")
async def get_event_by_id(
    id: int,
    event_service: EventService = Depends(get_event_service),
):
    event = await event_service.get_event(id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event

@router.post("/emit")
async def emit_event(
    request: Request,
    background_tasks: BackgroundTasks,
    event_service: EventService = Depends(get_event_service),
):
    event_data = await request.json()
    new_event = await event_service.emit(event_data)
    background_tasks.add_task(dispatch_event, new_event, event_service)
    return {"event_id": new_event.event_id, "status": "Event logged."}