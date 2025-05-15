from sqlmodel import SQLModel, Field, Relationship, Column, JSON
from typing import Optional

class Dispatch(SQLModel, table=True):
    __tablename__ = "dispatch"

    component_name: str = Field(foreign_key="dict_component.component_name", primary_key=True)
    unit_name: str = Field(primary_key=True)
    operand_name: str = Field(foreign_key="dict_operand.operand_name", primary_key=True)
    state: str = Field(primary_key=True)
    event_type: str = Field(primary_key=True)
    route_path: str
    http_method: str = "POST"
    payload: Optional[dict] = Field(sa_column=Column(JSON, nullable=True))  # Optional payload
    description: Optional[str] = None