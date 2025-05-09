from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, Dict
from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy import Column

class DictState(SQLModel, table=True):
    __tablename__ = "dict_state"

    name: str = Field(primary_key=True, max_length=50)
    template: str = Field(nullable=False)
    description: Optional[str] = Field(default=None)

    outgoing_transitions: List["StateTransition"] = Relationship(
        back_populates="from_state_entry",
        sa_relationship_kwargs={
            "foreign_keys": "[StateTransition.from_state]"
        }
    )
    incoming_transitions: List["StateTransition"] = Relationship(
        back_populates="to_state_entry",
        sa_relationship_kwargs={
            "foreign_keys": "[StateTransition.to_state]"
        }
    )

    event_entry: List["Event"] = Relationship(
        back_populates="dict_state_entry"
    )