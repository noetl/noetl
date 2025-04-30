from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import datetime
from sqlalchemy import Column, ForeignKeyConstraint
from sqlalchemy.dialects.postgresql import JSON

class EventType(SQLModel, table=True):
    __tablename__ = "event_type"
    name: str = Field(primary_key=True)
    template: str = Field(nullable=False)
    events: List["Event"] = Relationship(back_populates="event_type_entry")


class Event(SQLModel, table=True):
    __tablename__ = "event"
    __table_args__ = (
        ForeignKeyConstraint(
            ["resource_path", "resource_version"],
            ["catalog.resource_path", "catalog.resource_version"],
            name="fk_event_catalog"
        ),
    )

    event_id: str = Field(primary_key=True)
    resource_path: str = Field(nullable=False)
    resource_version: str = Field(nullable=False)
    event_type: str = Field(foreign_key="event_type.name", nullable=False)
    event_message: Optional[str] = Field(default=None)
    content: Optional[str] = Field(default=None)
    payload: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    context: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    meta: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    catalog_entry: Optional["Catalog"] = Relationship(
        back_populates="events",
        sa_relationship_kwargs={
            "primaryjoin": "and_(Event.resource_path == Catalog.resource_path, "
                           "Event.resource_version == Catalog.resource_version)"
        },
    )
    event_type_entry: Optional["EventType"] = Relationship(back_populates="events")
