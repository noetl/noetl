from noetl.api.models.event import Event
from noetl.api.services.event import EventService
from noetl.util import setup_logger
logger = setup_logger(__name__, include_location=True)

async def dispatch_event(event: Event, event_service: EventService):
    await process_event(event, event_service)

async def process_event(event: Event, event_service: EventService):
    logger.info(f"Processing event: {event.event_state}", extra=event.model_dump())

    if event.event_state:
        await event_service.event_state_exists(event.event_state)

