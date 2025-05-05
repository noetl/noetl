from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, Dict
from datetime import datetime, timezone
from sqlalchemy import Column, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON


class ResourceType(SQLModel, table=True):
    __tablename__ = "resource_type"

    name: str = Field(primary_key=True)

    catalog_entries: List["Catalog"] = Relationship(back_populates="resource_type_entry")
