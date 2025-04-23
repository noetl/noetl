from sqlmodel import SQLModel, Field, Column, JSON
from typing import Optional


class CatalogEntry(SQLModel, table=True):
    __tablename__ = "catalog"
    resource_path: str = Field(primary_key=True)
    resource_version: str = Field(primary_key=True)
    resource_type: str = Field(index=True)
    source: str = Field(default="inline")
    payload: dict = Field(sa_column=Column(JSON), nullable=False)
    meta: Optional[dict] = Field(sa_column=Column(JSON))
    timestamp: Optional[str] = Field(default=None)
