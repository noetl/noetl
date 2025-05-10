from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, Dict
from datetime import datetime, timezone
from sqlalchemy import Column, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON



class DictResource(SQLModel, table=True):
    __tablename__ = "dict_resource"

    name: str = Field(primary_key=True, description="Unique resource identifier")
    description: Optional[str] = Field(default=None, description="Description of the resource")

    catalog_entries: List["Catalog"] = Relationship(
        back_populates="dict_resource_entry",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )