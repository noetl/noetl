from sqlmodel import SQLModel, Field
from typing import Optional

from sqlmodel import SQLModel, Field
from typing import Optional
from sqlalchemy import Column, PrimaryKeyConstraint

class FlowTransition(SQLModel, table=True):
    __tablename__ = "flow_transition"
    __table_args__ = (
        PrimaryKeyConstraint("event_type", "event_state", "unit_name", name="flow_transition_pkey"),
    )

    event_type: str = Field(description="e.g. ContextRegistration")
    event_state: str = Field(description="e.g. REQUESTED")
    unit_name: str = Field(description="e.g. workflow, task")

    route_path: str = Field()
    http_method: str = Field(default="POST")
    module_name: str = Field()

    route_module: Optional[str] = Field(default=None)
    service_module: Optional[str] = Field(default=None)
    model_module: Optional[str] = Field(default=None)
    table_name: Optional[str] = Field(default=None)

    next_event_type: Optional[str] = Field(default=None)
    next_event_state: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
