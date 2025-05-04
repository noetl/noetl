from noetl.api.models.event import Event
from noetl.api.services.event import EventService
from noetl.util import setup_logger
logger = setup_logger(__name__, include_location=True)

async def process_event(event: Event, event_service: EventService):
    logger.info(f"Processing event: {event.event_type}", extra=event)
    if event.event_type:
        await event_service.event_state_exists(event.event_type)

def dispatch_event(event: Event, event_service: EventService):
    process_event(event, event_service)
