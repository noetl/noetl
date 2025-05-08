from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, Dict
from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy import Column
from noetl.util.dro import generate_id

class DictState(SQLModel, table=True):
    __tablename__ = "dict_state"

    name: str = Field(primary_key=True)
    template: str = Field(nullable=False)
    description: Optional[str] = Field(default=None)
    transitions: Optional[List[str]] = Field(
        default_factory=list, sa_column=Column(JSON)
    )

    event_entry: List["Event"] = Relationship(back_populates="dict_state_entry")
