from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from noetl.api.models.dict_unit import DictUnit

class UnitTransition(SQLModel, table=True):
    __tablename__ = "unit_transition"

    from_unit: str = Field(foreign_key="dict_unit.name", primary_key=True)
    to_unit: str = Field(foreign_key="dict_unit.name", primary_key=True)
    method: str = Field(primary_key=True)
    active: bool = Field(default=True)

    from_unit_entry: Optional[DictUnit] = Relationship(
        back_populates="outgoing_transitions",
        sa_relationship_kwargs={
            "foreign_keys": "[UnitTransition.from_unit]"
        }
    )
    to_unit_entry: Optional[DictUnit] = Relationship(
        back_populates="incoming_transitions",
        sa_relationship_kwargs={
            "foreign_keys": "[UnitTransition.to_unit]"
        }
    )
