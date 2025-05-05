from typing import Optional, List
from sqlmodel import select
from noetl.ctx.app_context import AppContext
from noetl.api.models.event import Event, EventState
from noetl.util import setup_logger

logger = setup_logger(__name__, include_location=True)

def get_event_service(context: AppContext):
    return EventService(context)

class EventService:
    def __init__(self, context: AppContext) -> None:
        self.context = context

    async def get_event(self, event_id: Optional[str] = None) -> Optional[Event]:
        async with self.context.postgres.get_session() as session:
            if event_id:
                event = await session.get(Event, event_id)
                if event:
                    logger.debug(f"Found event with ID '{event_id}'.")
                else:
                    logger.warning(f"Event with ID '{event_id}' not found.")
                return event
            else:
                logger.warning("No event ID provided for get_event.")
                return None

    async def get_events(self, search: Optional[dict] = None) -> List[Event]:
        async with self.context.postgres.get_session() as session:
            query = select(Event)
            if search:
                filters = []
                fields = {
                    "event_id": Event.event_id,
                    "execution_id": Event.execution_id,
                    "context_id": Event.context_id,
                    "registry_id": Event.registry_id,
                    "event_message": Event.event_message
                }

                for key, value in search.items():
                    if key in fields and value:
                        if key == "event_message":
                            filters.append(fields[key].ilike(f"%{value}%"))
                        else:
                            filters.append(fields[key] == value)
                if filters:
                    query = query.where(*filters)
            query = query.order_by(Event.timestamp.desc())
            result = await session.exec(query)
            events = result.all()
            logger.debug(f"Retrieved {len(events)} events for search: {search}")
            return events

    async def event_state_exists(self, event_state: str) -> bool:
        async with self.context.postgres.get_session() as session:
            existing = await session.get(EventState, event_state)
            if existing:
                return True
            return False

    async def get_event_state(self, event_state: str) -> Optional[EventState]:
        async with self.context.postgres.get_session() as session:
            e_state = await session.get(EventState, event_state)
            if e_state:
                logger.debug(f"Found event state '{event_state}'.")
            else:
                logger.warning(f"Event state '{event_state}' not found.")
            return e_state

    async def get_event_states(self) -> List[EventState]:
        async with self.context.postgres.get_session() as session:
            stmt = select(EventState)
            result = await session.exec(stmt)
            event_states = result.all()
            logger.debug(f"Retrieved {len(event_states)} event states.")
            return event_states

    async def emit(self, event_data: dict) -> Event:
        async with self.context.postgres.get_session() as session:
            logger.debug(f"Emit event: {event_data}", extra=event_data)
            event_state_name = event_data.get("event_state")
            if event_state_name:
                event_state_exists = await self.event_state_exists(event_state_name)
                if not event_state_exists:
                    raise ValueError(f"Event state '{event_state_name}' does not exist.")
            event_state = await self.get_event_state(event_state_name)
            if not event_state:
                raise ValueError(f"Event state '{event_state_name}' does not exist.")
            event_message = create_event_message(event_data.get("meta"), event_state.template)
            new_event = Event(**event_data | {"event_message": event_message})
            session.add(new_event)
            await session.commit()
            await session.refresh(new_event)
            return new_event


def create_event_message(meta: dict[str, str], event_state_template) -> str:
    from jinja2 import Template
    try:
        keys = ["resource_path", "resource_version", "registry_id", "execution_id", "context_id"]
        tokens = []
        for key in keys:
            if key in meta:
                tokens.append(f"{key.replace('_', ' ').capitalize()}: {meta.get(key)}")
        if not tokens:
            raise ValueError(f"Missing keys from meta: {keys}")
        namespace = ", ".join(tokens)
        template = Template(event_state_template)
        event_message = template.render(namespace=namespace)
        return event_message
    except KeyError as e:
        raise ValueError(
            f"Placeholder '{e.args[0]}' is missing for template '{event_state_template}'.")
    except Exception as e:
        raise ValueError(f"Failed to render '{event_state_template}' template: {str(e)}")
