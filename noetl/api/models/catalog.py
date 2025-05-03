from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import datetime
from sqlalchemy import Column, UniqueConstraint, ForeignKeyConstraint
from sqlalchemy.dialects.postgresql import JSON

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
    resource_version: str = Field(primary_key=True, max_length=11, index=True)
    resource_type: str = Field(foreign_key="resource_type.name", nullable=False)
    source: str = Field(default="inline")
    resource_location: Optional[str] = Field(default=None)
    content: Optional[str] = Field(default=None)
    payload: dict = Field(sa_column=Column(JSON, nullable=False))
    meta: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    template: Optional[str] = Field(default=None)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    resource_type_entry: Optional["ResourceType"] = Relationship(back_populates="catalog_entries")
    events: Optional[List["EventLog"]] = Relationship(
        back_populates="catalog_entry",
        sa_relationship_kwargs={
            "primaryjoin": "and_(Catalog.resource_path == EventLog.resource_path, "
                           "Catalog.resource_version == EventLog.resource_version)"
        },
    )
