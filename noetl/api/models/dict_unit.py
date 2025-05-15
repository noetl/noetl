from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List

class DictUnit(SQLModel, table=True):
    __tablename__ = "dict_unit"
    name: str = Field(primary_key=True)
    description: Optional[str] = Field(default=None)

    outgoing_transitions: List["UnitTransition"] = Relationship(
        back_populates="from_unit_entry",
        sa_relationship_kwargs={"foreign_keys": "[UnitTransition.from_unit]"}
    )
    incoming_transitions: List["UnitTransition"] = Relationship(
        back_populates="to_unit_entry",
        sa_relationship_kwargs={"foreign_keys": "[UnitTransition.to_unit]"}
    )
    event_entry: List["Event"] = Relationship(back_populates="dict_unit_entry")