from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, Dict
from datetime import datetime, timezone
from sqlalchemy import Column
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON


class Registry(SQLModel, table=True):
    __tablename__ = "registry"

    registry_id: str = Field(primary_key=True, max_length=36)
    resource_path: str = Field(nullable=False)
    resource_version: str = Field(nullable=False)
    namespace: Optional[dict] = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = Field(default="PENDING", nullable=False)
    payload: dict = Field(sa_column=Column(JSON, nullable=False))
    meta: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    labels: Optional[List[str]] = Field(default_factory=list, sa_column=Column(JSON))
    tags: Optional[Dict[str, str]] = Field(default_factory=dict, sa_column=Column(JSON))
    timestamp: datetime = Field(default=datetime.now(timezone.utc))

    __table_args__ = (
        sa.ForeignKeyConstraint(
            ['resource_path', 'resource_version'],
            ['catalog.resource_path', 'catalog.resource_version'],
            name="fk_registry_catalog"
        ),
    )

    # Relationships
    catalog_entry: Optional["Catalog"] = Relationship(
        back_populates="registry_entries",
        sa_relationship_kwargs={
            "primaryjoin": "and_(Registry.resource_path == Catalog.resource_path, "
                           "Registry.resource_version == Catalog.resource_version)"
        }
    )
    executions: List["Execution"] = Relationship(back_populates="registry_entry")
    events: List["Event"] = Relationship(back_populates="registry_entry")
