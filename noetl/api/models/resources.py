from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy.dialects.postgresql import JSON
from typing import Optional, List
from datetime import datetime
from sqlalchemy import Column, UniqueConstraint, ForeignKeyConstraint
from noetl.util import setup_logger

logger = setup_logger(__name__, include_location=True)

class ResourceType(SQLModel, table=True):
    __tablename__ = "resource_type"
    name: str = Field(primary_key=True)
    catalog_entries: List["Catalog"] = Relationship(back_populates="resource_type_entry")


class Catalog(SQLModel, table=True):
    __tablename__ = "catalog"
    __table_args__ = (
        UniqueConstraint("resource_path", "resource_version", name="uq_catalog_path_version"),
    )
    resource_path: str = Field(primary_key=True)
    resource_version: str = Field(primary_key=True)
    resource_type: str = Field(foreign_key="resource_type.name", nullable=False)
    source: str = Field(default="inline")
    resource_location: Optional[str] = Field(default=None)
    content: Optional[str] = Field(default=None)
    payload: dict = Field(sa_column=Column(JSON, nullable=False))
    meta: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    template: Optional[str] = Field(default=None)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    resource_type_entry: Optional["ResourceType"] = Relationship(back_populates="catalog_entries")
    events: Optional["Event"] = Relationship(
        back_populates="catalog_entry",
        sa_relationship_kwargs={
            "primaryjoin": "and_(Catalog.resource_path == Event.resource_path, "
                           "Catalog.resource_version == Event.resource_version)"
        },
    )


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


def create_noetl_tables(engine):
    SQLModel.metadata.create_all(engine)

