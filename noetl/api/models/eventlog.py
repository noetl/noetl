from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import datetime
from sqlalchemy import Column, ForeignKeyConstraint
from sqlalchemy.dialects.postgresql import JSON
from noetl.util.dro import generate_id



class EventState(SQLModel, table=True):
    __tablename__ = "event_state"
    name: str = Field(primary_key=True)
    template: str = Field(nullable=False)
    description: Optional[str] = Field(default=None)
    transitions: Optional[List[str]] = Field(default_factory=list, sa_column=Column(JSON))
    events: List["EventLog"] = Relationship(back_populates="event_state_entry")


class EventLog(SQLModel, table=True):
    __tablename__ = "event_log"
    __table_args__ = (
        ForeignKeyConstraint(
            ["resource_path", "resource_version"],
            ["catalog.resource_path", "catalog.resource_version"],
            name="fk_event_catalog"
        ),
    )
    event_id: str = Field(default_factory=generate_id, primary_key=True, max_length=36)
    parent_id: Optional[str] = Field(default=None, index=True, max_length=36)
    execution_id: Optional[str] = Field(default=None, index=True, max_length=36)
    event_type: Optional[str] = Field(default=None)
    status: str = Field(default="READY", nullable=False)
    resource_path: str = Field(nullable=False)
    resource_version: str = Field(nullable=False)
    event_state: str = Field(foreign_key="event_state.name", nullable=False)
    event_message: Optional[str] = Field(default=None)
    content: Optional[str] = Field(default=None)
    payload: Optional[dict] = Field(default_factory=dict, sa_column=Column(JSON))
    context: Optional[dict] = Field(default_factory=dict, sa_column=Column(JSON))
    meta: Optional[dict] = Field(default_factory=dict, sa_column=Column(JSON))
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    catalog_entry: Optional["Catalog"] = Relationship(
        back_populates="events",
        sa_relationship_kwargs={
            "primaryjoin": "and_(EventLog.resource_path == Catalog.resource_path, "
                           "EventLog.resource_version == Catalog.resource_version)"
        },
    )
    event_state_entry: Optional["EventState"] = Relationship(back_populates="events")
