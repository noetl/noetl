from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, Dict
from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy import Column
from noetl.util.dro import generate_id

class EventState(SQLModel, table=True):
    __tablename__ = "event_state"

    name: str = Field(primary_key=True)
    template: str = Field(nullable=False)
    description: Optional[str] = Field(default=None)
    transitions: Optional[List[str]] = Field(
        default_factory=list, sa_column=Column(JSON)
    )

    events: List["Event"] = Relationship(back_populates="event_state_entry")


class Event(SQLModel, table=True):
    __tablename__ = "event"

    event_id: str = Field(default_factory=generate_id, primary_key=True, max_length=36)
    parent_id: Optional[str] = Field(default=None, index=True, max_length=36)
    registry_id: Optional[str] = Field(foreign_key="registry.registry_id", default=None, index=True)
    execution_id: Optional[str] = Field(foreign_key="execution.execution_id", default=None, index=True)
    context_id: Optional[str] = Field(foreign_key="context.context_id", default=None, index=True)
    event_type: str = Field(nullable=False)
    status: str = Field(default="READY", nullable=False)
    event_state: str = Field(foreign_key="event_state.name", nullable=False)
    event_message: Optional[str] = Field(default=None)
    content: Optional[str] = Field(default=None)
    payload: Optional[dict] = Field(default_factory=dict, sa_column=Column(JSON))
    meta: Optional[dict] = Field(default_factory=dict, sa_column=Column(JSON))
    labels: Optional[List[str]] = Field(default_factory=list, sa_column=Column(JSON))
    tags: Optional[Dict[str, str]] = Field(default_factory=dict, sa_column=Column(JSON))
    timestamp: datetime = Field(default=datetime.now(timezone.utc))

    registry_entry: Optional["Registry"] = Relationship(back_populates="events")
    execution_entry: Optional["Execution"] = Relationship(back_populates="events")
    context_entry: Optional["Context"] = Relationship(back_populates="events")
    event_state_entry: Optional["EventState"] = Relationship(back_populates="events")

    def validate_parent_sources(self):
        sources = [self.registry_id, self.execution_id, self.context_id]
        if sum(source is not None for source in sources) != 1:
            raise ValueError("Event must relate to exactly one of Registry, Execution, or Context.")