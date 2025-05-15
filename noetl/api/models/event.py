from sqlmodel import SQLModel, Field, Column, Relationship, JSON
from typing import Optional, List, Dict
from datetime import datetime, timezone
# from sqlalchemy.dialects.postgresql import JSON
# from sqlalchemy import Column
from noetl.util.dro import generate_id


class Event(SQLModel, table=True):
    __tablename__ = "event"

    event_id: str = Field(default_factory=generate_id, primary_key=True, max_length=36)
    parent_id: Optional[str] = Field(default=None, index=True, max_length=36)
    workload_id: Optional[str] = Field(foreign_key="workload.workload_id", default=None, index=True, max_length=36)
    runtime_id: Optional[str] = Field(foreign_key="runtime.runtime_id", default=None, index=True, max_length=36)
    context_id: Optional[str] = Field(foreign_key="context.context_id", default=None, index=True, max_length=36)
    unit_id: Optional[str] = Field(foreign_key="dict_unit.name", default=None, index=True)
    component_id: Optional[str] = Field(foreign_key="dict_component.component_name", default=None, index=True)
    event_type: str = Field(nullable=False)
    # scope: Optional[str] = Field(default=None, description="Scope of the event: workflow, task, action, loop")
    status: str = Field(default="READY", nullable=False)
    state: str = Field(foreign_key="dict_state.name", nullable=False)
    event_message: Optional[str] = Field(default=None)
    content: Optional[str] = Field(default=None)
    payload: Optional[dict] = Field(default_factory=dict, sa_column=Column(JSON))
    meta: Optional[dict] = Field(default_factory=dict, sa_column=Column(JSON))
    labels: Optional[List[str]] = Field(default_factory=list, sa_column=Column(JSON))
    tags: Optional[Dict[str, str]] = Field(default_factory=dict, sa_column=Column(JSON))
    timestamp: datetime = Field(default=datetime.now(timezone.utc))

    workload_entry: Optional["Workload"] = Relationship(
        back_populates="event_entry",
        sa_relationship_kwargs={
            "foreign_keys": "[Event.workload_id]",
            "primaryjoin": "Event.workload_id == Workload.workload_id"
        }
    )

    runtime_entry: Optional["Runtime"] = Relationship(back_populates="event_entry")
    context_entry: Optional["Context"] = Relationship(back_populates="event_entry")
    dict_state_entry: Optional["DictState"] = Relationship(back_populates="event_entry")
    dict_unit_entry: Optional["DictUnit"] = Relationship(back_populates="event_entry")
    dict_component_entry: Optional["DictComponent"] = Relationship(back_populates="event_entry")

    def validate_parent_sources(self):
        sources = [self.wokrload_id, self.runtime_id, self.context_id]
        if sum(source is not None for source in sources) != 1:
            raise ValueError("Event must relate to exactly one of Workload, Runtime, or Context.")