from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, Dict
from datetime import datetime, timezone
from sqlalchemy import Column, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON


class DictResource(SQLModel, table=True):
    __tablename__ = "dict_resource"

    name: str = Field(primary_key=True)

    catalog_entries: List["Catalog"] = Relationship(back_populates="dict_resource_entry")
