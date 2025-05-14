from sqlmodel import SQLModel, Field
from typing import Optional

class FlowTransition(SQLModel, table=True):
    __tablename__ = "flow_transition"

    component_name: str = Field(foreign_key="dict_component.component_name", primary_key=True)
    unit_name: str = Field(primary_key=True)
    operand_name: str = Field(foreign_key="dict_operand.operand_name", primary_key=True)
    current_state: str = Field(primary_key=True)
    event_type: str = Field(primary_key=True)
    route_path: str
    http_method: str = "POST"
    next_state: Optional[str] = None
    description: Optional[str] = None