from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, Dict
from datetime import datetime, timezone
from sqlalchemy import Column, UniqueConstraint
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

    resource_path: str = Field(primary_key=True, max_length=255)
    resource_version: str = Field(primary_key=True, max_length=11, index=True)
    resource_type: str = Field(foreign_key="resource_type.name", nullable=False)
    resource_location: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    content: Optional[str] = Field(default=None)
    payload: dict = Field(sa_column=Column(JSON, nullable=False))
    meta: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    labels: Optional[List[str]] = Field(default_factory=list, sa_column=Column(JSON))
    tags: Optional[Dict[str, str]] = Field(default_factory=dict, sa_column=Column(JSON))
    template: Optional[str] = Field(default=None)
    timestamp: datetime = Field(default=datetime.now(timezone.utc))

    resource_type_entry: Optional["ResourceType"] = Relationship(back_populates="catalog_entries")
    registry_entries: List["Registry"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "and_(Catalog.resource_path == Registry.resource_path, "
                           "Catalog.resource_version == Registry.resource_version)"
        },
        back_populates="catalog_entry",
    )