from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, Dict
from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy import Column
from noetl.api.models.dict_state import DictState


class StateTransition(SQLModel, table=True):
    __tablename__ = "state_transition"

    from_state: str = Field(
        foreign_key="dict_state.name",
        primary_key=True,
        max_length=50
    )
    to_state: str = Field(
        foreign_key="dict_state.name",
        primary_key=True,
        max_length=50
    )
    description: Optional[str] = Field(default=None)
    active: bool = Field(default=True)

    from_state_entry: Optional[DictState] = Relationship(
        back_populates="outgoing_transitions",
        sa_relationship_kwargs={
            "foreign_keys": "[StateTransition.from_state]",
            "primaryjoin": "StateTransition.from_state == DictState.name"
        }
    )
    to_state_entry: Optional[DictState] = Relationship(
        back_populates="incoming_transitions",
        sa_relationship_kwargs={
            "foreign_keys": "[StateTransition.to_state]",
            "primaryjoin": "StateTransition.to_state == DictState.name"
        }
    )
