from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, Dict
from datetime import datetime, timezone
from sqlalchemy import Column
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON
from noetl.util.dro import generate_id

class Workload(SQLModel, table=True):
    __tablename__ = "workload"

    workload_id: str = Field(default_factory=generate_id, primary_key=True, max_length=36)
    event_id: Optional[str] = Field(foreign_key="event.event_id", default=None, index=True, max_length=36)
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

    event_entry: Optional["Event"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "[Workload.event_id]",
            "primaryjoin": "Workload.event_id == Event.event_id"
        }
    )

    events: List["Event"] = Relationship(
        back_populates="workload_entry",
        sa_relationship_kwargs={
            "foreign_keys": "[Event.workload_id]",
            "primaryjoin": "Workload.workload_id == Event.workload_id"
        }
    )

    catalog_entry: Optional["Catalog"] = Relationship(
        back_populates="workload_entry",
        sa_relationship_kwargs={
            "primaryjoin": "and_(Workload.resource_path == Catalog.resource_path, "
                           "Workload.resource_version == Catalog.resource_version)"
        }
    )

    runtime_entry: List["Runtime"] = Relationship(back_populates="workload_entry")
