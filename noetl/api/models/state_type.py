from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, Dict
from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy import Column
from noetl.util.dro import generate_id

class StateType(SQLModel, table=True):
    __tablename__ = "state_type"

    name: str = Field(primary_key=True)
    template: str = Field(nullable=False)
    description: Optional[str] = Field(default=None)
    transitions: Optional[List[str]] = Field(
        default_factory=list, sa_column=Column(JSON)
    )

    events: List["Event"] = Relationship(back_populates="state_type_entry")
