from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, Dict
from datetime import datetime, timezone
from sqlalchemy import Column, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON
from noetl.util.dro import generate_id

class Catalog(SQLModel, table=True):
    __tablename__ = "catalog"
    __table_args__ = (
        UniqueConstraint("resource_path", "resource_version", name="uq_catalog_path_version"),
    )

    resource_path: str = Field(primary_key=True, max_length=255)
    resource_version: str = Field(primary_key=True, max_length=11, index=True)
    resource_type: str = Field(foreign_key="dict_resource.name", nullable=False)
    resource_location: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    content: Optional[str] = Field(default=None)
    payload: dict = Field(sa_column=Column(JSON, nullable=False))
    meta: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    labels: Optional[List[str]] = Field(default_factory=list, sa_column=Column(JSON))
    tags: Optional[Dict[str, str]] = Field(default_factory=dict, sa_column=Column(JSON))
    template: Optional[str] = Field(default=None)
    timestamp: datetime = Field(default=datetime.now(timezone.utc))

    dict_resource_entry: Optional["DictResource"] = Relationship(back_populates="catalog_entries")
    workload_entry: List["Workload"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "and_(Catalog.resource_path == Workload.resource_path, "
                           "Catalog.resource_version == Workload.resource_version)"
        },
        back_populates="catalog_entry",
    )
