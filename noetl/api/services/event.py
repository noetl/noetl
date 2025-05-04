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

    async def get_events(self, search: Optional[str] = None) -> List[Event]:
        async with self.context.postgres.get_session() as session:
            query = select(Event)
            if search:
                query = query.where(Event.event_message.ilike(f"%{search}%"))
            query = query.order_by(Event.timestamp.desc())
            result = await session.exec(query)
            events = result.all()
            logger.info(f"Retrieved {len(events)} events", extra={"search": search})
            return events

    async def log_event(self, event_data: dict) -> Event:
        async with self.context.postgres.get_session() as session:
            logger.info(f" log_event Logging event: {event_data}", extra=event_data)
            new_event = Event(**event_data)
            session.add(new_event)
            await session.commit()
            await session.refresh(new_event)
            return new_event

    async def event_state_exists(self, event_state: str) -> None:
        async with self.context.postgres.get_session() as session:
            existing = await session.get(EventState, event_state)
            if not existing:
                new_event_state = EventState(name=event_state, template="Default event template")
                session.add(new_event_state)
                await session.commit()
                logger.info(f"Event type '{event_state}' created.")
            else:
                logger.info(f"Event type '{event_state}' already exists.")

    async def get_event_state(self, event_state: str) -> Optional[EventState]:
        async with self.context.postgres.get_session() as session:
            e_state = await session.get(EventState, event_state)
            if e_state:
                logger.info(f"Found event type '{event_state}'.")
            else:
                logger.warning(f"Event type '{event_state}' not found.")
            return e_state

    async def get_event_states(self) -> List[EventState]:
        async with self.context.postgres.get_session() as session:
            stmt = select(EventState)
            result = await session.exec(stmt)
            event_states = result.all()
            logger.info(f"Retrieved {len(event_states)} event types.")
            return event_states
