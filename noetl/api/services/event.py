from typing import Optional, List
from sqlmodel import select
from noetl.ctx.app_context import AppContext
from noetl.api.models.event import Event
from noetl.api.models.state_type import StateType
from noetl.api.schemas.event import EventSchema
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

    async def state_exists(self, state: str) -> bool:
        async with self.context.postgres.get_session() as session:
            existing = await session.get(StateType, state)
            if existing:
                return True
            return False

    async def get_state(self, state: str) -> Optional[StateType]:
        async with self.context.postgres.get_session() as session:
            e_state = await session.get(StateType, state)
            if e_state:
                logger.debug(f"Found state '{state}'.")
            else:
                logger.warning(f"State '{state}' not found.")
            return e_state

    async def get_states(self) -> List[StateType]:
        async with self.context.postgres.get_session() as session:
            stmt = select(StateType)
            result = await session.exec(stmt)
            states = result.all()
            logger.debug(f"Retrieved {len(states)} event states.")
            return states

    async def emit(self, event_data: dict) -> EventSchema:
        async with self.context.postgres.get_session() as session:
            logger.debug(f"Emit event: {event_data}", extra=event_data)
            state_name = event_data.get("state")
            if state_name:
                state_exists = await self.state_exists(state_name)
                if not state_exists:
                    raise ValueError(f"Event state '{state_name}' does not exist.")
            state = await self.get_state(state_name)
            if not state:
                raise ValueError(f"State '{state_name}' does not exist.")
            event_message = create_event_message(event_data.get("meta"), state.template)
            new_event = Event(**event_data | {"event_message": event_message})
            session.add(new_event)
            await session.commit()
            await session.refresh(new_event)
            event_schema = EventSchema.model_validate(new_event)
            return event_schema


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
