from sqlmodel import select
from datetime import datetime, UTC
import json
from noetl.api.models.event import Event, EventType
from noetl.util import setup_logger

logger = setup_logger(__name__, include_location=True)

def get_event_service():
    return EventService()

class EventService:
    @staticmethod
    async def create_event_type(session, event_type: str):
        exists = await session.get(EventType, event_type)
        if not exists:
            new_event_type = EventType(name=event_type, template="Default event template")
            session.add(new_event_type)
            await session.commit()
            logger.info(f"Event type '{event_type}' created.")
        else:
            logger.info(f"Event type '{event_type}' already exists.")

    @staticmethod
    async def log_event(session, event_data: dict):
        event_id = event_data.get("event_id")
        existing_event_query = select(Event).where(Event.event_id == event_id)
        existing_event_result = await session.exec(existing_event_query)
        existing_event = existing_event_result.first()

        if existing_event:
            logger.info(f"Event '{event_id}' already exists.")
            return {
                "resource_path": existing_event.resource_path,
                "resource_version": existing_event.resource_version,
                "status": "already_exists",
                "message": f"Event '{event_id}' already exists."
            }

        await EventService.create_event_type(session, event_data.get("event_type"))

        new_event = Event(
            event_id=event_id,
            event_type=event_data.get("event_type"),
            resource_path=event_data.get("resource_path"),
            resource_version=event_data.get("resource_version"),
            event_message=event_data.get("event_message"),
            content=event_data.get("content"),
            payload=event_data.get("payload"),
            context=event_data.get("context"),
            meta=event_data.get("meta"),
            timestamp=datetime.now(UTC),
        )
        session.add(new_event)
        await session.commit()

        logger.info(
            f"Event '{event_id}' logged for resource '{event_data.get('resource_path')}' (version: {event_data.get('resource_version')})."
        )
        logger.debug(f"Event details: {json.dumps(event_data, indent=2)}")
        return {
            "resource_path": event_data["resource_path"],
            "resource_version": event_data["resource_version"],
            "status": "success",
            "message": f"Event '{event_id}' logged successfully."
        }
